//! Rim colours. The game loads a rim texture for each stock team but never picks one, and every
//! wheel model uses one shared texture. So a car gets another colour only from wheel models with
//! their own material, which the tool generates: while such a car's models load, the wheel folder
//! points at its copy.
//!
//! The model manager (`0x4E3DA0`) caches models by file name alone, so every car would share the
//! first `generic_wheel_med.rom` and `generic_wheel_low.rom` it loaded, whatever their folder. Rim
//! wheels therefore keep their `rim_<n>` folder in the cache key.
use crate::hook::{Hook, Patch};
use crate::log;
use crate::session::Session;
use std::collections::HashMap;
use std::ffi::{CStr, CString};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::OnceLock;

const LOAD_CAR_MODELS: usize = 0x46FA30;
const LOAD_CAR_MODELS_BYTES: &[u8] = &[0x81, 0xEC, 0x50, 0x02, 0x00, 0x00];
const WHEEL_FOLDER: usize = 0x470380;
const WHEEL_FOLDER_BYTES: &[u8] = &[0xB8, 0xFC, 0xFE, 0x5E, 0x00];
const STOCK_WHEEL_FOLDER: usize = 0x5EFEFC;
/// The car object's own name. It stays when the Smashmouth cheat loads another model.
const CAR_NAME: usize = 0x10;
/// The model manager's call that makes a cache key from a path, and the stock key function.
const MODEL_KEY_CALL: usize = 0x4E3DC1;
const MODEL_KEY: usize = 0x504750;
const CALL: u8 = 0xE8;
const CALL_SIZE: usize = 5;
const RIM_FOLDER_PREFIX: &str = "rim_";

type LoadCarModels = unsafe extern "thiscall" fn(*mut u8, *const u8, i32, i32) -> u8;
/// cdecl: path, key buffer, buffer size. Returns 0 when the key does not fit.
type ModelKey = unsafe extern "C" fn(*const i8, *mut i8, i32) -> i32;

static CAR_MODELS_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static WHEEL_FOLDER_NOW: AtomicUsize = AtomicUsize::new(STOCK_WHEEL_FOLDER);
static FOLDERS: OnceLock<HashMap<String, CString>> = OnceLock::new();

/// Each car's wheel folder. Rim 0 is the stock wheel, so it needs none.
fn folders_of(rims: &HashMap<String, u32>) -> HashMap<String, String> {
    rims.iter().filter(|(_, rim)| **rim > 0).map(|(car, rim)| (car.clone(), format!("cars/generic_models/cache/rim_{rim}"))).collect()
}

/// The cache key for a model in a rim folder, so it does not share the stock wheel's key.
fn rim_model_key(path: &str) -> Option<String> {
    let mut parts = path.rsplit(['/', '\\']);
    let file = parts.next()?;
    let folder = parts.next()?;
    let is_rim = folder.get(..RIM_FOLDER_PREFIX.len()).is_some_and(|start| start.eq_ignore_ascii_case(RIM_FOLDER_PREFIX));
    is_rim.then(|| format!("{folder}/{file}"))
}

fn call_to(target: usize) -> Vec<u8> {
    let offset = (target as i32).wrapping_sub((MODEL_KEY_CALL + CALL_SIZE) as i32);
    [&[CALL][..], &offset.to_le_bytes()].concat()
}

pub fn patches() -> Vec<Patch> {
    vec![Patch { address: MODEL_KEY_CALL, old: call_to(MODEL_KEY), new: call_to(model_key_detour as usize) }]
}

fn sites() -> Vec<Hook> {
    vec![
        Hook { address: LOAD_CAR_MODELS, expected: LOAD_CAR_MODELS_BYTES, detour: car_models_detour as usize, original: Some(&CAR_MODELS_ORIGINAL) },
        Hook { address: WHEEL_FOLDER, expected: WHEEL_FOLDER_BYTES, detour: wheel_folder_detour as usize, original: None },
    ]
}

