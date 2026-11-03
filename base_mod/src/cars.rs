//! Added cars and teams inside the game's own objects. The rules live in `teams` and `shuffle`.
use crate::hook::{write_code, Hook, Patch};
use crate::session::{Session, STOCK_CARS, STOCK_TEAMS};
use crate::shuffle::{self, PickCar};
use crate::{fatal, log, session, teams};
use std::collections::HashMap;
use std::ffi::{c_void, CStr, CString};
use std::sync::atomic::{AtomicU32, AtomicUsize, Ordering};
use std::sync::{Mutex, OnceLock};

const LOAD_CARS: usize = 0x403230;
const DESTROY_CARS: usize = 0x403390;
const FIND_BOX: usize = 0x4F2020;
const REGISTER_CALL: usize = 0x402CC3;
const REGISTER_SAVEABLE: usize = 0x4C53E0;
const SAVEABLE_VTABLE: u32 = 0x59CFE0;
const SELECTOR_EVENT: usize = 0x420D20;
const WINDOW_SHIFT: usize = 0x42DE70;
const LAYOUT_ICONS: usize = 0x42DD70;
const TEAM_LOGOS: usize = 0x42E3A0;
const SET_TEXTURE: usize = 0x43CB80;
const SET_BOX: usize = 0x43CBE0;
const QUICK_RACE_SETUP: usize = 0x48FB00;
const LEAGUE_SETUP: usize = 0x499E40;
const LOAD_CAR_MODELS: usize = 0x46FA30;
const WHEEL_FOLDER: usize = 0x470380;
const STOCK_WHEEL_FOLDER: usize = 0x5EFEFC;
const LEFT_WRAP: usize = 0x420DF9;
const RIGHT_WRAP: usize = 0x420E8B;

// Car object fields.
const CAR_TEAM: usize = 0xC;
const CAR_AI: usize = 0x60;

const CAR_NAME: usize = 0x10;

// Car list fields.
const LIST_CAPACITY: usize = 4;
const LIST_COUNT: usize = 8;
const LIST_ARRAY: usize = 0xC;

// Selector fields.
const WIDGET_COUNT: usize = 0x104;
const WIDGET_ARRAY: usize = 0x108;
const RING_COUNT: usize = 0x118;
const RING_FIRST: usize = 0x130;
const RING_LAST: usize = 0x134;
const WINDOW_START: usize = 0x1AC;
const MAX_ICONS: usize = 0x1B0;

// A widget's rectangle, through its vtable. Off-screen icons use x = 10.
const VTABLE_GET_RECT: usize = 0x34 / 4;
const VTABLE_SET_RECT: usize = 0x2C / 4;
const OFF_SCREEN_X: f32 = 10.0;

type Unary = unsafe extern "thiscall" fn(*mut u8);
type Named = unsafe extern "thiscall" fn(*mut c_void, *const i8) -> *mut c_void;
type LoadCarModels = unsafe extern "thiscall" fn(*mut u8, *const u8, i32, i32) -> u8;

static LOAD_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static DESTROY_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static BOX_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static EVENT_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static SHIFT_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static LAYOUT_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static LOGOS_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static QUICK_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static LEAGUE_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static CAR_MODELS_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static WHEEL_FOLDER_NOW: AtomicUsize = AtomicUsize::new(STOCK_WHEEL_FOLDER);

static CARS_MADE: AtomicU32 = AtomicU32::new(0);
static SHAPE: OnceLock<Shape> = OnceLock::new();
static LOADED: Mutex<Option<Loaded>> = Mutex::new(None);

/// What the session fixes for the whole run.
struct Shape {
    teams: usize,
    width: usize,
    box_fallbacks: HashMap<String, CString>,
    logos: Vec<(CString, CString)>,
    rim_folders: HashMap<String, CString>,
}

struct Car {
    object: usize,
    team: usize,
    stock_number: u32,
    ai: bool,
}

/// The rebuilt list. The grid must live as long as the game's list points at it.
struct Loaded {
    grid: Vec<u32>,
    real_list: (u32, u32, u32),
    cars: Vec<Car>,
}

fn shape() -> &'static Shape {
    SHAPE.get().expect("hooks run only after the shape is set")
}

unsafe fn read(base: *const u8, offset: usize) -> u32 {
    std::ptr::read_unaligned(base.add(offset) as *const u32)
}

unsafe fn write(base: *mut u8, offset: usize, value: u32) {
    std::ptr::write_unaligned(base.add(offset) as *mut u32, value);
}

