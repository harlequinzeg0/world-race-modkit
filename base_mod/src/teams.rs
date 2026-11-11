//! The car select grid. The game expects an even grid of `teams x width` cars, so short teams
//! fill their spare slots with their first car, and each team shows only its real length.
use crate::session::Session;

const STOCK_WIDTH: usize = 7;

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
    use crate::session::Team;

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
            rims: Default::default(),
        }
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
