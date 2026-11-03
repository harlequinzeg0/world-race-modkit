//! World Race Script Extender: a `dinput8.dll` proxy for the stock game.
//! With no `WRSE_SESSION`, it only forwards input calls, so a leftover DLL leaves the game stock.
mod cars;
mod files;
pub mod fixes;
pub mod hook;
mod log;
pub mod saves;
pub mod session;
pub mod shuffle;
pub mod teams;
pub mod text;
pub mod vfs;

use session::Session;
use std::ffi::{c_void, CString, OsStr};
use std::sync::OnceLock;

extern "system" {
    fn GetSystemDirectoryA(buffer: *mut u8, size: u32) -> u32;
    fn LoadLibraryA(name: *const i8) -> *mut c_void;
    fn GetProcAddress(module: *mut c_void, name: *const i8) -> *mut c_void;
    fn ExitProcess(code: u32) -> !;
}

#[link(name = "user32")]
extern "system" {
    fn MessageBoxA(window: *mut c_void, text: *const i8, title: *const i8, flags: u32) -> i32;
}

type CreateFn = unsafe extern "system" fn(*mut c_void, u32, *const c_void, *mut *mut c_void, *mut c_void) -> i32;

const SESSION_VARIABLE: &str = "WRSE_SESSION";
const DLL_PROCESS_ATTACH: u32 = 1;
const MB_ICONERROR: u32 = 0x10;
const E_FAIL: i32 = 0x8000_4005_u32 as i32;
const MAX_PATH: usize = 260;

static SESSION: OnceLock<Session> = OnceLock::new();

/// The session this game run uses. Hooks exist only once it is set.
pub(crate) fn session() -> &'static Session {
    SESSION.get().expect("hooks run only after the session is set")
}

fn load_session(path: &OsStr) -> Result<Session, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("cannot read the session file: {e}"))?;
    session::parse(&text)
}

/// The game must not run half modded, so a bad session ends it.
fn fatal(message: &str) -> ! {
    log::line(message);
    let text = CString::new(message.replace('\0', " ")).unwrap_or_default();
    unsafe {
        MessageBoxA(std::ptr::null_mut(), text.as_ptr(), b"World Race Script Extender\0".as_ptr() as *const i8, MB_ICONERROR);
        ExitProcess(1)
    }
}

fn install(session: &'static Session) -> Result<(), String> {
    let mut hooks = files::hooks();
    hooks.extend(saves::hooks(&session.save_dir)?);
    hooks.extend(text::hooks(session));
    let mut patches = fixes::patches();
    if !session.teams.is_empty() {
        let (car_hooks, car_patches) = cars::parts(session)?;
        hooks.extend(car_hooks);
        patches.extend(car_patches);
    }
    unsafe { hook::install_all(&hooks, &patches) }
}

fn start() {
    let Some(path) = std::env::var_os(SESSION_VARIABLE) else {
        return;
    };
    let session = match load_session(&path) {
        Ok(session) => session,
        Err(message) => {
            log::init(&format!("{}.log", path.to_string_lossy()));
            fatal(&message);
        }
    };
    let session = SESSION.get_or_init(|| session);
    log::init(&session.log_path);
    log::line(&format!("session loaded, {} roots", session.roots.len()));
    if let Err(message) = install(session) {
        fatal(&message);
    }
    log::line("hooks installed");
}

#[no_mangle]
pub extern "system" fn DllMain(_module: *mut c_void, reason: u32, _reserved: *mut c_void) -> i32 {
    if reason == DLL_PROCESS_ATTACH {
        start();
    }
    1
}

#[no_mangle]
pub unsafe extern "system" fn DirectInput8Create(
    instance: *mut c_void,
    version: u32,
    iid: *const c_void,
    out: *mut *mut c_void,
    outer: *mut c_void,
) -> i32 {
    let mut directory = [0u8; MAX_PATH];
    let length = GetSystemDirectoryA(directory.as_mut_ptr(), MAX_PATH as u32) as usize;
    let path = format!("{}\\dinput8.dll\0", String::from_utf8_lossy(&directory[..length]));
    let real = LoadLibraryA(path.as_ptr() as *const i8);
    if real.is_null() {
        return E_FAIL;
    }
    let create = GetProcAddress(real, b"DirectInput8Create\0".as_ptr() as *const i8);
    if create.is_null() {
        return E_FAIL;
    }
    let create: CreateFn = std::mem::transmute(create);
    create(instance, version, iid, out, outer)
}
