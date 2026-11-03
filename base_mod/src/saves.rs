//! Moves saves to the profile's folder.
use crate::hook::Hook;
use std::sync::OnceLock;

const SAVE_ROOT: usize = 0x4DB7F0;
const MAKE_DIRECTORY: usize = 0x4DC320;

/// The game keeps this path in a 260-byte buffer and adds folder and file names to it.
pub const MAX_ROOT: usize = 200;

static ROOT: OnceLock<Vec<u8>> = OnceLock::new();

pub fn root_bytes(directory: &str) -> Result<Vec<u8>, String> {
    let root = directory.replace('\\', "/");
    let root = root.trim_end_matches('/');
    if root.is_empty() {
        return Err("session file has no save folder".to_string());
    }
    if root.len() > MAX_ROOT {
        return Err(format!("save folder path is too long for the game: {root}"));
    }
    let mut bytes = root.as_bytes().to_vec();
    bytes.push(0);
    Ok(bytes)
}

/// Stock code puts the game folder plus `\saves` at `this + 8` and creates that folder.
unsafe extern "thiscall" fn save_root_detour(this: *mut u8, _first: u32, _second: u32) -> u32 {
    let root = ROOT.get().expect("hooks run only after the save root is set");
    let buffer = this.add(8);
    std::ptr::copy_nonoverlapping(root.as_ptr(), buffer, root.len());
    let make_directory: unsafe extern "C" fn(*const u8) -> u32 = std::mem::transmute(MAKE_DIRECTORY);
    make_directory(buffer);
    crate::log::line("save root redirected");
    0
}

pub fn hooks(save_dir: &str) -> Result<Vec<Hook>, String> {
    // A second call would keep the first root, so a session sets it only once.
    let _ = ROOT.set(root_bytes(save_dir)?);
    Ok(vec![Hook {
        address: SAVE_ROOT,
        expected: &[0x56, 0x8D, 0x71, 0x08, 0x68, 0x04, 0x01, 0x00, 0x00],
        detour: save_root_detour as usize,
        original: None,
    }])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn root_ends_with_one_null() {
        assert_eq!(root_bytes("D:/profile/save").unwrap(), b"D:/profile/save\0");
    }

    #[test]
    fn backslashes_become_forward_slashes() {
        assert_eq!(root_bytes(r"D:\profile\save").unwrap(), b"D:/profile/save\0");
    }

    #[test]
    fn a_trailing_slash_is_removed() {
        assert_eq!(root_bytes("D:/profile/save/").unwrap(), b"D:/profile/save\0");
    }

    #[test]
    fn a_path_at_the_limit_fits() {
        assert!(root_bytes(&"a".repeat(MAX_ROOT)).is_ok());
    }

    #[test]
    fn a_longer_path_is_refused() {
        let error = root_bytes(&"a".repeat(MAX_ROOT + 1)).unwrap_err();
        assert!(error.contains("too long"), "{error}");
    }

    #[test]
    fn an_empty_path_is_refused() {
        assert!(root_bytes("").is_err());
    }
}
