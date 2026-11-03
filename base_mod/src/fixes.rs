//! Bugs in the stock game that added content can expose.
use crate::hook::Patch;

const CHALLENGE_OBJECT_SIZE: usize = 0x49CF2C;
const LAST_BYTE_OFFSET: u32 = 0x130;
const SAFE_SIZE: u32 = 0x140;

/// Challenge setup allocates 0x130 bytes, then writes one byte at offset 0x130. That byte lands
/// on the size field of the next heap block, and the game asserts when that block is freed.
/// Stock heap layouts usually hide this, but any change in allocation sizes can expose it.
pub fn patches() -> Vec<Patch> {
    vec![Patch {
        address: CHALLENGE_OBJECT_SIZE,
        old: LAST_BYTE_OFFSET.to_le_bytes().to_vec(),
        new: SAFE_SIZE.to_le_bytes().to_vec(),
    }]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn challenge_object_covers_its_last_byte() {
        let fix = &patches()[0];
        assert_eq!(fix.old, LAST_BYTE_OFFSET.to_le_bytes());
        let size = u32::from_le_bytes(fix.new.clone().try_into().unwrap());
        assert!(size > LAST_BYTE_OFFSET);
    }

    #[test]
    fn fixes_keep_the_code_size() {
        assert!(patches().iter().all(|fix| fix.old.len() == fix.new.len()));
    }
}
