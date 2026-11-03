//! The session's log file. A failed write is ignored, because a log must never stop the game.
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::sync::OnceLock;

static PATH: OnceLock<String> = OnceLock::new();

/// Starts a new log for this run. Only the first call has any effect.
pub fn init(path: &str) {
    if PATH.set(path.to_string()).is_ok() {
        let _ = File::create(path);
    }
}

pub fn line(text: &str) {
    if let Some(path) = PATH.get() {
        if let Ok(mut file) = OpenOptions::new().append(true).open(path) {
            let _ = writeln!(file, "{text}");
        }
    }
}