unsafe fn restore_list(this: *mut u8) {
    if let Some(loaded) = LOADED.lock().unwrap().take() {
        write(this, LIST_CAPACITY, loaded.real_list.0);
        write(this, LIST_COUNT, loaded.real_list.1);
        write(this, LIST_ARRAY, loaded.real_list.2);
    }
}

unsafe fn rebuild_list(this: *mut u8) {
    let current = session();
    let count = read(this, LIST_COUNT);
    let expected = STOCK_CARS + current.cars.len() as u32;
    if count != expected {
        fatal(&format!("car_info.xml has {count} cars, and the session expects {expected}"));
    }
    let array = read(this, LIST_ARRAY) as *const u32;
    let mut cars = Vec::with_capacity(count as usize);
    for (team, row) in current.teams.iter().enumerate() {
        for slot in &row.slots {
            let object = *array.add(*slot as usize) as *mut u8;
            // Added cars take a stock number, so stock code that uses one stays in bounds.
            if *slot >= STOCK_CARS {
                write(object, CAR_TEAM, row.base_team as u32);
            }
            let stock_number = read(object, CAR_TEAM);
            cars.push(Car { object: object as usize, team, stock_number, ai: *object.add(CAR_AI) != 0 });
        }
    }
    let grid: Vec<u32> = teams::grid_indices(current, shape().width).iter().map(|index| *array.add(*index as usize)).collect();
    let real_list = (read(this, LIST_CAPACITY), count, read(this, LIST_ARRAY));
    write(this, LIST_ARRAY, grid.as_ptr() as u32);
    write(this, LIST_COUNT, grid.len() as u32);
    write(this, LIST_CAPACITY, grid.len() as u32);
    log::line(&format!("car grid built, {} teams, width {}", shape().teams, shape().width));
    *LOADED.lock().unwrap() = Some(Loaded { grid, real_list, cars });
}

unsafe extern "thiscall" fn load_detour(this: *mut u8, path: *const i8) -> *mut u8 {
    restore_list(this);
    CARS_MADE.store(0, Ordering::SeqCst);
    let original: unsafe extern "thiscall" fn(*mut u8, *const i8) -> *mut u8 = std::mem::transmute(LOAD_ORIGINAL.load(Ordering::SeqCst));
    let result = original(this, path);
    rebuild_list(this);
    result
}

unsafe extern "thiscall" fn destroy_detour(this: *mut u8) {
    restore_list(this);
    let original: Unary = std::mem::transmute(DESTROY_ORIGINAL.load(Ordering::SeqCst));
    original(this);
}

/// Stock cars register as saveable objects. Added cars must not, or the save format shifts.
unsafe extern "thiscall" fn register_detour(this: *mut u32) -> *mut u32 {
    if CARS_MADE.fetch_add(1, Ordering::SeqCst) < STOCK_CARS {
        let register: unsafe extern "thiscall" fn(*mut u32) -> *mut u32 = std::mem::transmute(REGISTER_SAVEABLE);
        return register(this);
    }
    *this = SAVEABLE_VTABLE;
    *this.add(1) = 0xFFFF_FFFF;
    this
}

/// A null box crashes the caller, so an added name retries with its stock base.
unsafe extern "thiscall" fn box_detour(this: *mut c_void, name: *const i8) -> *mut c_void {
    let original: Named = std::mem::transmute(BOX_ORIGINAL.load(Ordering::SeqCst));
    let found = original(this, name);
    if !found.is_null() {
        return found;
    }
    let text = CStr::from_ptr(name).to_string_lossy();
    match shape().box_fallbacks.get(text.as_ref()) {
        Some(fallback) => original(this, fallback.as_ptr()),
        None => {
            log::line(&format!("missing box: {text}"));
            found
        }
    }
}

unsafe fn is_car_selector(this: *const u8) -> bool {
    read(this, MAX_ICONS) as usize == shape().teams * shape().width
}

unsafe fn sync_row(this: *mut u8) {
    if is_car_selector(this) {
        let team = (read(this, WINDOW_START) as usize / shape().width).min(shape().teams - 1);
        write(this, RING_COUNT, teams::team_slots(session(), team).len() as u32);
    }
}

unsafe extern "thiscall" fn shift_detour(this: *mut u8, delta: i32) {
    let original: unsafe extern "thiscall" fn(*mut u8, i32) = std::mem::transmute(SHIFT_ORIGINAL.load(Ordering::SeqCst));
    original(this, delta);
    sync_row(this);
}

