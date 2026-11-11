//! How an Xbox controller becomes game input. Pure logic: no Windows calls.
//!
//! Driving goes straight into the game's control bytes, so steering, throttle and flips are
//! analog. Menus, pause and cameras go in as held keyboard keys, because the game reads those
//! from fixed keys.
use serde::Deserialize;

pub const DPAD_UP: u16 = 0x0001;
pub const DPAD_DOWN: u16 = 0x0002;
pub const DPAD_LEFT: u16 = 0x0004;
pub const DPAD_RIGHT: u16 = 0x0008;
pub const BUTTON_START: u16 = 0x0010;
pub const BUTTON_BACK: u16 = 0x0020;
pub const BUTTON_LEFT_THUMB: u16 = 0x0040;
pub const BUTTON_RIGHT_THUMB: u16 = 0x0080;
pub const BUTTON_LB: u16 = 0x0100;
pub const BUTTON_RB: u16 = 0x0200;
pub const BUTTON_A: u16 = 0x1000;
pub const BUTTON_B: u16 = 0x2000;
pub const BUTTON_X: u16 = 0x4000;
pub const BUTTON_Y: u16 = 0x8000;

// Microsoft's recommended XInput values.
const LEFT_DEAD_ZONE: i32 = 7849;
const RIGHT_DEAD_ZONE: i32 = 8689;
const TRIGGER_THRESHOLD: i32 = 30;
const STICK_MAX: i32 = 32767;
const TRIGGER_MAX: i32 = 255;
/// The game's control bytes run from -127 to 127.
const FULL: i32 = 127;
/// A stick moves the menu selection past half of its travel.
const MENU_PUSH: i32 = 16384;

pub const DIK_ESCAPE: u8 = 0x01;
pub const DIK_RETURN: u8 = 0x1C;
pub const DIK_T: u8 = 0x14;
pub const DIK_Y: u8 = 0x15;
pub const DIK_UP: u8 = 0xC8;
pub const DIK_LEFT: u8 = 0xCB;
pub const DIK_RIGHT: u8 = 0xCD;
pub const DIK_DOWN: u8 = 0xD0;

/// Offsets from the steer byte (control object + 0x10) to the bytes `add_drive` writes.
pub const STEER: usize = 0;
pub const THROTTLE: usize = 1;
pub const HANDBRAKE: usize = 3;
pub const FLIP: usize = 4;
pub const NITRO: usize = 5;
/// Press edges of the four stunt combo inputs, control object + 0x39 to + 0x3C.
pub const COMBOS: usize = 0x29;
pub const CONTROL_BYTES: usize = COMBOS + 4;

/// An Xbox input that a button action can use. The names match the Mod Manager's.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Input {
    A,
    B,
    X,
    Y,
    Lb,
    Rb,
    Lt,
    Rt,
    Back,
    LeftStickClick,
    RightStickClick,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
pub enum Stick {
    #[serde(rename = "left_stick")]
    Left,
    #[serde(rename = "right_stick")]
    Right,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Layout {
    pub accelerate: Input,
    pub brake: Input,
    pub second_brake: Input,
    pub steer: Stick,
    pub flip: Stick,
    pub handbrake: Input,
    pub nitro: Input,
    pub camera_change: Input,
    pub camera_behind: Input,
}

impl Default for Layout {
    fn default() -> Self {
        Layout {
            accelerate: Input::Rt,
            brake: Input::Lt,
            second_brake: Input::Y,
            steer: Stick::Left,
            flip: Stick::Left,
            handbrake: Input::A,
            nitro: Input::B,
            camera_change: Input::X,
            camera_behind: Input::RightStickClick,
        }
    }
}

/// The `XINPUT_GAMEPAD` layout, so XInput can fill it directly.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Pad {
    pub buttons: u16,
    pub left_trigger: u8,
    pub right_trigger: u8,
    pub thumb_lx: i16,
    pub thumb_ly: i16,
    pub thumb_rx: i16,
    pub thumb_ry: i16,
}

/// The pad's part of one frame's car controls, in the game's units.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Drive {
    pub steer: i8,
    pub throttle: i8,
    pub handbrake: u8,
    pub flip: i8,
    pub nitro: bool,
    pub combos: [bool; 4],
}

