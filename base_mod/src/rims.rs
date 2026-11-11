//! Rim colours. The game loads a rim texture for each stock team but never picks one, and every
//! wheel model uses one shared texture. So a car gets another colour only from wheel models with
//! their own material, which the tool generates: while such a car's models load, the wheel folder
//! points at its copy.
use crate::hook::Hook;
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

type LoadCarModels = unsafe extern "thiscall" fn(*mut u8, *const u8, i32, i32) -> u8;

static CAR_MODELS_ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static WHEEL_FOLDER_NOW: AtomicUsize = AtomicUsize::new(STOCK_WHEEL_FOLDER);
static FOLDERS: OnceLock<HashMap<String, CString>> = OnceLock::new();

/// Each car's wheel folder. Rim 0 is the stock wheel, so it needs none.
fn folders_of(rims: &HashMap<String, u32>) -> HashMap<String, String> {
    rims.iter().filter(|(_, rim)| **rim > 0).map(|(car, rim)| (car.clone(), format!("cars/generic_models/cache/rim_{rim}"))).collect()
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
    fn hooks_check_their_bytes() {
        let hooks = sites();
        assert_eq!((hooks[0].address, hooks[0].expected), (0x46FA30, &[0x81, 0xEC, 0x50, 0x02, 0x00, 0x00][..]));
        assert_eq!((hooks[1].address, hooks[1].expected), (0x470380, &[0xB8, 0xFC, 0xFE, 0x5E, 0x00][..]));
    }
}