/// The ring moves only the icons it counts, so spare icons must leave the screen.
unsafe fn park_spare_icons(this: *mut u8) {
    let shown = read(this, RING_COUNT) as usize;
    let total = read(this, WIDGET_COUNT) as usize;
    let widgets = read(this, WIDGET_ARRAY) as *const u32;
    for i in shown..total {
        let holder = *widgets.add(i) as *const u32;
        let object = *holder as *mut c_void;
        let vtable = *(object as *const *const usize);
        let get: unsafe extern "thiscall" fn(*mut c_void) -> *const f32 = std::mem::transmute(*vtable.add(VTABLE_GET_RECT));
        let set: unsafe extern "thiscall" fn(*mut c_void, *const f32) = std::mem::transmute(*vtable.add(VTABLE_SET_RECT));
        let mut rect = [0f32; 4];
        std::ptr::copy_nonoverlapping(get(object), rect.as_mut_ptr(), rect.len());
        rect[0] = OFF_SCREEN_X;
        set(object, rect.as_ptr());
    }
}

unsafe extern "thiscall" fn layout_detour(this: *mut u8, slot: i32) {
    sync_row(this);
    let original: unsafe extern "thiscall" fn(*mut u8, i32) = std::mem::transmute(LAYOUT_ORIGINAL.load(Ordering::SeqCst));
    original(this, slot);
    if is_car_selector(this) {
        park_spare_icons(this);
        // On an even ring stock leaves the last end one short, so a left scroll moves the wrong icon.
        let (first, last) = teams::ring_ends(slot, read(this, RING_COUNT) as i32);
        write(this, RING_FIRST, first as u32);
        write(this, RING_LAST, last as u32);
    }
}

unsafe extern "thiscall" fn event_detour(this: *mut u8, event: *const u8) -> u32 {
    let player = if read(this, 0x120) == 1 { 0 } else { *event.add(4) as usize };
    let state = read(this, 0x100 + player * 4) as *const u8;
    let team = (read(state, 4) as usize).min(shape().teams - 1);
    let last = teams::last_slot(session(), team);
    write_code(LEFT_WRAP, &(last as u32).to_le_bytes());
    write_code(RIGHT_WRAP, &[last as u8]);
    let original: unsafe extern "thiscall" fn(*mut u8, *const u8) -> u32 = std::mem::transmute(EVENT_ORIGINAL.load(Ordering::SeqCst));
    original(this, event)
}

/// Stock code gives every slot a texture, and a second texture on a slot would leak the first.
/// The leaked entry crashes the texture dump at the next state change, so added slots are hidden
/// from stock code here and get their only texture below.
unsafe extern "thiscall" fn logos_detour(this: *mut u8) {
    let count = read(this, RING_COUNT);
    let added = count as usize == shape().teams && shape().teams > STOCK_TEAMS;
    if added {
        write(this, RING_COUNT, STOCK_TEAMS as u32);
    }
    let original: Unary = std::mem::transmute(LOGOS_ORIGINAL.load(Ordering::SeqCst));
    original(this);
    if !added {
        return;
    }
    write(this, RING_COUNT, count);
    let widgets = read(this, WIDGET_ARRAY) as *const u32;
    let set_texture: Named = std::mem::transmute(SET_TEXTURE);
    let set_box: Named = std::mem::transmute(SET_BOX);
    for (offset, (texture, box_name)) in shape().logos.iter().enumerate() {
        let holder = *widgets.add(STOCK_TEAMS + offset) as *const u32;
        let object = *holder as *mut c_void;
        set_texture(object, texture.as_ptr());
        set_box(object, box_name.as_ptr());
    }
}

fn random_seed() -> u32 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(1, |time| time.subsec_nanos())
}

unsafe fn renumber_teams(players: &[u32]) {
    let guard = LOADED.lock().unwrap();
    let Some(loaded) = guard.as_ref() else {
        return;
    };
    let drawable = &loaded.grid[..loaded.grid.len() - 1];
    let candidates: Vec<PickCar> = loaded
        .cars
        .iter()
        .map(|car| {
            let object = car.object as u32;
            PickCar { team: car.team, ai: car.ai, player: players.contains(&object), drawable: drawable.contains(&object) }
        })
        .collect();
    let Some(picked) = shuffle::pick(&shuffle::free_teams(shape().teams, &candidates), random_seed()) else {
        log::line("too few teams with a free AI car, keeping stock numbers");
        return;
    };
    log::line(&format!("opponent teams {picked:?}"));
    for car in &loaded.cars {
        write(car.object as *mut u8, CAR_TEAM, shuffle::team_number(&picked, car.team));
    }
}

