//! The virtual keyboard, "big-fella iPhone remote": the keys keys.rs maps
//! the remote's buttons, swipes and media commands to. KWin reads it like
//! any other keyboard (and repeats a held key, as for the LG remote's
//! remote-bridged device).

use anyhow::{Context, Result};
use evdev::uinput::{VirtualDevice, VirtualDeviceBuilder};
use evdev::{AttributeSet, EventType, InputEvent, Key};
use tracing::warn;

use crate::input::InputSink;

pub const NAME: &str = "big-fella iPhone remote";

pub struct Uinput {
    dev: VirtualDevice,
    failed: bool,
}

impl Uinput {
    pub fn open(home_key: u16) -> Result<Self> {
        let mut keys = AttributeSet::<Key>::new();
        for code in crate::keys::all(home_key) {
            keys.insert(Key::new(code));
        }
        let dev = VirtualDeviceBuilder::new()
            .context("opening /dev/uinput (is the uinput module loaded, and may we write it?)")?
            .name(NAME)
            .with_keys(&keys)?
            .build()?;
        Ok(Self { dev, failed: false })
    }
}

impl InputSink for Uinput {
    fn key(&mut self, code: u16, down: bool) {
        // evdev's emit ends the batch with a SYN_REPORT.
        if let Err(e) = self.dev.emit(&[InputEvent::new(EventType::KEY, code, i32::from(down))]) {
            if !self.failed {
                warn!("uinput: {e}");
                self.failed = true;
            }
        }
    }
}
