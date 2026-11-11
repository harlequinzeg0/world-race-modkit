//! The borderless window: the game's own window mode, sized to the monitor, with no border.
//!
//! Start-up always asks the window set-up for full screen (mode 2). Mode 1 is a normal window
//! with Direct3D 9 in windowed mode, which this hook sizes to the monitor and then restyles.
//!
//! The game hides the cursor over its window (`SetCursor(NULL)` on WM_SETCURSOR and
//! `ShowCursor(FALSE)`). In full screen that never mattered, but a borderless window still covers
//! the monitor after alt-tab, so WRSE gives the cursor back while another program is active.
use crate::hook::Hook;
use crate::log;
use std::ffi::c_void;
use std::sync::atomic::{AtomicI32, AtomicUsize, Ordering};

#[link(name = "user32")]
extern "system" {
    fn SetProcessDPIAware() -> i32;
    fn GetSystemMetrics(index: i32) -> i32;
    fn SetWindowLongA(window: *mut c_void, index: i32, value: i32) -> i32;
    fn SetWindowPos(window: *mut c_void, after: *mut c_void, x: i32, y: i32, width: i32, height: i32, flags: u32) -> i32;
    fn GetForegroundWindow() -> *mut c_void;
    fn ShowCursor(show: i32) -> i32;
    fn SetCursor(cursor: *mut c_void) -> *mut c_void;
    fn LoadCursorA(instance: *mut c_void, name: *const i8) -> *mut c_void;
    fn SetForegroundWindow(window: *mut c_void) -> i32;
    fn CallWindowProcA(previous: usize, window: *mut c_void, message: u32, wparam: usize, lparam: isize) -> isize;
}

const WINDOW_SET_UP: usize = 0x4CD970;
const WINDOW_SET_UP_BYTES: &[u8] = &[0xA1, 0x68, 0x46, 0x62, 0x00];
const GAME_WINDOW: usize = 0x61443C;
/// Set by the game's WM_ACTIVATEAPP handler. The intro movies wait while it is 0.
const GAME_ACTIVE: usize = 0x624695;
const CONFIG: usize = 0x611CEC;
const CONFIG_WIDTH: usize = 0x24;
const CONFIG_HEIGHT: usize = 0x2C;
const WINDOW_MODE: i32 = 1;

const SM_CXSCREEN: i32 = 0;
const SM_CYSCREEN: i32 = 1;
const GWL_STYLE: i32 = -16;
const WS_POPUP_VISIBLE: u32 = 0x9000_0000;
const SWP_FRAMECHANGED_SHOWWINDOW: u32 = 0x20 | 0x40;
const GWL_WNDPROC: i32 = -4;
const WM_SETCURSOR: u32 = 0x20;
const WM_ACTIVATEAPP: u32 = 0x1C;
const IDC_ARROW: usize = 32512;

type WindowSetUp = unsafe extern "C" fn(*const i8, i32, f32, f32, u32) -> u32;

static WINDOW_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static GAME_PROC: AtomicUsize = AtomicUsize::new(0);
/// `ShowCursor(TRUE)` calls made while another program was active, taken back on return.
static SHOWN: AtomicI32 = AtomicI32::new(0);

/// The mode and size the window set-up gets instead of the stock call's.
pub fn borderless_call(monitor: (i32, i32)) -> (i32, f32, f32) {
    (WINDOW_MODE, monitor.0 as f32, monitor.1 as f32)
}

fn give_cursor_back(message: u32, game_active: bool) -> bool {
    message == WM_SETCURSOR && !game_active
}

unsafe fn show_cursor() {
    let mut count = ShowCursor(1);
    SHOWN.fetch_add(1, Ordering::SeqCst);
    while count < 0 {
        count = ShowCursor(1);
        SHOWN.fetch_add(1, Ordering::SeqCst);
    }
    SetCursor(LoadCursorA(std::ptr::null_mut(), IDC_ARROW as *const i8));
}

