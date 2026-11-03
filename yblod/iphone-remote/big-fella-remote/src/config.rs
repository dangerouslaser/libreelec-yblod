//! /etc/big-fella/remote.toml (optional: without it, the defaults).

use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::Deserialize;

use crate::touch;

#[derive(Debug, Clone, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Config {
    /// The name the iPhone lists. Empty: the host name ("big-fella" without
    /// one).
    pub name: String,
    /// Whether new phones may pair, until Settings says otherwise (its
    /// choice is kept in the state folder).
    pub pairing: bool,
    /// The TCP port phones connect to (an Apple TV's usual one).
    pub port: u16,
    /// Announce us over mDNS (_companion-link._tcp). Off: nothing finds us.
    pub advertise: bool,
    /// The mDNS host name our service points at (its A/AAAA records).
    /// Empty: the host name. Set it where another responder already
    /// answers for the host name (Avahi on LibreELEC), so the two don't
    /// claim one name with different addresses.
    pub mdns_host: String,
    /// The Apple TV model we say we are, and its Rapport flags: values
    /// receivers known to work with the iPhone's remote use
    /// (CompanionGames and windows-apple-remote; atv-core: AppleTV14,1 and
    /// 0x36782).
    pub model: String,
    pub rp_flags: String,
    pub state_dir: PathBuf,
    /// The home screen's way in (JSON lines; see README).
    pub control_socket: PathBuf,
    /// Who may use the control socket besides root. Empty: uid 1000-59999.
    pub control_uids: Vec<u32>,
    /// Create the virtual keyboard. Off: pairing only (tests).
    pub uinput: bool,
    /// The key the remote's TV (Home) button sends (remote-bridged's
    /// home_key: 172, KEY_HOMEPAGE).
    pub home_key: u16,
    /// The phone's Return as Enter on the virtual keyboard (after the
    /// text). Off: only the control socket's text event says so
    /// (`"submit": true`), for a home screen that ends the field itself
    /// (Kodi's keyboard dialog: big-fella-remote-kodi).
    pub return_key: bool,
    pub touch: Touch,
    pub speaker: Speaker,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Touch {
    /// Travel per arrow, of the touch area's 1000.
    pub step: f64,
    /// How close to an edge a resting finger repeats, of 1000.
    pub edge: f64,
    pub edge_delay_ms: u64,
    pub repeat_ms: u64,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Speaker {
    /// The iPhone's volume buttons go to speakerd (the speaker the TV
    /// plays through) while it's up and has its speaker; otherwise they're
    /// the volume keys, for the shell (PipeWire's volume).
    pub enabled: bool,
    /// speakerd's socket. Empty: the first /run/user/<uid>/speakerd.sock.
    pub socket: String,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            name: String::new(),
            pairing: true,
            port: 49153,
            advertise: true,
            mdns_host: String::new(),
            model: "AppleTV5,3".into(),
            rp_flags: "0xB6782".into(),
            state_dir: "/var/lib/big-fella-remote".into(),
            control_socket: "/run/big-fella-remote/control.sock".into(),
            control_uids: Vec::new(),
            uinput: true,
            home_key: 172,
            return_key: true,
            touch: Touch::default(),
            speaker: Speaker::default(),
        }
    }
}

impl Default for Touch {
    fn default() -> Self {
        let t = touch::Tuning::default();
        Self { step: t.step, edge: t.edge, edge_delay_ms: t.edge_delay_ms, repeat_ms: t.repeat_ms }
    }
}

impl Default for Speaker {
    fn default() -> Self {
        Self { enabled: true, socket: String::new() }
    }
}

impl Config {
    pub fn touch(&self) -> touch::Tuning {
        touch::Tuning {
            step: self.touch.step.clamp(40.0, 600.0),
            edge: self.touch.edge.clamp(0.0, 400.0),
            edge_delay_ms: self.touch.edge_delay_ms.clamp(100, 5000),
            repeat_ms: self.touch.repeat_ms.clamp(40, 2000),
            ..touch::Tuning::default()
        }
    }

    pub fn control_allowed(&self, uid: u32) -> bool {
        uid == 0
            || if self.control_uids.is_empty() {
                (1000..60000).contains(&uid)
            } else {
                self.control_uids.contains(&uid)
            }
    }

    /// The name phones list.
    pub fn display_name(&self) -> String {
        let n = self.name.trim();
        if !n.is_empty() {
            return n.chars().take(63).collect();
        }
        hostname().unwrap_or_else(|| "big-fella".into())
    }
}

pub fn parse(text: &str) -> Result<Config> {
    toml::from_str(text).context("reading the config")
}

pub fn load(path: &Path) -> Result<Config> {
    match std::fs::read_to_string(path) {
        Ok(text) => parse(&text).with_context(|| path.display().to_string()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Config::default()),
        Err(e) => Err(e).with_context(|| format!("reading {}", path.display())),
    }
}

/// The host name: /etc/hostname, else the kernel's.
pub fn hostname() -> Option<String> {
    ["/etc/hostname", "/proc/sys/kernel/hostname"].iter().find_map(|p| {
        let h = std::fs::read_to_string(p).ok()?;
        let h = h.trim();
        (!h.is_empty() && h != "localhost").then(|| h.to_owned())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_and_overrides() {
        let c = parse("").unwrap();
        assert!(c.pairing && c.advertise && c.uinput && c.speaker.enabled && c.return_key);
        assert!(c.mdns_host.is_empty());
        assert_eq!((c.port, c.home_key, c.model.as_str()), (49153, 172, "AppleTV5,3"));
        assert!(c.control_allowed(0) && c.control_allowed(1000) && !c.control_allowed(999));
        let c = parse("name = \"Living room\"\nport = 50000\n[touch]\nstep = 5.0").unwrap();
        assert_eq!((c.display_name().as_str(), c.port, c.touch().step), ("Living room", 50000, 40.0));
        assert!(parse("prot = 1").is_err());
    }

    #[test]
    fn the_shipped_example_parses() {
        parse(include_str!("../packaging/remote.toml")).unwrap();
    }
}