/// A paused race counts as a menu.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Context {
    Race,
    #[default]
    Menu,
}

fn axis(value: i16, dead_zone: i32) -> i32 {
    let size = (value as i32).abs().min(STICK_MAX);
    if size <= dead_zone {
        return 0;
    }
    (size - dead_zone) * FULL / (STICK_MAX - dead_zone) * (value as i32).signum()
}

fn trigger(value: u8) -> i32 {
    let value = value as i32;
    if value <= TRIGGER_THRESHOLD {
        return 0;
    }
    (value - TRIGGER_THRESHOLD) * FULL / (TRIGGER_MAX - TRIGGER_THRESHOLD)
}

fn button_bit(input: Input) -> Option<u16> {
    match input {
        Input::A => Some(BUTTON_A),
        Input::B => Some(BUTTON_B),
        Input::X => Some(BUTTON_X),
        Input::Y => Some(BUTTON_Y),
        Input::Lb => Some(BUTTON_LB),
        Input::Rb => Some(BUTTON_RB),
        Input::Back => Some(BUTTON_BACK),
        Input::LeftStickClick => Some(BUTTON_LEFT_THUMB),
        Input::RightStickClick => Some(BUTTON_RIGHT_THUMB),
        Input::Lt | Input::Rt => None,
    }
}

/// How far a pedal input is pressed, 0 to 127. Triggers are analog; buttons are all or nothing.
fn pedal(pad: &Pad, input: Input) -> i32 {
    match (input, button_bit(input)) {
        (Input::Lt, _) => trigger(pad.left_trigger),
        (Input::Rt, _) => trigger(pad.right_trigger),
        (_, Some(bit)) if pad.buttons & bit != 0 => FULL,
        _ => 0,
    }
}

fn held(pad: &Pad, input: Input) -> bool {
    pedal(pad, input) > 0
}

/// Only accelerate and brake are analog. Any other action is on or off, even on a trigger.
fn button(pad: &Pad, input: Input) -> i32 {
    held(pad, input) as i32 * FULL
}

fn stick(pad: &Pad, which: Stick) -> (i32, i32) {
    match which {
        Stick::Left => (axis(pad.thumb_lx, LEFT_DEAD_ZONE), axis(pad.thumb_ly, LEFT_DEAD_ZONE)),
        Stick::Right => (axis(pad.thumb_rx, RIGHT_DEAD_ZONE), axis(pad.thumb_ry, RIGHT_DEAD_ZONE)),
    }
}

fn dpad(pad: &Pad, positive: u16, negative: u16) -> i32 {
    (pad.buttons & positive != 0) as i32 * FULL - (pad.buttons & negative != 0) as i32 * FULL
}

fn signed(value: i32) -> i8 {
    value.clamp(-FULL, FULL) as i8
}

fn brake(pad: &Pad, layout: &Layout) -> i32 {
    pedal(pad, layout.brake).max(pedal(pad, layout.second_brake))
}

/// `before` is last frame's pad, for the stunt combo presses. `silent` is `Keys::silent`: a
/// button still held from a menu, such as A after "Resume", must not pull the handbrake or fire
/// nitro. Pedals stay analog, so a held trigger drives on after a resume.
pub fn drive(now: &Pad, before: &Pad, layout: &Layout, silent: u32) -> Drive {
    let button = |input: Input| if source(input) & silent != 0 { 0 } else { button(now, input) };
    // Like the keyboard keys O, K, T and SPACE, which the game also uses for combos.
    let combo_held = |pad: &Pad| {
        [held(pad, layout.accelerate), brake(pad, layout) > 0, held(pad, layout.camera_change), held(pad, layout.handbrake)]
    };
    let (held_now, held_before) = (combo_held(now), combo_held(before));
    Drive {
        steer: signed(stick(now, layout.steer).0 + dpad(now, DPAD_RIGHT, DPAD_LEFT)),
        throttle: signed(pedal(now, layout.accelerate) - 2 * brake(now, layout)),
        handbrake: button(layout.handbrake) as u8,
        flip: signed(stick(now, layout.flip).1 + dpad(now, DPAD_UP, DPAD_DOWN)),
        nitro: button(layout.nitro) > 0,
        combos: [0, 1, 2, 3].map(|n| held_now[n] && !held_before[n]),
    }
}