unsafe fn take_cursor_back() {
    for _ in 0..SHOWN.swap(0, Ordering::SeqCst) {
        ShowCursor(0);
    }
}

unsafe extern "system" fn window_proc(window: *mut c_void, message: u32, wparam: usize, lparam: isize) -> isize {
    if message == WM_ACTIVATEAPP {
        log::line(&format!("game window active: {}", wparam != 0));
    }
    let game_active = GetForegroundWindow() == window;
    if give_cursor_back(message, game_active) {
        show_cursor();
        return 1;
    }
    if game_active {
        take_cursor_back();
    }
    CallWindowProcA(GAME_PROC.load(Ordering::SeqCst), window, message, wparam, lparam)
}

pub fn hooks() -> Vec<Hook> {
    vec![Hook { address: WINDOW_SET_UP, expected: WINDOW_SET_UP_BYTES, detour: window_detour as usize, original: Some(&WINDOW_ORIGINAL) }]
}

unsafe extern "C" fn window_detour(title: *const i8, mode: i32, width: f32, height: f32, depth: u32) -> u32 {
    let original: WindowSetUp = std::mem::transmute(WINDOW_ORIGINAL.load(Ordering::SeqCst));
    // Without this, Windows scaling makes the game see a smaller monitor and stretches the picture.
    SetProcessDPIAware();
    let monitor = (GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN));
    if monitor.0 <= 0 || monitor.1 <= 0 {
        log::line("cannot read the monitor size, so the game keeps full screen");
        return original(title, mode, width, height, depth);
    }
    // The rest of the game reads the size from the config, so it must match the window.
    let config = *(CONFIG as *const *mut u8);
    if !config.is_null() {
        *(config.add(CONFIG_WIDTH) as *mut i32) = monitor.0;
        *(config.add(CONFIG_HEIGHT) as *mut i32) = monitor.1;
    }
    let (mode, width, height) = borderless_call(monitor);
    let result = original(title, mode, width, height, depth);
    let window = *(GAME_WINDOW as *const *mut c_void);
    // The handle, not the result, says whether a window exists: the success value is not traced.
    if !window.is_null() {
        SetWindowLongA(window, GWL_STYLE, WS_POPUP_VISIBLE as i32);
        SetWindowPos(window, std::ptr::null_mut(), 0, 0, monitor.0, monitor.1, SWP_FRAMECHANGED_SHOWWINDOW);
        GAME_PROC.store(SetWindowLongA(window, GWL_WNDPROC, window_proc as usize as i32) as u32 as usize, Ordering::SeqCst);
        // The intro movies wait until the game is active. Full screen Direct3D forces that, but
        // a window must ask for it, and the game can miss its first WM_ACTIVATEAPP.
        let front = SetForegroundWindow(window) != 0;
        let active = *(GAME_ACTIVE as *const u8) != 0;
        log::line(&format!("game window brought to the front: {front}, game active: {active}"));
        if !active {
            CallWindowProcA(GAME_PROC.load(Ordering::SeqCst), window, WM_ACTIVATEAPP, 1, 0);
        }
        log::line(&format!("borderless window at {}x{}", monitor.0, monitor.1));
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn borderless_uses_window_mode_and_the_monitor_size() {
        assert_eq!(borderless_call((2560, 1440)), (1, 2560.0, 1440.0));
    }

    #[test]
    fn the_cursor_shows_over_the_game_only_while_another_program_is_active() {
        assert!(give_cursor_back(WM_SETCURSOR, false));
        assert!(!give_cursor_back(WM_SETCURSOR, true));
        assert!(!give_cursor_back(WM_ACTIVATEAPP, false));
    }

    #[test]
    fn window_hook_checks_its_bytes() {
        let hooks = hooks();
        assert_eq!(hooks.len(), 1);
        assert_eq!((hooks[0].address, hooks[0].expected), (0x4CD970, &[0xA1, 0x68, 0x46, 0x62, 0x00][..]));
        assert!(hooks[0].original.is_some());
    }
}
