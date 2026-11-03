//! Puts all teams in the opponent shuffle. The game shuffles exactly 5 teams and picks opponents
//! by team number, so before it runs, 5 teams chosen from all teams become numbers 0 to 4.

pub const PICKED_TEAMS: usize = 5;

/// Matches no number the game shuffles, so an unpicked team's cars are never drawn.
pub const UNPICKED: u32 = 0x7F;

pub struct PickCar {
    pub team: usize,
    pub ai: bool,
    pub player: bool,
    /// The game's draw never reaches the last list entry.
    pub drawable: bool,
}

/// The game draws cars until one fits, so a team with no free AI car would hang it.
pub fn free_teams(team_count: usize, cars: &[PickCar]) -> Vec<usize> {
    let free = |team: usize| cars.iter().any(|car| car.team == team && car.ai && !car.player && car.drawable);
    (0..team_count).filter(|team| free(*team)).collect()
}

/// None when too few teams are free. Then the stock numbers must stay.
pub fn pick(free: &[usize], seed: u32) -> Option<Vec<usize>> {
    if free.len() < PICKED_TEAMS {
        return None;
    }
    let mut teams = free.to_vec();
    let mut state = seed | 1;
    for i in (1..teams.len()).rev() {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
        teams.swap(i, state as usize % (i + 1));
    }
    teams.truncate(PICKED_TEAMS);
    Some(teams)
}

pub fn team_number(picked: &[usize], team: usize) -> u32 {
    picked.iter().position(|t| *t == team).map_or(UNPICKED, |position| position as u32)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn car(team: usize) -> PickCar {
        PickCar { team, ai: true, player: false, drawable: true }
    }

    fn all_teams() -> Vec<PickCar> {
        (0..6).map(car).collect()
    }

    #[test]
    fn every_team_with_a_free_car_counts() {
        assert_eq!(free_teams(6, &all_teams()), [0, 1, 2, 3, 4, 5]);
    }

    #[test]
    fn a_team_with_no_ai_car_is_not_free() {
        let mut cars = all_teams();
        cars[5].ai = false;
        assert_eq!(free_teams(6, &cars), [0, 1, 2, 3, 4]);
    }

    #[test]
    fn a_team_whose_only_ai_car_is_the_players_is_not_free() {
        let mut cars = all_teams();
        cars[5].player = true;
        assert_eq!(free_teams(6, &cars), [0, 1, 2, 3, 4]);
    }

    #[test]
    fn a_team_whose_only_ai_car_is_the_last_list_entry_is_not_free() {
        let mut cars = all_teams();
        cars[5].drawable = false;
        assert_eq!(free_teams(6, &cars), [0, 1, 2, 3, 4]);
    }

    #[test]
    fn a_second_ai_car_keeps_the_team_free() {
        let mut cars = all_teams();
        cars[5].player = true;
        cars.push(car(5));
        assert_eq!(free_teams(6, &cars), [0, 1, 2, 3, 4, 5]);
    }

    #[test]
    fn a_pick_is_five_different_teams() {
        for seed in 1..200 {
            let mut picked = pick(&[0, 1, 2, 3, 4, 5, 6], seed).unwrap();
            picked.sort();
            picked.dedup();
            assert_eq!(picked.len(), 5, "seed {seed}");
        }
    }

    #[test]
    fn every_team_gets_picked_over_many_races() {
        let mut seen = [false; 7];
        for seed in 1..200 {
            for team in pick(&[0, 1, 2, 3, 4, 5, 6], seed).unwrap() {
                seen[team] = true;
            }
        }
        assert_eq!(seen, [true; 7]);
    }

    #[test]
    fn a_seed_of_zero_still_shuffles() {
        assert!(pick(&[0, 1, 2, 3, 4, 5], 0).is_some());
    }

    #[test]
    fn fewer_than_five_free_teams_gives_no_pick() {
        assert_eq!(pick(&[0, 1, 2, 3], 7), None);
    }

    #[test]
    fn picked_teams_number_from_zero_and_others_match_nothing() {
        let picked = [5, 0, 2, 1, 3];
        assert_eq!(team_number(&picked, 5), 0);
        assert_eq!(team_number(&picked, 3), 4);
        assert_eq!(team_number(&picked, 4), UNPICKED);
    }
}
