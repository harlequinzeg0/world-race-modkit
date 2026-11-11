//! The car select grid. The game expects an even grid of `teams x width` cars, so short teams
//! fill their spare slots with their first car, and each team shows only its real length.
use crate::session::Session;
use std::collections::HashMap;

const STOCK_WIDTH: usize = 7;

/// The folders holding each car's wheel models, by car name. Rim 0 is the stock wheel.
pub fn rim_folders(session: &Session) -> HashMap<String, String> {
    session
        .cars
        .iter()
        .filter(|car| car.rim.is_some_and(|rim| rim > 0))
        .filter_map(|car| Some((car.name.clone(), format!("cars/generic_models/cache/rim_{}", car.rim?))))
        .collect()
}

pub fn team_slots(session: &Session, team: usize) -> &[u32] {
    &session.teams[team].slots
}

pub fn width(session: &Session) -> usize {
    session.teams.iter().map(|team| team.slots.len()).max().unwrap_or(0).max(STOCK_WIDTH)
}

pub fn last_slot(session: &Session, team: usize) -> usize {
    team_slots(session, team).len() - 1
}

/// The ring positions of the leftmost and rightmost icons around a selected slot. Stock code
/// counts half the ring each way, which reaches every icon only when the ring length is odd.
pub fn ring_ends(slot: i32, ring: i32) -> (i32, i32) {
    let first = (slot - (ring - 1) / 2).rem_euclid(ring);
    (first, (first + ring - 1) % ring)
}

/// Car list indexes for the whole grid, row by row.
pub fn grid_indices(session: &Session, width: usize) -> Vec<u32> {
    let mut grid = Vec::with_capacity(session.teams.len() * width);
    for team in &session.teams {
        grid.extend((0..width).map(|slot| *team.slots.get(slot).unwrap_or(&team.slots[0])));
    }
    grid
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::session::{Car, Team};

    fn team(slots: &[u32]) -> Team {
        Team { id: "t".to_string(), slots: slots.to_vec(), logo: None, base_team: 0 }
    }

    fn session(rows: &[&[u32]]) -> Session {
        Session {
            format: 1,
            roots: vec!["r".to_string()],
            save_dir: "s".to_string(),
            log_path: "l".to_string(),
            cars: Vec::new(),
            teams: rows.iter().map(|r| team(r)).collect(),
            text: Default::default(),
            display: Default::default(),
            controller: Default::default(),
        }
    }

    fn car(name: &str, rim: Option<u32>) -> Car {
        Car { index: 35, team: 0, name: name.to_string(), based_on: "b".to_string(), rim }
    }

    #[test]
    fn a_rim_colour_has_its_own_wheel_folder() {
        let mut s = session(&[&[0]]);
        s.cars = vec![car("plain", None), car("painted", Some(3))];
        let folders = HashMap::from([("painted".to_string(), "cars/generic_models/cache/rim_3".to_string())]);
        assert_eq!(rim_folders(&s), folders);
    }

    #[test]
    fn the_first_rim_colour_is_the_stock_wheel() {
        let mut s = session(&[&[0]]);
        s.cars = vec![car("painted", Some(0))];
        assert!(rim_folders(&s).is_empty());
    }

    #[test]
    fn slots_come_from_the_team() {
        let s = session(&[&[0, 1], &[2, 3, 35]]);
        assert_eq!(team_slots(&s, 1), [2, 3, 35]);
    }

    #[test]
    fn width_is_the_longest_team() {
        assert_eq!(width(&session(&[&[0; 9], &[0; 7]])), 9);
    }

    #[test]
    fn width_is_never_below_stock() {
        assert_eq!(width(&session(&[&[0; 3]])), 7);
    }

    #[test]
    fn wrap_uses_each_teams_own_length() {
        let s = session(&[&[0; 9], &[0; 7], &[0; 1]]);
        assert_eq!((last_slot(&s, 0), last_slot(&s, 1), last_slot(&s, 2)), (8, 6, 0));
    }

    #[test]
    fn ring_ends_match_stock_on_an_odd_ring() {
        assert_eq!(ring_ends(3, 7), (0, 6));
        assert_eq!(ring_ends(0, 7), (4, 3));
    }

    #[test]
    fn ring_ends_cover_every_icon_on_an_even_ring() {
        for ring in [8, 10, 16] {
            for slot in 0..ring {
                let (first, last) = ring_ends(slot, ring);
                assert_eq!((last + 1) % ring, first, "slot {slot} of {ring}");
            }
        }
        assert_eq!(ring_ends(0, 8), (5, 4));
    }

    #[test]
    fn ring_ends_accept_the_no_slot_value() {
        assert_eq!(ring_ends(-1, 7), (3, 2));
    }

    #[test]
    fn grid_is_even_and_spare_slots_repeat_the_first_car() {
        let grid = grid_indices(&session(&[&[4, 5], &[6]]), 3);
        assert_eq!(grid, [4, 5, 4, 6, 6, 6]);
    }
}
