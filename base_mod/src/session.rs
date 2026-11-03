//! The session file that the Python tool writes before launch.
use serde::Deserialize;
use std::collections::HashMap;

/// The newest session format this DLL understands.
pub const FORMAT: u32 = 1;

pub const STOCK_CARS: u32 = 35;
pub const STOCK_TEAMS: usize = 5;
pub const STOCK_TEXT: u32 = 574;
/// The game loads `generic_wheel_high_0` to `_4`. They differ only in their rim colour.
pub const RIM_COLOURS: u32 = 5;

/// The selector sizes its arrays with signed 8-bit values holding `width * 4`. Tests reached 9.
pub const MAX_WIDTH: usize = 16;
/// The team wrap is a signed 8-bit value. Tests reached 6.
pub const MAX_TEAMS: usize = 16;

#[derive(Debug, Deserialize)]
pub struct Session {
    pub format: u32,
    pub roots: Vec<String>,
    pub save_dir: String,
    pub log_path: String,
    #[serde(default)]
    pub cars: Vec<Car>,
    #[serde(default)]
    pub teams: Vec<Team>,
    /// New text names and their IDs in the merged .msg files.
    #[serde(default)]
    pub text: HashMap<String, u32>,
}

/// An added car. `index` is its place in the merged `car_info.xml`.
#[derive(Debug, Deserialize)]
pub struct Car {
    pub index: u32,
    pub team: usize,
    pub name: String,
    pub based_on: String,
    /// The wheel texture to use. Without one, the car's rims follow its team number.
    #[serde(default)]
    pub rim: Option<u32>,
}

/// A row on the car select screen. `slots` holds indexes into the merged car list, in order.
#[derive(Debug, Deserialize)]
pub struct Team {
    pub id: String,
    pub slots: Vec<u32>,
    pub logo: Option<Logo>,
    pub base_team: usize,
}

#[derive(Debug, Deserialize)]
pub struct Logo {
    pub texture: String,
    #[serde(rename = "box")]
    pub box_name: String,
}

fn check_teams(session: &Session) -> Result<(), String> {
    if session.teams.is_empty() {
        return match session.cars.is_empty() {
            true => Ok(()),
            false => Err("session adds cars but has no teams".to_string()),
        };
    }
    if !(STOCK_TEAMS..=MAX_TEAMS).contains(&session.teams.len()) {
        return Err(format!("session has {} teams, and the game needs {STOCK_TEAMS} to {MAX_TEAMS}", session.teams.len()));
    }
    let last_car = STOCK_CARS + session.cars.len() as u32;
    for (index, team) in session.teams.iter().enumerate() {
        if team.slots.is_empty() {
            return Err(format!("team {} has no cars", team.id));
        }
        if team.slots.len() > MAX_WIDTH {
            return Err(format!("team {} has {} cars, and the limit is {MAX_WIDTH}", team.id, team.slots.len()));
        }
        if let Some(slot) = team.slots.iter().find(|slot| **slot >= last_car) {
            return Err(format!("team {} uses car {slot}, but there are only {last_car} cars", team.id));
        }
        if index >= STOCK_TEAMS && team.logo.is_none() {
            return Err(format!("added team {} has no logo", team.id));
        }
        if team.base_team >= STOCK_TEAMS {
            return Err(format!("team {} has a base team that is not a stock team", team.id));
        }
    }
    Ok(())
}

pub fn parse(text: &str) -> Result<Session, String> {
    let session: Session = serde_json::from_str(text).map_err(|e| format!("session file is not valid: {e}"))?;
    if session.format > FORMAT {
        return Err(format!("session format {} is newer than this DLL's {FORMAT}", session.format));
    }
    if session.roots.is_empty() {
        return Err("session file has no file roots".to_string());
    }
    check_teams(&session)?;
    if let Some(car) = session.cars.iter().find(|car| car.rim.is_some_and(|rim| rim >= RIM_COLOURS)) {
        return Err(format!("car {} has a rim colour past the {RIM_COLOURS} wheel textures", car.name));
    }
    if let Some((name, id)) = session.text.iter().find(|(_, id)| **id < STOCK_TEXT) {
        return Err(format!("new text {name} has the stock ID {id}"));
    }
    Ok(session)
}

#[cfg(test)]
mod tests {
    use super::*;

    const GOOD: &str = r#"{"format": 1, "roots": ["D:/gen", "D:/mod"], "save_dir": "D:/save", "log_path": "D:/wrse.log"}"#;

    #[test]
    fn accepts_a_good_file() {
        let session = parse(GOOD).unwrap();
        assert_eq!(session.format, 1);
        assert_eq!(session.roots, ["D:/gen", "D:/mod"]);
        assert_eq!(session.save_dir, "D:/save");
        assert_eq!(session.log_path, "D:/wrse.log");
    }

    #[test]
    fn refuses_bad_json() {
        assert!(parse("{not json").is_err());
    }