// Sources a key can come from: the 16 button bits, then these.
const LEFT_TRIGGER_SOURCE: u32 = 1 << 16;
const RIGHT_TRIGGER_SOURCE: u32 = 1 << 17;
const STICK_UP: u32 = 1 << 18;
const STICK_DOWN: u32 = 1 << 19;
const STICK_LEFT: u32 = 1 << 20;
const STICK_RIGHT: u32 = 1 << 21;

fn sources(pad: &Pad) -> u32 {
    let mut found = pad.buttons as u32;
    let pushed = |value: i16, sign: i32| (value as i32) * sign > MENU_PUSH;
    for (on, bit) in [
        (trigger(pad.left_trigger) > 0, LEFT_TRIGGER_SOURCE),
        (trigger(pad.right_trigger) > 0, RIGHT_TRIGGER_SOURCE),
        (pushed(pad.thumb_ly, 1), STICK_UP),
        (pushed(pad.thumb_ly, -1), STICK_DOWN),
        (pushed(pad.thumb_lx, -1), STICK_LEFT),
        (pushed(pad.thumb_lx, 1), STICK_RIGHT),
    ] {
        if on {
            found |= bit;
        }
    }
    found
}

fn source(input: Input) -> u32 {
    match input {
        Input::Lt => LEFT_TRIGGER_SOURCE,
        Input::Rt => RIGHT_TRIGGER_SOURCE,
        other => button_bit(other).map_or(0, u32::from),
    }
}

/// Turns pad buttons into held keys. A button already held when the context changes stays
/// silent until it is let go, so the button that paused a race cannot also pick a menu item.
#[derive(Debug, Default)]
pub struct Keys {
    context: Context,
    before: u32,
    silent: u32,
}

impl Keys {
    /// Pad sources held since the last context change, which stay silent until let go.
    pub fn silent(&self) -> u32 {
        self.silent
    }

    /// The DirectInput key codes to hold down this frame.
    pub fn keys(&mut self, now: &Pad, context: Context, layout: &Layout) -> Vec<u8> {
        let held = sources(now);
        if context != self.context {
            self.context = context;
            self.silent = held & self.before;
        }
        self.before = held;
        self.silent &= held;
        let active = held & !self.silent;
        let table: Vec<(u32, u8)> = match context {
            // The results screen shows over a race that still runs, so WRSE cannot tell it from
            // racing. A is Enter and the D-pad gives arrows here too: Enter does nothing in a race,
            // and the D-pad already steers and flips at full lock. The stick sends no arrows, so a
            // runner with arrows bound to steering keeps analog steering.
            Context::Race => vec![
                (BUTTON_A as u32, DIK_RETURN),
                (DPAD_UP as u32, DIK_UP),
                (DPAD_DOWN as u32, DIK_DOWN),
                (DPAD_LEFT as u32, DIK_LEFT),
                (DPAD_RIGHT as u32, DIK_RIGHT),
                (BUTTON_START as u32, DIK_ESCAPE),
                (source(layout.camera_change), DIK_T),
                (source(layout.camera_behind), DIK_Y),
            ],
            Context::Menu => vec![
                (BUTTON_A as u32 | BUTTON_START as u32, DIK_RETURN),
                (BUTTON_B as u32, DIK_ESCAPE),
                (DPAD_UP as u32 | STICK_UP, DIK_UP),
                (DPAD_DOWN as u32 | STICK_DOWN, DIK_DOWN),
                (DPAD_LEFT as u32 | STICK_LEFT, DIK_LEFT),
                (DPAD_RIGHT as u32 | STICK_RIGHT, DIK_RIGHT),
            ],
        };
        table.into_iter().filter(|(from, _)| active & from != 0).map(|(_, key)| key).collect()
    }
}

