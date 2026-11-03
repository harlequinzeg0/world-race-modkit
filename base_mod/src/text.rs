//! New text names. The game finds text by name in a table compiled into the EXE, so names added
//! by the session are answered here, and the stock table answers the rest.
use crate::hook::Hook;
use crate::session;
use crate::session::Session;
use std::collections::HashMap;
use std::ffi::CStr;
use std::sync::atomic::{AtomicUsize, Ordering};

const FIND_TEXT: usize = 0x4A3700;

static ORIGINAL: AtomicUsize = AtomicUsize::new(0);

pub fn lookup(table: &HashMap<String, u32>, name: &str) -> Option<u32> {
    table.get(name).copied()
}

unsafe extern "C" fn find_detour(id: *mut u32, name: *const i8) -> *mut u32 {
    if !name.is_null() {
        if let Some(found) = lookup(&session().text, &CStr::from_ptr(name).to_string_lossy()) {
            *id = found;
            return id;
        }
    }
    let original: unsafe extern "C" fn(*mut u32, *const i8) -> *mut u32 = std::mem::transmute(ORIGINAL.load(Ordering::SeqCst));
    original(id, name)
}

pub fn hooks(session: &Session) -> Vec<Hook> {
    if session.text.is_empty() {
        return Vec::new();
    }
    vec![Hook { address: FIND_TEXT, expected: &[0x53, 0x8B, 0x5C, 0x24, 0x0C], detour: find_detour as usize, original: Some(&ORIGINAL) }]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_session_name_gives_its_id() {
        let table = HashMap::from([("CAR_NEON".to_string(), 574)]);
        assert_eq!(lookup(&table, "CAR_NEON"), Some(574));
    }

    #[test]
    fn a_stock_name_is_left_to_the_game() {
        let table = HashMap::from([("CAR_NEON".to_string(), 574)]);
        assert_eq!(lookup(&table, "MAIN_MENU"), None);
    }
}
