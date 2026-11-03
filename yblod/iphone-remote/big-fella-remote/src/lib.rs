//! big-fella-remote: the TV box in the iPhone's Control Center remote,
//! through Apple's Companion Link protocol, with nothing to install on the
//! phone. See README.md.

pub mod advertise;
pub mod config;
pub mod conn;
pub mod control;
pub mod crypto;
pub mod daemon;
pub mod frame;
pub mod input;
pub mod keys;
pub mod kodi;
pub mod opack;
pub mod pairing;
pub mod rti;
pub mod session;
pub mod speaker;
pub mod srp;
pub mod store;
pub mod tlv8;
pub mod touch;
#[cfg(target_os = "linux")]
pub mod uinput;

#[cfg(test)]
mod tests;