    fn with_teams(cars: &str, teams: &str) -> String {
        GOOD.replace(r#"{"format": 1,"#, &format!(r#"{{"format": 1, "cars": {cars}, "teams": {teams},"#))
    }

    fn stock_teams() -> String {
        let row = |id: &str, first: u32, base: u32| {
            let slots: Vec<u32> = (first..first + 7).collect();
            format!(r#"{{"id": "{id}", "slots": {slots:?}, "logo": null, "base_team": {base}}}"#)
        };
        ["a", "b", "c", "d", "e"].iter().enumerate().map(|(i, id)| row(id, i as u32 * 7, i as u32)).collect::<Vec<_>>().join(",")
    }

    const ADDED_CAR: &str = r#"[{"index": 35, "team": 5, "name": "neon", "based_on": "ballistic"}]"#;
    const ADDED_TEAM: &str = r#"{"id": "neon_riders", "slots": [35], "logo": {"texture": "misc/cache/flash", "box": "flash_1"}, "base_team": 2}"#;

    #[test]
    fn cars_and_teams_are_optional() {
        let session = parse(GOOD).unwrap();
        assert!(session.cars.is_empty() && session.teams.is_empty());
    }

    #[test]
    fn accepts_an_added_team() {
        let session = parse(&with_teams(ADDED_CAR, &format!("[{},{ADDED_TEAM}]", stock_teams()))).unwrap();
        assert_eq!(session.cars[0].name, "neon");
        assert_eq!(session.teams[5].logo.as_ref().unwrap().box_name, "flash_1");
    }

    #[test]
    fn a_car_needs_no_rim_colour() {
        let session = parse(&with_teams(ADDED_CAR, &format!("[{},{ADDED_TEAM}]", stock_teams()))).unwrap();
        assert_eq!(session.cars[0].rim, None);
    }

    #[test]
    fn a_car_can_choose_a_stock_rim_colour() {
        let car = ADDED_CAR.replace(r#""team": 5,"#, r#""team": 5, "rim": 4,"#);
        let session = parse(&with_teams(&car, &format!("[{},{ADDED_TEAM}]", stock_teams()))).unwrap();
        assert_eq!(session.cars[0].rim, Some(4));
    }

    #[test]
    fn refuses_a_rim_colour_past_the_wheel_textures() {
        let car = ADDED_CAR.replace(r#""team": 5,"#, r#""team": 5, "rim": 5,"#);
        let error = parse(&with_teams(&car, &format!("[{},{ADDED_TEAM}]", stock_teams()))).unwrap_err();
        assert!(error.contains("neon"), "{error}");
    }

    #[test]
    fn refuses_a_team_with_no_cars() {
        let team = ADDED_TEAM.replace("[35]", "[]");
        let error = parse(&with_teams(ADDED_CAR, &format!("[{},{team}]", stock_teams()))).unwrap_err();
        assert!(error.contains("neon_riders"), "{error}");
    }

    #[test]
    fn refuses_a_slot_past_the_last_car() {
        let team = ADDED_TEAM.replace("[35]", "[36]");
        let error = parse(&with_teams(ADDED_CAR, &format!("[{},{team}]", stock_teams()))).unwrap_err();
        assert!(error.contains("36"), "{error}");
    }

    #[test]
    fn refuses_an_added_team_with_no_logo() {
        let team = ADDED_TEAM.replace(r#"{"texture": "misc/cache/flash", "box": "flash_1"}"#, "null");
        let error = parse(&with_teams(ADDED_CAR, &format!("[{},{team}]", stock_teams()))).unwrap_err();
        assert!(error.contains("logo"), "{error}");
    }

    #[test]
    fn refuses_a_base_team_that_is_not_stock() {
        let team = ADDED_TEAM.replace(r#""base_team": 2"#, r#""base_team": 5"#);
        let error = parse(&with_teams(ADDED_CAR, &format!("[{},{team}]", stock_teams()))).unwrap_err();
        assert!(error.contains("base"), "{error}");
    }

    #[test]
    fn refuses_fewer_than_the_stock_teams() {
        assert!(parse(&with_teams("[]", r#"[{"id": "a", "slots": [0], "logo": null, "base_team": 0}]"#)).is_err());
    }

    #[test]
    fn refuses_a_team_too_long_for_the_game() {
        let slots: Vec<u32> = (0..MAX_WIDTH as u32 + 1).collect();
        let team = ADDED_TEAM.replace("[35]", &format!("{slots:?}"));
        let error = parse(&with_teams(ADDED_CAR, &format!("[{},{team}]", stock_teams()))).unwrap_err();
        assert!(error.contains("neon_riders"), "{error}");
    }

    #[test]
    fn accepts_new_text_names() {
        let text = GOOD.replace(r#"{"format": 1,"#, r#"{"format": 1, "text": {"CAR_NEON": 574},"#);
        assert_eq!(parse(&text).unwrap().text["CAR_NEON"], 574);
    }

    #[test]
    fn refuses_a_new_text_id_inside_the_stock_table() {
        let text = GOOD.replace(r#"{"format": 1,"#, r#"{"format": 1, "text": {"CAR_NEON": 573},"#);
        let error = parse(&text).unwrap_err();
        assert!(error.contains("CAR_NEON"), "{error}");
    }

    #[test]
    fn refuses_added_cars_with_no_teams() {
        let error = parse(&with_teams(ADDED_CAR, "[]")).unwrap_err();
        assert!(error.contains("teams"), "{error}");
    }

    #[test]
    fn refuses_a_missing_field() {
        assert!(parse(r#"{"format": 1, "roots": ["a"], "save_dir": "b"}"#).is_err());
    }

    #[test]
    fn refuses_a_newer_format() {
        let text = GOOD.replace(r#""format": 1"#, &format!(r#""format": {}"#, FORMAT + 1));
        let error = parse(&text).unwrap_err();
        assert!(error.contains("format"), "{error}");
    }

    #[test]
    fn refuses_empty_roots() {
        let text = GOOD.replace(r#"["D:/gen", "D:/mod"]"#, "[]");
        let error = parse(&text).unwrap_err();
        assert!(error.contains("roots"), "{error}");
    }
}
