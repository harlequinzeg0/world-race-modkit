//! Xbox controller input for player 1, through two hooks on the game's input code.
//!
//! The input update reads the pad once a frame and holds keyboard keys for menus, pause and
//! cameras. The player control function then adds the pad's driving to the car's controls.
//! Player 1 stays on "Keyboard" in Config.cfg, so the game never reads the pad itself.
use crate::hook::Hook;
use crate::log;
use crate::pad::{self, Context, Keys, Layout, Pad};
use crate::session::Session;
use crate::xinput::Reader;
use std::ffi::c_void;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

#[link(name = "user32")]
extern "system" {
    fn GetForegroundWindow() -> *mut c_void;
}

const INPUT_UPDATE: usize = 0x4E0FC0;
const INPUT_UPDATE_BYTES: &[u8] = &[0x51, 0x53, 0x55, 0x56, 0x8B, 0xF1];
const PLAYER_CONTROL: usize = 0x4CBC90;
const PLAYER_CONTROL_BYTES: &[u8] = &[0x81, 0xEC, 0xA4, 0x00, 0x00, 0x00];
const GAME_WINDOW: usize = 0x61443C;

// Input manager fields: two keyboard state buffers that swap each frame.
const KEYBOARD_BUFFERS: usize = 0x2CD8;
const KEYBOARD_INDEX: usize = 0x2CC4;
const KEYBOARD_SIZE: usize = 0x100;
const KEY_DOWN: u8 = 0x80;

// Player control object fields.
const CONTROL_STEER: usize = 0x10;
const CONTROL_FORCED_BRAKE: usize = 0x45;
const CONTROL_SKIP: usize = 0x4C;
const CONTROL_PLAYER: usize = 0x20;
const CONTROL_PAUSE: usize = 0x30;
const PAUSE_FLAG: usize = 0x58;
const PLAYER_ONE: i32 = 0;

type InputUpdate = unsafe extern "thiscall" fn(*mut u8, u32, u32) -> u32;
type PlayerControl = unsafe extern "thiscall" fn(*mut u8, f32) -> u32;

static INPUT_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static CONTROL_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static STATE: Mutex<Option<State>> = Mutex::new(None);

struct State {
    /// Loaded on the first frame, not in DllMain, where loading a DLL can hang start-up.
    reader: Option<Option<Reader>>,
    connected: bool,
    layout: Layout,
    keys: Keys,
    pad: Pad,
    /// The pad as the control function last saw it, for the stunt combo presses.
    driven: Pad,
    frame: u32,
    race_frame: Option<u32>,
    /// The keys the pad held last frame, logged when they change.
    held_keys: Vec<u8>,
    context: Option<Context>,
    paused: bool,
    /// Player 1's control flags as last logged: paused, skip, forced brake.
    flags: Option<(bool, bool, bool)>,
}

/// XInput reads the pad even when the game is in the background, so focus decides.
pub fn frame_pad(focused: bool, read: Option<Pad>) -> Pad {
    match focused {
        true => read.unwrap_or_default(),
        false => Pad::default(),
    }
}

/// The pad drives only while the race runs. The control function also runs while paused.
pub fn pad_drives(paused: bool, skip: u8, forced_brake: u8) -> bool {
    !paused && skip == 0 && forced_brake == 0
}

/// A frame where the pad drove, this frame or the last, means a race is on.
pub fn context(frame: u32, race_frame: Option<u32>, paused: bool) -> Context {
    match race_frame {
        Some(race) if frame.wrapping_sub(race) <= 1 && !paused => Context::Race,
        _ => Context::Menu,
    }
}

fn sites() -> Vec<Hook> {
    vec![
        Hook { address: INPUT_UPDATE, expected: INPUT_UPDATE_BYTES, detour: input_detour as usize, original: Some(&INPUT_ORIGINAL) },
        Hook { address: PLAYER_CONTROL, expected: PLAYER_CONTROL_BYTES, detour: control_detour as usize, original: Some(&CONTROL_ORIGINAL) },
    ]
}

pub fn hooks(session: &Session) -> Vec<Hook> {
    *STATE.lock().unwrap() = Some(State {
        reader: None,
        connected: false,
        layout: session.controller.layout,
        keys: Keys::default(),
        pad: Pad::default(),
        driven: Pad::default(),
        frame: 0,
        race_frame: None,
        held_keys: Vec::new(),
        context: None,
        paused: false,
        flags: None,
    });
    sites()
}

unsafe fn focused() -> bool {
    let window = *(GAME_WINDOW as *const *mut c_void);
    !window.is_null() && GetForegroundWindow() == window
}

impl State {
    fn read(&mut self) -> Option<Pad> {
        let reader = self.reader.get_or_insert_with(|| {
            let reader = Reader::load();
            if reader.is_none() {
                log::line("no XInput DLL, so the Xbox controller is off");
            }
            reader
        });
        let pad = reader.as_mut()?.read();
        if pad.is_some() != self.connected {
            self.connected = pad.is_some();
            log::line(if self.connected { "Xbox controller connected" } else { "Xbox controller disconnected" });
        }
        pad
    }

