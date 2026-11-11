//! Reads the first connected Xbox controller through XInput, loaded while the game runs.
use crate::pad::Pad;
use std::ffi::c_void;

extern "system" {
    fn LoadLibraryA(name: *const i8) -> *mut c_void;
    fn GetProcAddress(module: *mut c_void, name: *const i8) -> *mut c_void;
    fn GetTickCount() -> u32;
}

/// Windows 8 and later have the first; Vista and 7 have the second.
const LIBRARIES: [&[u8]; 2] = [b"xinput1_4.dll\0", b"xinput9_1_0.dll\0"];
const USERS: u32 = 4;
const ERROR_SUCCESS: u32 = 0;
/// XInput is slow to answer for an empty slot, so look for a new controller only this often.
const SEARCH_INTERVAL_MS: u32 = 1_000;

#[repr(C)]
#[derive(Default)]
struct State {
    packet: u32,
    pad: Pad,
}

type GetState = unsafe extern "system" fn(u32, *mut State) -> u32;

fn search_due(now: u32, last: Option<u32>) -> bool {
    last.map_or(true, |last| now.wrapping_sub(last) >= SEARCH_INTERVAL_MS)
}

pub struct Reader {
    get_state: GetState,
    user: Option<u32>,
    last_search: Option<u32>,
}

impl Reader {
    /// None when Windows has no XInput DLL.
    pub fn load() -> Option<Reader> {
        LIBRARIES.iter().find_map(|name| unsafe {
            let module = LoadLibraryA(name.as_ptr() as *const i8);
            if module.is_null() {
                return None;
            }
            let function = GetProcAddress(module, b"XInputGetState\0".as_ptr() as *const i8);
            (!function.is_null()).then(|| Reader { get_state: std::mem::transmute::<*mut c_void, GetState>(function), user: None, last_search: None })
        })
    }

    fn state(&self, user: u32) -> Option<Pad> {
        let mut state = State::default();
        (unsafe { (self.get_state)(user, &mut state) } == ERROR_SUCCESS).then_some(state.pad)
    }

    /// The controller's state now, or None when no controller is connected.
    pub fn read(&mut self) -> Option<Pad> {
        if let Some(user) = self.user {
            if let Some(pad) = self.state(user) {
                return Some(pad);
            }
            self.user = None;
        }
        let now = unsafe { GetTickCount() };
        if !search_due(now, self.last_search) {
            return None;
        }
        self.last_search = Some(now);
        let (user, pad) = (0..USERS).find_map(|user| self.state(user).map(|pad| (user, pad)))?;
        self.user = Some(user);
        Some(pad)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_first_search_is_at_once() {
        assert!(search_due(5, None));
    }

    #[test]
    fn searches_at_most_once_a_second() {
        assert!(!search_due(1_500, Some(1_000)));
        assert!(search_due(2_000, Some(1_000)));
    }

    #[test]
    fn the_clock_wrapping_still_searches() {
        assert!(search_due(500, Some(u32::MAX - 600)));
    }
}