/// Adds the pad's controls to the game's own, so the keyboard keeps working beside the pad.
/// `game` starts at the steer byte and holds `CONTROL_BYTES` bytes.
pub fn add_drive(game: &mut [u8], drive: &Drive) {
    let add = |byte: u8, value: i8| signed(byte as i8 as i32 + value as i32) as u8;
    game[STEER] = add(game[STEER], drive.steer);
    game[THROTTLE] = add(game[THROTTLE], drive.throttle);
    game[FLIP] = add(game[FLIP], drive.flip);
    game[HANDBRAKE] = (game[HANDBRAKE] as i32 + drive.handbrake as i32).min(FULL) as u8;
    game[NITRO] |= drive.nitro as u8;
    for (byte, pressed) in game[COMBOS..CONTROL_BYTES].iter_mut().zip(drive.combos) {
        *byte |= pressed as u8;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pad() -> Pad {
        Pad::default()
    }

    fn race(now: &Pad) -> Drive {
        drive(now, &pad(), &Layout::default(), 0)
    }

    #[test]
    fn centre_stick_gives_no_steer() {
        assert_eq!(race(&pad()).steer, 0);
    }

    #[test]
    fn inside_the_dead_zone_gives_no_steer() {
        assert_eq!(race(&Pad { thumb_lx: 7000, ..pad() }).steer, 0);
    }

    #[test]
    fn full_left_is_full_lock() {
        assert_eq!(race(&Pad { thumb_lx: -32768, ..pad() }).steer, -127);
    }

    #[test]
    fn half_right_is_about_half() {
        let steer = race(&Pad { thumb_lx: 20000, ..pad() }).steer;
        assert!((60..=70).contains(&steer), "{steer}");
    }

    #[test]
    fn dpad_steers_full() {
        assert_eq!(race(&Pad { buttons: DPAD_LEFT, ..pad() }).steer, -127);
        assert_eq!(race(&Pad { buttons: DPAD_RIGHT, ..pad() }).steer, 127);
    }

    #[test]
    fn right_trigger_is_analog_throttle() {
        assert_eq!(race(&Pad { right_trigger: 255, ..pad() }).throttle, 127);
        let half = race(&Pad { right_trigger: 128, ..pad() }).throttle;
        assert!((50..=64).contains(&half), "{half}");
        assert_eq!(race(&Pad { right_trigger: 20, ..pad() }).throttle, 0);
    }

    #[test]
    fn brake_beats_throttle() {
        assert_eq!(race(&Pad { right_trigger: 255, left_trigger: 255, ..pad() }).throttle, -127);
    }

    #[test]
    fn flip_follows_left_stick_y() {
        assert_eq!(race(&Pad { thumb_ly: 32767, ..pad() }).flip, 127);
        assert_eq!(race(&Pad { buttons: DPAD_DOWN, ..pad() }).flip, -127);
    }

    #[test]
    fn steer_on_the_right_stick() {
        let layout = Layout { steer: Stick::Right, ..Layout::default() };
        assert_eq!(drive(&Pad { thumb_rx: 32767, ..pad() }, &pad(), &layout, 0).steer, 127);
        assert_eq!(drive(&Pad { thumb_lx: 32767, ..pad() }, &pad(), &layout, 0).steer, 0);
    }

    #[test]
    fn face_buttons_by_default() {
        let drive = race(&Pad { buttons: BUTTON_A, ..pad() });
        assert_eq!((drive.handbrake, drive.nitro), (127, false));
        assert!(race(&Pad { buttons: BUTTON_B, ..pad() }).nitro);
    }

    #[test]
    fn y_brakes_too() {
        assert_eq!(race(&Pad { buttons: BUTTON_Y, ..pad() }).throttle, -127);
        assert_eq!(race(&Pad { buttons: BUTTON_Y, right_trigger: 255, ..pad() }).throttle, -127);
    }

    #[test]
    fn either_brake_input_gives_the_brake_combo_press() {
        assert!(race(&Pad { buttons: BUTTON_Y, ..pad() }).combos[1]);
        let both_before = Pad { buttons: BUTTON_Y, left_trigger: 255, ..pad() };
        assert!(!drive(&Pad { buttons: BUTTON_Y, ..pad() }, &both_before, &Layout::default(), 0).combos[1]);
    }

    #[test]
    fn rebound_nitro_follows_its_button() {
        let layout = Layout { nitro: Input::Y, ..Layout::default() };
        assert!(drive(&Pad { buttons: BUTTON_Y, ..pad() }, &pad(), &layout, 0).nitro);
        assert!(!drive(&Pad { buttons: BUTTON_B, ..pad() }, &pad(), &layout, 0).nitro);
    }

    #[test]
    fn a_trigger_as_a_button() {
        let layout = Layout { handbrake: Input::Lt, ..Layout::default() };
        assert_eq!(drive(&Pad { left_trigger: 200, ..pad() }, &pad(), &layout, 0).handbrake, 127);
    }

    #[test]
    fn combo_edge_only_on_press() {
        let held = Pad { buttons: BUTTON_A, ..pad() };
        assert!(!drive(&held, &held, &Layout::default(), 0).combos[3]);
        assert!(drive(&held, &pad(), &Layout::default(), 0).combos[3]);
    }

    fn keys_in(keys: &mut Keys, now: &Pad, context: Context) -> Vec<u8> {
        keys.keys(now, context, &Layout::default())
    }

    #[test]
    fn start_pauses_in_a_race() {
        assert!(keys_in(&mut Keys::default(), &Pad { buttons: BUTTON_START, ..pad() }, Context::Race).contains(&DIK_ESCAPE));
    }

    #[test]
    fn cameras_in_a_race() {
        let mut keys = Keys::default();
        assert_eq!(keys_in(&mut keys, &Pad { buttons: BUTTON_X, ..pad() }, Context::Race), [DIK_T]);
        assert_eq!(keys_in(&mut keys, &Pad { buttons: BUTTON_RIGHT_THUMB, ..pad() }, Context::Race), [DIK_Y]);
    }

    #[test]
    fn b_is_back_in_menus() {
        assert_eq!(keys_in(&mut Keys::default(), &Pad { buttons: BUTTON_B, ..pad() }, Context::Menu), [DIK_ESCAPE]);
    }

    #[test]
    fn a_is_also_enter_in_a_race() {
        // The results screen shows over a race that still runs, and Enter does nothing in a race.
        assert_eq!(keys_in(&mut Keys::default(), &Pad { buttons: BUTTON_A, ..pad() }, Context::Race), [DIK_RETURN]);
    }

    #[test]
    fn dpad_moves_menus_in_a_race_too() {
        let mut keys = Keys::default();
        assert_eq!(keys_in(&mut keys, &Pad { buttons: DPAD_DOWN, ..pad() }, Context::Race), [DIK_DOWN]);
        assert_eq!(keys_in(&mut keys, &Pad { buttons: DPAD_LEFT, ..pad() }, Context::Race), [DIK_LEFT]);
    }

    #[test]
    fn the_stick_sends_no_arrows_in_a_race() {
        assert!(keys_in(&mut Keys::default(), &Pad { thumb_lx: -30000, thumb_ly: 30000, ..pad() }, Context::Race).is_empty());
    }

    #[test]
    fn b_is_not_a_key_in_a_race() {
        assert!(keys_in(&mut Keys::default(), &Pad { buttons: BUTTON_B, ..pad() }, Context::Race).is_empty());
    }

    #[test]
    fn a_and_start_select_in_menus() {
        let mut keys = Keys::default();
        assert_eq!(keys_in(&mut keys, &Pad { buttons: BUTTON_A, ..pad() }, Context::Menu), [DIK_RETURN]);
        keys_in(&mut keys, &pad(), Context::Menu);
        assert_eq!(keys_in(&mut keys, &Pad { buttons: BUTTON_START, ..pad() }, Context::Menu), [DIK_RETURN]);
    }

    #[test]
    fn stick_moves_menu_selection() {
        let mut keys = Keys::default();
        assert_eq!(keys_in(&mut keys, &Pad { thumb_lx: -20000, ..pad() }, Context::Menu), [DIK_LEFT]);
        assert_eq!(keys_in(&mut keys, &Pad { thumb_ly: 20000, ..pad() }, Context::Menu), [DIK_UP]);
        assert!(keys_in(&mut keys, &Pad { thumb_lx: 10000, ..pad() }, Context::Menu).is_empty());
        assert_eq!(keys_in(&mut keys, &Pad { buttons: DPAD_DOWN, ..pad() }, Context::Menu), [DIK_DOWN]);
    }

    #[test]
    fn a_held_button_does_not_fire_after_a_context_change() {
        let mut keys = Keys::default();
        let b = Pad { buttons: BUTTON_B, ..pad() };
        assert!(keys_in(&mut keys, &b, Context::Race).is_empty());
        assert!(keys_in(&mut keys, &b, Context::Menu).is_empty());
        assert!(keys_in(&mut keys, &pad(), Context::Menu).is_empty());
        assert_eq!(keys_in(&mut keys, &b, Context::Menu), [DIK_ESCAPE]);
    }

    #[test]
    fn start_held_into_the_pause_menu_does_not_select() {
        let mut keys = Keys::default();
        let start = Pad { buttons: BUTTON_START, ..pad() };
        assert_eq!(keys_in(&mut keys, &start, Context::Race), [DIK_ESCAPE]);
        assert!(keys_in(&mut keys, &start, Context::Menu).is_empty());
    }

    #[test]
    fn a_held_select_does_not_handbrake_after_resume() {
        let mut keys = Keys::default();
        let a = Pad { buttons: BUTTON_A, ..pad() };
        assert_eq!(keys_in(&mut keys, &a, Context::Menu), [DIK_RETURN]);
        keys_in(&mut keys, &a, Context::Race);
        let resumed = drive(&a, &a, &Layout::default(), keys.silent());
        assert_eq!(resumed.handbrake, 0);
        keys_in(&mut keys, &pad(), Context::Race);
        let drive_again = drive_with(&a, &keys);
        assert_eq!(drive_again.handbrake, 127);
    }

    #[test]
    fn a_held_pedal_still_drives_after_resume() {
        let mut keys = Keys::default();
        let held = Pad { buttons: BUTTON_A, right_trigger: 255, ..pad() };
        keys_in(&mut keys, &held, Context::Menu);
        keys_in(&mut keys, &held, Context::Race);
        assert_eq!(drive(&held, &held, &Layout::default(), keys.silent()).throttle, 127);
    }

    fn drive_with(now: &Pad, keys: &Keys) -> Drive {
        drive(now, &pad(), &Layout::default(), keys.silent())
    }

    fn controls() -> Vec<u8> {
        vec![0; CONTROL_BYTES]
    }

    #[test]
    fn add_drive_clamps() {
        let mut game = controls();
        game[STEER] = (-100i8) as u8;
        add_drive(&mut game, &Drive { steer: -100, ..Drive::default() });
        assert_eq!(game[STEER] as i8, -127);
    }

    #[test]
    fn add_drive_with_no_pad_keeps_the_keyboard() {
        let mut game = controls();
        game[THROTTLE] = 127;
        game[NITRO] = 1;
        game[COMBOS] = 1;
        let before = game.clone();
        add_drive(&mut game, &Drive::default());
        assert_eq!(game, before);
    }

    #[test]
    fn add_drive_writes_every_control() {
        let mut game = controls();
        let pad_drive = Drive { steer: 10, throttle: -20, handbrake: 127, flip: 30, nitro: true, combos: [false, true, false, true] };
        add_drive(&mut game, &pad_drive);
        assert_eq!((game[STEER] as i8, game[THROTTLE] as i8, game[HANDBRAKE], game[FLIP] as i8, game[NITRO]), (10, -20, 127, 30, 1));
        assert_eq!(&game[COMBOS..COMBOS + 4], &[0, 1, 0, 1]);
    }

    #[test]
    fn layout_reads_the_mod_manager_names() {
        let layout: Layout = serde_json::from_str(
            r#"{"accelerate": "rt", "brake": "lt", "second_brake": "rb", "steer": "right_stick", "flip": "left_stick", "handbrake": "left_stick_click",
                "nitro": "lb", "camera_change": "x", "camera_behind": "right_stick_click"}"#,
        )
        .unwrap();
        assert_eq!((layout.steer, layout.handbrake, layout.nitro, layout.second_brake), (Stick::Right, Input::LeftStickClick, Input::Lb, Input::Rb));
    }

    #[test]
    fn layout_refuses_an_unknown_action() {
        assert!(serde_json::from_str::<Layout>(r#"{"jump": "a"}"#).is_err());
    }
}