    unsafe fn input_frame(&mut self, manager: *mut u8) {
        let focused = focused();
        let read = if focused { self.read() } else { None };
        self.pad = frame_pad(focused, read);
        self.frame = self.frame.wrapping_add(1);
        let context = context(self.frame, self.race_frame, self.paused);
        if self.context != Some(context) {
            self.context = Some(context);
            log::line(&format!("controller context: {context:?}"));
        }
        let index = *(manager.add(KEYBOARD_INDEX) as *const u32) as usize;
        if index > 1 {
            return;
        }
        let buffer = std::slice::from_raw_parts_mut(manager.add(KEYBOARD_BUFFERS + index * KEYBOARD_SIZE), KEYBOARD_SIZE);
        let keys = self.keys.keys(&self.pad, context, &self.layout);
        for key in &keys {
            buffer[*key as usize] |= KEY_DOWN;
        }
        if keys != self.held_keys {
            log::line(&format!("pad keys: {keys:02x?}"));
            self.held_keys = keys;
        }
    }

    unsafe fn control_frame(&mut self, control: *mut u8) {
        let pause = *(control.add(CONTROL_PAUSE) as *const *const u8);
        self.paused = !pause.is_null() && *pause.add(PAUSE_FLAG) != 0;
        let (skip, forced_brake) = (*control.add(CONTROL_SKIP), *control.add(CONTROL_FORCED_BRAKE));
        let flags = (self.paused, skip != 0, forced_brake != 0);
        if self.flags != Some(flags) {
            self.flags = Some(flags);
            log::line(&format!("player 1 controls: paused {}, skip {}, forced brake {}", flags.0, flags.1, flags.2));
        }
        let before = std::mem::replace(&mut self.driven, self.pad);
        if !pad_drives(self.paused, skip, forced_brake) {
            return;
        }
        self.race_frame = Some(self.frame);
        let drive = pad::drive(&self.pad, &before, &self.layout, self.keys.silent());
        pad::add_drive(std::slice::from_raw_parts_mut(control.add(CONTROL_STEER), pad::CONTROL_BYTES), &drive);
    }
}

unsafe extern "thiscall" fn input_detour(manager: *mut u8, first: u32, second: u32) -> u32 {
    let original: InputUpdate = std::mem::transmute(INPUT_ORIGINAL.load(Ordering::SeqCst));
    let result = original(manager, first, second);
    if let Some(state) = STATE.lock().unwrap().as_mut() {
        state.input_frame(manager);
    }
    result
}

unsafe extern "thiscall" fn control_detour(control: *mut u8, step: f32) -> u32 {
    let original: PlayerControl = std::mem::transmute(CONTROL_ORIGINAL.load(Ordering::SeqCst));
    let result = original(control, step);
    if *(control.add(CONTROL_PLAYER) as *const i32) == PLAYER_ONE {
        if let Some(state) = STATE.lock().unwrap().as_mut() {
            state.control_frame(control);
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn full() -> Pad {
        Pad { buttons: pad::BUTTON_A, right_trigger: 255, thumb_lx: 32767, ..Pad::default() }
    }

    #[test]
    fn no_output_when_not_focused() {
        assert_eq!(frame_pad(false, Some(full())), Pad::default());
    }

    #[test]
    fn unplugged_pad_gives_no_output() {
        assert_eq!(frame_pad(true, None), Pad::default());
    }

    #[test]
    fn a_focused_pad_is_used() {
        assert_eq!(frame_pad(true, Some(full())), full());
    }

    #[test]
    fn a_race_frame_this_frame_or_last_is_a_race() {
        assert_eq!(context(10, Some(10), false), Context::Race);
        assert_eq!(context(10, Some(9), false), Context::Race);
    }

    #[test]
    fn no_race_frame_lately_is_a_menu() {
        assert_eq!(context(10, None, false), Context::Menu);
        assert_eq!(context(10, Some(7), false), Context::Menu);
    }

    #[test]
    fn a_paused_race_is_a_menu() {
        assert_eq!(context(10, Some(10), true), Context::Menu);
    }

    #[test]
    fn the_pad_drives_only_a_running_race() {
        assert!(pad_drives(false, 0, 0));
        assert!(!pad_drives(true, 0, 0));
        assert!(!pad_drives(false, 1, 0));
        assert!(!pad_drives(false, 0, 1));
    }

    #[test]
    fn hooks_check_their_bytes() {
        let sites = sites();
        assert_eq!(sites.len(), 2);
        assert_eq!((sites[0].address, sites[0].expected), (0x4E0FC0, &[0x51, 0x53, 0x55, 0x56, 0x8B, 0xF1][..]));
        assert_eq!((sites[1].address, sites[1].expected), (0x4CBC90, &[0x81, 0xEC, 0xA4, 0x00, 0x00, 0x00][..]));
        assert!(sites.iter().all(|site| site.expected.len() >= 5 && site.original.is_some()));
    }
}