unsafe fn restore_numbers() {
    if let Some(loaded) = LOADED.lock().unwrap().as_ref() {
        for car in &loaded.cars {
            write(car.object as *mut u8, CAR_TEAM, car.stock_number);
        }
    }
}

/// Racers are stored as (car, extra) pairs.
unsafe fn racers(pairs: *const u32, count: usize) -> Vec<u32> {
    (0..count).map(|i| *pairs.add(i * 2)).collect()
}

unsafe extern "thiscall" fn quick_detour(this: *mut u8) {
    let list = read(read(this, 0x30) as *const u8, 8) as *const u8;
    renumber_teams(&racers(read(list, 8) as *const u32, read(list, 4) as usize));
    let original: Unary = std::mem::transmute(QUICK_ORIGINAL.load(Ordering::SeqCst));
    original(this);
    restore_numbers();
}

/// The game never selects a car's wheel texture, because the field that check reads is never set,
/// and it draws all wheels in one batch, so one shared texture cannot differ between cars. A wheel
/// model with its own material can, so a car with a rim colour loads its own copy.
unsafe extern "thiscall" fn car_models_detour(this: *mut u8, car: *const u8, level: i32, count: i32) -> u8 {
    let name = CStr::from_ptr(read(car, CAR_NAME) as *const i8).to_string_lossy();
    if let Some(folder) = shape().rim_folders.get(name.as_ref()) {
        WHEEL_FOLDER_NOW.store(folder.as_ptr() as usize, Ordering::SeqCst);
        log::line(&format!("{name} loads wheels from {}", folder.to_string_lossy()));
    }
    let original: LoadCarModels = std::mem::transmute(CAR_MODELS_ORIGINAL.load(Ordering::SeqCst));
    let result = original(this, car, level, count);
    WHEEL_FOLDER_NOW.store(STOCK_WHEEL_FOLDER, Ordering::SeqCst);
    result
}

unsafe extern "C" fn wheel_folder_detour() -> usize {
    WHEEL_FOLDER_NOW.load(Ordering::SeqCst)
}

unsafe extern "thiscall" fn league_detour(this: *mut u8) {
    renumber_teams(&racers(read(this, 0x20) as *const u32, read(this, 0x1C) as usize));
    let original: Unary = std::mem::transmute(LEAGUE_ORIGINAL.load(Ordering::SeqCst));
    original(this);
    restore_numbers();
}

fn c_string(text: &str) -> Result<CString, String> {
    CString::new(text).map_err(|_| format!("session text holds a null: {text}"))
}

fn make_shape(session: &Session) -> Result<Shape, String> {
    let mut box_fallbacks = HashMap::new();
    for car in &session.cars {
        box_fallbacks.insert(car.name.clone(), c_string(&car.based_on)?);
    }
    let mut logos = Vec::new();
    for team in session.teams.iter().skip(STOCK_TEAMS) {
        box_fallbacks.insert(team.id.clone(), c_string(&session.teams[team.base_team].id)?);
        if let Some(logo) = &team.logo {
            logos.push((c_string(&logo.texture)?, c_string(&logo.box_name)?));
        }
    }
    let mut rim_folders = HashMap::new();
    for (car, folder) in teams::rim_folders(session) {
        rim_folders.insert(car, c_string(&folder)?);
    }
    Ok(Shape { teams: session.teams.len(), width: teams::width(session), box_fallbacks, logos, rim_folders })
}

fn value(address: usize, old: u32, new: u32) -> Patch {
    Patch { address, old: old.to_le_bytes().to_vec(), new: new.to_le_bytes().to_vec() }
}

fn byte(address: usize, old: u8, new: u8) -> Patch {
    Patch { address, old: vec![old], new: vec![new] }
}

/// `lea r, [s * 8]; sub r, s` becomes `imul r, s, width`.
fn times_width(address: usize, old: [u8; 9], target: u8, source: u8, width: u8) -> Patch {
    let mut new = vec![0x6B, 0xC0 | (target << 3) | source, width];
    new.resize(old.len(), 0x90);
    Patch { address, old: old.to_vec(), new }
}

fn relative_call(target: usize) -> u32 {
    (target as i32 - (REGISTER_CALL as i32 + 5)) as u32
}

