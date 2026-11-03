//! Where keys go: the virtual keyboard (uinput.rs), or a recorder in
//! tests.

use std::sync::{Arc, Mutex};

pub trait InputSink: Send {
    fn key(&mut self, code: u16, down: bool);

    fn press(&mut self, code: u16) {
        self.key(code, true);
        self.key(code, false);
    }
}

/// Nowhere (no uinput).
pub struct NoInput;

impl InputSink for NoInput {
    fn key(&mut self, code: u16, down: bool) {
        tracing::debug!("key {code} {} (nowhere to go)", if down { "down" } else { "up" });
    }
}

/// Keeps what it's sent, for tests.
#[derive(Clone, Default)]
pub struct Recorder(pub Arc<Mutex<Vec<(u16, bool)>>>);

impl InputSink for Recorder {
    fn key(&mut self, code: u16, down: bool) {
        if let Ok(mut v) = self.0.lock() {
            v.push((code, down));
        }
    }
}
