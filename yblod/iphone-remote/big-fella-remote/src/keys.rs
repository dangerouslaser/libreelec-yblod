//! The remote's buttons as the keys the shell and the apps already know:
//! the same ones remote-bridged sends for the LG remote
//! (remote-bridged/src/keymap.rs `desktop_key`), so nothing new is needed
//! on the other side. The shell treats them as ordinary keys
//! (big-fella-shell/shell/services/Input.qml).
//!
//! `_hidC` codes (pyatv's HidCommand): 1-4 Up/Down/Left/Right, 5 Menu,
//! 6 Select, 7 Home, 8/9 Volume Up/Down, 10 Siri, 11 Screensaver, 12 Sleep,
//! 13 Wake, 14 PlayPause, 15/16 Channel +/−, 17 Guide, 18/19 Page Up/Down.
//! `_mcc` media commands: 1 Play, 2 Pause, 3 Next, 4 Previous, 5 GetVolume,
//! 6 SetVolume, 7 SkipBy (`_skpS` seconds), 8-11 fast forward / rewind
//! begin and end, 12/13 caption settings.

pub const KEY_ESC: u16 = 1;
pub const KEY_ENTER: u16 = 28;
pub const KEY_UP: u16 = 103;
pub const KEY_PAGEUP: u16 = 104;
pub const KEY_LEFT: u16 = 105;
pub const KEY_RIGHT: u16 = 106;
pub const KEY_DOWN: u16 = 108;
pub const KEY_PAGEDOWN: u16 = 109;
pub const KEY_VOLUMEDOWN: u16 = 114;
pub const KEY_VOLUMEUP: u16 = 115;
pub const KEY_PAUSE: u16 = 119;
pub const KEY_NEXTSONG: u16 = 163;
pub const KEY_PLAYPAUSE: u16 = 164;
pub const KEY_PREVIOUSSONG: u16 = 165;
pub const KEY_REWIND: u16 = 168;
pub const KEY_FASTFORWARD: u16 = 208;
pub const KEY_EPG: u16 = 365;

pub const HID_SELECT: i64 = 6;
pub const HID_VOLUME_UP: i64 = 8;
pub const HID_VOLUME_DOWN: i64 = 9;

/// A button's key. None: not ours to act on (Siri, the volume buttons,
/// which go to the speaker, and sleep/wake: the TV's power is tvd's).
pub fn hid_key(code: i64, home_key: u16) -> Option<u16> {
    Some(match code {
        1 => KEY_UP,
        2 => KEY_DOWN,
        3 => KEY_LEFT,
        4 => KEY_RIGHT,
        5 => KEY_ESC,
        6 => KEY_ENTER,
        7 => home_key,
        14 => KEY_PLAYPAUSE,
        // Page Up/Down, as remote-bridged's CH +/−: the browsers and lists
        // page with them, and big-fella's Live TV takes them as the
        // channel keys.
        15 | 18 => KEY_PAGEUP,
        16 | 19 => KEY_PAGEDOWN,
        17 => KEY_EPG,
        _ => return None,
    })
}

/// A media command's key (pressed and released).
pub fn media_key(command: i64, skip_seconds: f64) -> Option<u16> {
    Some(match command {
        1 => KEY_PLAYPAUSE,
        2 => KEY_PAUSE,
        3 => KEY_NEXTSONG,
        4 => KEY_PREVIOUSSONG,
        // The ±10 s buttons: the player's fast forward and rewind (as the
        // LG remote's ⏩ ⏪: big-fella-player reads them as seeks).
        7 if skip_seconds < 0.0 => KEY_REWIND,
        7 => KEY_FASTFORWARD,
        8 => KEY_FASTFORWARD,
        10 => KEY_REWIND,
        _ => return None,
    })
}

/// Every key the virtual keyboard may send.
pub fn all(home_key: u16) -> Vec<u16> {
    let mut keys: Vec<u16> = (1..=19).filter_map(|c| hid_key(c, home_key)).collect();
    keys.extend((1..=10).filter_map(|c| media_key(c, 1.0)));
    keys.extend([KEY_REWIND, KEY_VOLUMEUP, KEY_VOLUMEDOWN]);
    keys.sort_unstable();
    keys.dedup();
    keys
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_remote_bridged_keys() {
        assert_eq!(hid_key(5, 172), Some(KEY_ESC));
        assert_eq!(hid_key(6, 172), Some(KEY_ENTER));
        assert_eq!(hid_key(7, 172), Some(172));
        assert_eq!(hid_key(7, 102), Some(102));
        for no in [8, 9, 10, 11, 12, 13, 20, -1] {
            assert_eq!(hid_key(no, 172), None, "{no}");
        }
        assert_eq!(media_key(7, -10.0), Some(KEY_REWIND));
        assert_eq!(media_key(7, 10.0), Some(KEY_FASTFORWARD));
        let all = all(172);
        assert!(all.contains(&172) && all.contains(&KEY_VOLUMEUP) && all.contains(&KEY_EPG));
    }
}