pub fn hooks(session: &Session) -> Result<Vec<Hook>, String> {
    let mut folders = HashMap::new();
    for (car, folder) in folders_of(&session.rims) {
        let folder = CString::new(folder).map_err(|_| format!("car {car} has a wheel folder with a null in it"))?;
        folders.insert(car, folder);
    }
    FOLDERS.get_or_init(|| folders);
    Ok(sites())
}

unsafe extern "thiscall" fn car_models_detour(this: *mut u8, car: *const u8, level: i32, count: i32) -> u8 {
    let name = CStr::from_ptr(*(car.add(CAR_NAME) as *const *const i8)).to_string_lossy();
    if let Some(folder) = FOLDERS.get().and_then(|folders| folders.get(name.as_ref())) {
        WHEEL_FOLDER_NOW.store(folder.as_ptr() as usize, Ordering::SeqCst);
        log::line(&format!("{name} loads wheels from {}", folder.to_string_lossy()));
    }
    let original: LoadCarModels = std::mem::transmute(CAR_MODELS_ORIGINAL.load(Ordering::SeqCst));
    let result = original(this, car, level, count);
    WHEEL_FOLDER_NOW.store(STOCK_WHEEL_FOLDER, Ordering::SeqCst);
    result
}

unsafe extern "C" fn model_key_detour(path: *const i8, key: *mut i8, size: i32) -> i32 {
    let stock: ModelKey = std::mem::transmute(MODEL_KEY);
    let result = stock(path, key, size);
    if result == 0 || path.is_null() {
        return result;
    }
    if let Some(own) = rim_model_key(&CStr::from_ptr(path).to_string_lossy()) {
        // The stock key stays when the longer one does not fit, as the stock function would refuse.
        if own.len() < size as usize {
            std::ptr::copy_nonoverlapping(own.as_ptr(), key as *mut u8, own.len());
            *key.add(own.len()) = 0;
        }
    }
    result
}

unsafe extern "C" fn wheel_folder_detour() -> usize {
    WHEEL_FOLDER_NOW.load(Ordering::SeqCst)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    #[test]
    fn a_rim_colour_has_its_own_wheel_folder() {
        let rims = HashMap::from([("ballistic".to_string(), 3)]);
        let folders = HashMap::from([("ballistic".to_string(), "cars/generic_models/cache/rim_3".to_string())]);
        assert_eq!(folders_of(&rims), folders);
    }

    #[test]
    fn a_rim_wheel_keeps_its_folder_in_the_model_key() {
        assert_eq!(rim_model_key("cars/generic_models/cache/rim_3/generic_wheel_med.rom").as_deref(), Some("rim_3/generic_wheel_med.rom"));
        assert_eq!(rim_model_key(r"cars\generic_models\cache\RIM_4\generic_wheel_low.rom").as_deref(), Some("RIM_4/generic_wheel_low.rom"));
    }

    #[test]
    fn other_models_keep_the_stock_key() {
        assert_eq!(rim_model_key("cars/generic_models/cache/generic_wheel_med.rom"), None);
        assert_eq!(rim_model_key("generic_wheel_med.rom"), None);
        assert_eq!(rim_model_key("cars/ballistic/cache/ballistic_med.rom"), None);
    }

    #[test]
    fn the_model_key_call_is_checked() {
        let patches = patches();
        assert_eq!((patches[0].address, patches[0].old.as_slice()), (0x4E3DC1, &[0xE8, 0x8A, 0x09, 0x02, 0x00][..]));
        assert_eq!(patches[0].new[0], 0xE8);
    }

    #[test]
    fn hooks_check_their_bytes() {
        let hooks = sites();
        assert_eq!((hooks[0].address, hooks[0].expected), (0x46FA30, &[0x81, 0xEC, 0x50, 0x02, 0x00, 0x00][..]));
        assert_eq!((hooks[1].address, hooks[1].expected), (0x470380, &[0xB8, 0xFC, 0xFE, 0x5E, 0x00][..]));
    }
}