fn patches(session: &Session, width: usize, team_count: usize) -> Vec<Patch> {
    let (w, last_team) = (width as u8, (team_count - 1) as u8);
    let reps = STOCK_CARS + session.cars.len() as u32;
    vec![
        // Car list capacity, far above any grid the session allows.
        value(0x403241, 0x8C, 0x400),
        value(0x40324F, 0x23, 0x100),
        // Car select objects, one per car_rep.
        value(0x41E19A, 0x8C, reps * 4),
        value(0x41E1E0, 0x23, reps),
        value(0x41E261, 0x23, reps),
        // Selector widget array.
        byte(0x42CD28, 7, w),
        byte(0x42CD45, 0x1C, w * 4),
        value(0x42CD4C, 7, width as u32),
        // Team steps and the window start, which is team 2 in stock.
        byte(0x420E37, 7, w),
        byte(0x420DB3, 0xF9, 0u8.wrapping_sub(w)),
        value(0x42D444, 14, 2 * width as u32),
        // Team wrap.
        value(0x420DA3, 4, last_team as u32),
        byte(0x420E21, 4, last_team),
        // Slot wrap. The event hook sets these per team, so install only checks them.
        value(LEFT_WRAP, 6, 6),
        byte(RIGHT_WRAP, 6, 6),
        times_width(0x4209ED, [0x8D, 0x14, 0xCD, 0, 0, 0, 0, 0x2B, 0xD1], 2, 1, w),
        times_width(0x420EA4, [0x8D, 0x0C, 0xC5, 0, 0, 0, 0, 0x2B, 0xC8], 1, 0, w),
        times_width(0x421025, [0x8D, 0x04, 0xCD, 0, 0, 0, 0, 0x2B, 0xC1], 0, 1, w),
        times_width(0x42DC90, [0x8D, 0x1C, 0xC5, 0, 0, 0, 0, 0x2B, 0xD8], 3, 0, w),
        value(REGISTER_CALL + 1, relative_call(REGISTER_SAVEABLE), relative_call(register_detour as usize)),
    ]
}

fn hooks() -> Vec<Hook> {
    let site = |address, expected, detour, original| Hook { address, expected, detour, original: Some(original) };
    vec![
        site(LOAD_CARS, &[0x81, 0xEC, 0x4C, 0x02, 0x00, 0x00], load_detour as usize, &LOAD_ORIGINAL),
        site(DESTROY_CARS, &[0x53, 0x56, 0x57, 0x8B, 0xF9], destroy_detour as usize, &DESTROY_ORIGINAL),
        site(FIND_BOX, &[0x53, 0x55, 0x56, 0x8B, 0xF1, 0x57], box_detour as usize, &BOX_ORIGINAL),
        site(SELECTOR_EVENT, &[0x53, 0x55, 0x56, 0x57, 0x8B, 0x7C, 0x24, 0x14], event_detour as usize, &EVENT_ORIGINAL),
        site(WINDOW_SHIFT, &[0x8B, 0x44, 0x24, 0x04, 0x8B, 0x91, 0xAC, 0x01, 0x00, 0x00], shift_detour as usize, &SHIFT_ORIGINAL),
        site(LAYOUT_ICONS, &[0x83, 0xEC, 0x1C, 0x53, 0x55], layout_detour as usize, &LAYOUT_ORIGINAL),
        site(TEAM_LOGOS, &[0x56, 0x8B, 0xF1, 0x57, 0x33, 0xFF], logos_detour as usize, &LOGOS_ORIGINAL),
        site(QUICK_RACE_SETUP, &[0x83, 0xEC, 0x2C, 0x53, 0x55], quick_detour as usize, &QUICK_ORIGINAL),
        site(LOAD_CAR_MODELS, &[0x81, 0xEC, 0x50, 0x02, 0x00, 0x00], car_models_detour as usize, &CAR_MODELS_ORIGINAL),
        Hook { address: WHEEL_FOLDER, expected: &[0xB8, 0xFC, 0xFE, 0x5E, 0x00], detour: wheel_folder_detour as usize, original: None },
        site(LEAGUE_SETUP, &[0x81, 0xEC, 0x5C, 0x01, 0x00, 0x00], league_detour as usize, &LEAGUE_ORIGINAL),
    ]
}

/// The hooks and patches for a session that adds cars or teams.
pub fn parts(session: &Session) -> Result<(Vec<Hook>, Vec<Patch>), String> {
    let made = make_shape(session)?;
    let shape = SHAPE.get_or_init(|| made);
    Ok((hooks(), patches(session, shape.width, shape.teams)))
}
