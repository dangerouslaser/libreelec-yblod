//! A verified phone's messages: answers, and what they do. No I/O.
//!
//! Every message is an OPACK dictionary: `_i` its name, `_t` its kind (1
//! event, 2 request, 3 response), `_x` a transaction id, `_c` the content.
//! Facts about what the iPhone's remote sends and needs come from pyatv's
//! protocol documentation, atv-core and windows-apple-remote's notes (iOS
//! 27), and CompanionGames' (iOS 17, 18):
//!
//! - **Answer everything**, with `{"_x", "_t": 3, "_c"}`, unknown requests
//!   and events too: the remote (tvremoted) ends the session on an error.
//! - `_systemInfo`: answered with an Apple TV's details (ours are built in
//!   `advertise.rs`). iOS 27 may name it in a top-level `model` instead of
//!   `_i` (atv-core).
//! - `_sessionStart` (`_srvT` com.apple.tvremoteservices): our `_sid`.
//!   `TVRCSessionStart`: its content back.
//! - `_touchStart`: `{"_i": 1}`, a touch id (without one the remote gives
//!   up). `_hidT`: touch events (touch.rs). `_hidC`: buttons, `_hBtS` 1
//!   down, 2 up (keys.rs).
//! - `_interest` (`_regEvents`) and `FetchMediaControlStatus`: the media
//!   controls we have (`_mcF`: play, pause, skip ±, volume), which turns on
//!   the iPhone's own volume buttons. `_mcc`: media commands.
//! - `FetchAttentionState`: 3, awake.
//! - The keyboard: `_tiStart` (answered with the focused field, if any),
//!   `_tiStarted` / `_tiStopped` (we send them as fields take and lose the
//!   focus: the phone raises and drops its keyboard), `_tiC` (typing).

use std::collections::BTreeSet;

use crate::keys::{self, HID_SELECT, HID_VOLUME_DOWN, HID_VOLUME_UP, KEY_ENTER};
use crate::opack::Value;
use crate::rti::{self, Field};
use crate::touch::{self, Dir, Gesture, Pad};

/// pyatv's MediaControlFlags: Play 0x1, Pause 0x2, Volume 0x100, Skip
/// forward 0x200, Skip backward 0x400.
pub const MEDIA_FLAGS: i64 = 0x1 | 0x2 | 0x100 | 0x200 | 0x400;
/// A tap arrives as the Select button and (sometimes) as a touch: one OK
/// for both within this.
const SELECT_TWIN_MS: u64 = 400;
/// The volume buttons, held: a step every VOLUME_REPEAT_MS after
/// VOLUME_DELAY_MS (as remote-bridged's held volume button).
const VOLUME_DELAY_MS: u64 = 400;
const VOLUME_REPEAT_MS: u64 = 150;

#[derive(Debug, Clone, PartialEq)]
pub enum Effect {
    Key {
        code: u16,
        down: bool,
    },
    /// Down and up.
    Press(u16),
    /// One step: true up.
    Volume(bool),
    /// The remote's volume slider, 0-1.
    SetVolume(f64),
    Text(rti::Edit),
    /// The phone's name and model, from `_systemInfo`.
    About {
        name: String,
        model: String,
    },
}

/// What the daemon shares with every connection.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Shared {
    /// The text field the keyboard is for, while there is one.
    pub field: Option<Field>,
    /// The speaker's volume, 0-1, if known.
    pub volume: Option<f64>,
}

pub struct Config {
    pub home_key: u16,
    pub touch: touch::Tuning,
    /// Our `_systemInfo` answer.
    pub system_info: Value,
}

pub struct Session {
    cfg: Config,
    pad: Pad,
    /// A remote session is open (`_sessionStart` or `TVRCSessionStart`).
    started: bool,
    held: BTreeSet<u16>,
    /// Up or down, when it went down, the last step.
    volume: Option<(bool, u64, u64)>,
    last_select: Option<u64>,
    last_tap: Option<u64>,
    swallow_select_up: bool,
    next_xid: i64,
    /// The typing session the phone was last told about.
    told: Option<[u8; 16]>,
}

fn reply(msg: &Value, content: Value) -> Value {
    let xid = msg.get("_x").cloned().unwrap_or(Value::Int(0));
    Value::dict([("_c", content), ("_t", Value::Int(3)), ("_x", xid)])
}

fn empty() -> Value {
    Value::Dict(Vec::new())
}

impl Session {
    pub fn new(cfg: Config) -> Self {
        let pad = Pad::new(cfg.touch);
        Self {
            cfg,
            pad,
            started: false,
            held: BTreeSet::new(),
            volume: None,
            last_select: None,
            last_tap: None,
            swallow_select_up: false,
            next_xid: 1,
            told: None,
        }
    }

    fn event(&mut self, name: &str, content: Value) -> Value {
        let x = self.next_xid;
        self.next_xid += 1;
        Value::dict([("_i", Value::str(name)), ("_t", Value::Int(1)), ("_x", Value::Int(x)), ("_c", content)])
    }

    fn media_status(&mut self) -> Value {
        self.event("_iMC", Value::dict([("_mcF", Value::Int(MEDIA_FLAGS))]))
    }

    /// One message at `now` (ms): what to send back, and what it does.
    pub fn handle(&mut self, msg: &Value, shared: &Shared, now: u64) -> (Vec<Value>, Vec<Effect>) {
        let name = msg.get("_i").or_else(|| msg.get("model")).and_then(Value::as_str).unwrap_or("");
        let content = msg.get("_c").cloned().unwrap_or_else(empty);
        let mut out = Vec::new();
        let mut fx = Vec::new();
        let mut answer = empty();
        match name {
            "_systemInfo" => {
                answer = self.cfg.system_info.clone();
                let s = |k: &str| content.get(k).and_then(Value::as_str).unwrap_or("").to_owned();
                fx.push(Effect::About { name: s("name"), model: s("model") });
            }
            "_sessionStart" => {
                self.started = true;
                answer = Value::dict([("_sid", Value::Int(i64::from(rand::random::<u32>())))]);
            }
            "TVRCSessionStart" => {
                self.started = true;
                answer = content.clone();
            }
            "_sessionStop" => self.started = false,
            "_touchStart" => answer = Value::dict([("_i", Value::Int(1))]),
            "FetchAttentionState" => answer = Value::dict([("state", Value::Int(3))]),
            "FetchMediaControlStatus" => answer = Value::dict([("MediaControlFlags", Value::Int(MEDIA_FLAGS))]),
            "_interest" => {
                if let Some(Value::Array(events)) = content.get("_regEvents") {
                    for e in events.iter().filter_map(Value::as_str) {
                        match e {
                            "_iMC" => out.push(self.media_status()),
                            "MediaControlStatus" => {
                                out.push(self.event(e, Value::dict([("MediaControlFlags", Value::Int(MEDIA_FLAGS))])))
                            }
                            "SystemStatus" | "TVSystemStatus" => {
                                out.push(self.event(e, Value::dict([("state", Value::Int(3))])))
                            }
                            _ => {}
                        }
                    }
                }
            }
            "_hidC" => {
                let code = content.get("_hidC").and_then(Value::as_int).unwrap_or(0);
                let state = content.get("_hBtS").and_then(Value::as_int).unwrap_or(0);
                self.button(code, state == 1, now, &mut fx, &mut out);
            }
            "_hidT" => {
                let phase = content.get("_tPh").and_then(Value::as_int).unwrap_or(0);
                let x = content.get("_cx").and_then(Value::as_f64).unwrap_or(0.0);
                let y = content.get("_cy").and_then(Value::as_f64).unwrap_or(0.0);
                for g in self.pad.event(phase, x, y, now) {
                    self.gesture(g, now, &mut fx);
                }
            }
            "_mcc" | "MediaControlCommand" => {
                let cmd = content.get("_mcc").or_else(|| content.get("MediaControlCommand"));
                match cmd.and_then(Value::as_int).unwrap_or(0) {
                    5 => answer = Value::dict([("_vol", Value::Float(shared.volume.unwrap_or(0.5)))]),
                    6 => {
                        if let Some(v) = content.get("_vol").and_then(Value::as_f64) {
                            fx.push(Effect::SetVolume(v.clamp(0.0, 1.0)));
                        }
                    }
                    12 => answer = Value::dict([("_cse", Value::Bool(false))]),
                    c => {
                        let skip = content.get("_skpS").and_then(Value::as_f64).unwrap_or(1.0);
                        if let Some(k) = keys::media_key(c, skip) {
                            fx.push(Effect::Press(k));
                        }
                    }
                }
            }
            "_tiStart" => {
                if let Some(f) = &shared.field {
                    self.told = Some(f.session);
                    answer = Value::dict([("_tiV", Value::Int(1)), ("_tiD", Value::Data(rti::started(f)))]);
                }
            }
            "_tiC" => {
                if shared.field.is_some()
                    && let Some(e) = content.get("_tiD").and_then(Value::as_data).and_then(rti::edit)
                    && !e.is_empty()
                {
                    fx.push(Effect::Text(e));
                }
            }
            _ => {}
        }
        out.insert(0, reply(msg, answer));
        (out, fx)
    }

    fn button(&mut self, code: i64, down: bool, now: u64, fx: &mut Vec<Effect>, out: &mut Vec<Value>) {
        if code == HID_VOLUME_UP || code == HID_VOLUME_DOWN {
            let up = code == HID_VOLUME_UP;
            if down {
                fx.push(Effect::Volume(up));
                self.volume = Some((up, now, now));
            } else {
                self.volume = None;
                // pyatv waits for this (then asks the volume).
                out.push(self.media_status());
            }
            return;
        }
        let Some(key) = keys::hid_key(code, self.cfg.home_key) else { return };
        if code == HID_SELECT {
            if down && self.last_tap.is_some_and(|t| now.saturating_sub(t) < SELECT_TWIN_MS) {
                self.swallow_select_up = true;
                return;
            }
            if !down && std::mem::take(&mut self.swallow_select_up) {
                return;
            }
            if down {
                self.last_select = Some(now);
            }
        }
        if down {
            if self.held.insert(key) {
                fx.push(Effect::Key { code: key, down: true });
            }
        } else if self.held.remove(&key) {
            fx.push(Effect::Key { code: key, down: false });
        }
    }

    fn gesture(&mut self, g: Gesture, now: u64, fx: &mut Vec<Effect>) {
        match g {
            Gesture::Arrow(d) => fx.push(Effect::Press(match d {
                Dir::Up => keys::KEY_UP,
                Dir::Down => keys::KEY_DOWN,
                Dir::Left => keys::KEY_LEFT,
                Dir::Right => keys::KEY_RIGHT,
            })),
            Gesture::Tap => {
                if self.last_select.is_some_and(|t| now.saturating_sub(t) < SELECT_TWIN_MS) {
                    return;
                }
                self.last_tap = Some(now);
                fx.push(Effect::Press(KEY_ENTER));
            }
        }
    }

    /// Whether `tick` has anything to do (a touch, a held volume button).
    pub fn wants_tick(&self) -> bool {
        self.pad.active() || self.volume.is_some()
    }

    pub fn tick(&mut self, now: u64) -> Vec<Effect> {
        let mut fx = Vec::new();
        if let Some(g) = self.pad.tick(now) {
            self.gesture(g, now, &mut fx);
        }
        if let Some((up, since, last)) = self.volume
            && now.saturating_sub(since) >= VOLUME_DELAY_MS
            && now.saturating_sub(last) >= VOLUME_REPEAT_MS
        {
            fx.push(Effect::Volume(up));
            self.volume = Some((up, since, now));
        }
        fx
    }

    /// The focused field changed: tell the phone (once its remote is open).
    pub fn field_changed(&mut self, shared: &Shared) -> Vec<Value> {
        if !self.started {
            return Vec::new();
        }
        match &shared.field {
            Some(f) if self.told != Some(f.session) => {
                self.told = Some(f.session);
                let data = rti::started(f);
                vec![self.event("_tiStarted", Value::dict([("_tiV", Value::Int(1)), ("_tiD", Value::Data(data))]))]
            }
            None if self.told.take().is_some() => vec![self.event("_tiStopped", empty())],
            _ => Vec::new(),
        }
    }

    /// The phone's gone: every key it held goes up.
    pub fn release_all(&mut self) -> Vec<Effect> {
        self.volume = None;
        std::mem::take(&mut self.held).into_iter().map(|code| Effect::Key { code, down: false }).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::keys::*;

    fn session() -> Session {
        Session::new(Config {
            home_key: 172,
            touch: touch::Tuning::default(),
            system_info: Value::dict([("name", Value::str("big-fella"))]),
        })
    }

    fn msg(name: &str, x: i64, content: Value) -> Value {
        Value::dict([("_i", Value::str(name)), ("_t", Value::Int(2)), ("_x", Value::Int(x)), ("_c", content)])
    }

    fn hid(code: i64, state: i64) -> Value {
        msg("_hidC", 9, Value::dict([("_hBtS", Value::Int(state)), ("_hidC", Value::Int(code))]))
    }

    fn touch_ev(phase: i64, x: i64, y: i64) -> Value {
        msg("_hidT", 0, Value::dict([("_tPh", Value::Int(phase)), ("_cx", Value::Int(x)), ("_cy", Value::Int(y))]))
    }

    #[test]
    fn everything_is_answered() {
        let mut s = session();
        let sh = Shared::default();
        for name in ["_systemInfo", "_sessionStart", "SomethingNew", "_touchStart", "FetchAttentionState"] {
            let (out, _) = s.handle(&msg(name, 42, empty()), &sh, 0);
            assert_eq!(out[0].get("_t"), Some(&Value::Int(3)), "{name}");
            assert_eq!(out[0].get("_x"), Some(&Value::Int(42)), "{name}");
        }
        let (out, fx) = s.handle(
            &msg("_systemInfo", 1, Value::dict([("name", Value::str("iPhone")), ("model", Value::str("iPhone17,1"))])),
            &sh,
            0,
        );
        assert_eq!(out[0].get("_c").and_then(|c| c.get("name")).and_then(Value::as_str), Some("big-fella"));
        assert_eq!(fx, [Effect::About { name: "iPhone".into(), model: "iPhone17,1".into() }]);
        // iOS 27's _systemInfo, named by `model`.
        let ios27 = Value::dict([("model", Value::str("_systemInfo")), ("_x", Value::Int(5)), ("_c", empty())]);
        assert_eq!(s.handle(&ios27, &sh, 0).0[0].get("_c").and_then(|c| c.get("name")), Some(&Value::str("big-fella")));
        let (out, _) = s.handle(&msg("_touchStart", 3, empty()), &sh, 0);
        assert_eq!(out[0].get("_c"), Some(&Value::dict([("_i", Value::Int(1))])));
        let (out, _) = s.handle(
            &msg("_interest", 4, Value::dict([("_regEvents", Value::Array(vec![Value::str("_iMC")]))])),
            &sh,
            0,
        );
        assert_eq!(out[1].get("_i"), Some(&Value::str("_iMC")));
        assert_eq!(out[1].get("_c").and_then(|c| c.get("_mcF")), Some(&Value::Int(MEDIA_FLAGS)));
    }

    #[test]
    fn buttons_hold_and_release() {
        let mut s = session();
        let sh = Shared::default();
        assert_eq!(s.handle(&hid(5, 1), &sh, 0).1, [Effect::Key { code: KEY_ESC, down: true }]);
        assert_eq!(s.handle(&hid(5, 2), &sh, 50).1, [Effect::Key { code: KEY_ESC, down: false }]);
        assert_eq!(s.handle(&hid(7, 1), &sh, 100).1, [Effect::Key { code: 172, down: true }]);
        assert_eq!(s.handle(&hid(14, 1), &sh, 100).1, [Effect::Key { code: KEY_PLAYPAUSE, down: true }]);
        assert_eq!(s.handle(&hid(10, 1), &sh, 100).1, [], "Siri");
        // The phone goes away with buttons down: they go up.
        let mut up = s.release_all();
        up.sort_by_key(|e| format!("{e:?}"));
        assert_eq!(up, [Effect::Key { code: KEY_PLAYPAUSE, down: false }, Effect::Key { code: 172, down: false }]);
        assert_eq!(s.handle(&hid(7, 2), &sh, 200).1, [], "already up");
    }

    #[test]
    fn volume_steps_and_repeats() {
        let mut s = session();
        let sh = Shared { volume: Some(0.25), ..Shared::default() };
        assert_eq!(s.handle(&hid(8, 1), &sh, 0).1, [Effect::Volume(true)]);
        assert!(s.wants_tick());
        assert_eq!(s.tick(200), []);
        assert_eq!(s.tick(400), [Effect::Volume(true)]);
        assert_eq!(s.tick(450), []);
        assert_eq!(s.tick(560), [Effect::Volume(true)]);
        let (out, fx) = s.handle(&hid(8, 2), &sh, 600);
        assert_eq!((fx.len(), out[1].get("_i")), (0, Some(&Value::str("_iMC"))));
        assert!(!s.wants_tick());
        let get = msg("_mcc", 7, Value::dict([("_mcc", Value::Int(5))]));
        assert_eq!(s.handle(&get, &sh, 0).0[0].get("_c"), Some(&Value::dict([("_vol", Value::Float(0.25))])));
        let set = msg("_mcc", 8, Value::dict([("_mcc", Value::Int(6)), ("_vol", Value::Float(0.4))]));
        assert_eq!(s.handle(&set, &sh, 0).1, [Effect::SetVolume(0.4)]);
        let skip = msg("_mcc", 9, Value::dict([("_mcc", Value::Int(7)), ("_skpS", Value::Float(-10.0))]));
        assert_eq!(s.handle(&skip, &sh, 0).1, [Effect::Press(KEY_REWIND)]);
    }

    #[test]
    fn swipes_taps_and_one_ok_per_tap() {
        let mut s = session();
        let sh = Shared::default();
        s.handle(&touch_ev(1, 500, 500), &sh, 0);
        assert_eq!(s.handle(&touch_ev(2, 700, 500), &sh, 20).1, [Effect::Press(KEY_RIGHT)]);
        s.handle(&touch_ev(4, 700, 500), &sh, 40);
        // A tap as a touch, then as the Select button: one OK.
        s.handle(&touch_ev(1, 500, 500), &sh, 1000);
        assert_eq!(s.handle(&touch_ev(4, 502, 500), &sh, 1060).1, [Effect::Press(KEY_ENTER)]);
        assert_eq!(s.handle(&hid(6, 1), &sh, 1080).1, []);
        assert_eq!(s.handle(&hid(6, 2), &sh, 1100).1, []);
        // The other way round.
        assert_eq!(s.handle(&hid(6, 1), &sh, 3000).1, [Effect::Key { code: KEY_ENTER, down: true }]);
        assert_eq!(s.handle(&hid(6, 2), &sh, 3020).1, [Effect::Key { code: KEY_ENTER, down: false }]);
        s.handle(&touch_ev(1, 500, 500), &sh, 3030);
        assert_eq!(s.handle(&touch_ev(4, 500, 500), &sh, 3060).1, []);
        // Long after: both count.
        s.handle(&touch_ev(1, 500, 500), &sh, 5000);
        assert_eq!(s.handle(&touch_ev(4, 500, 500), &sh, 5050).1, [Effect::Press(KEY_ENTER)]);
    }

    #[test]
    fn the_keyboard() {
        let mut s = session();
        let field = Field { session: [3; 16], text: "ab".into(), title: "Search".into() };
        let mut sh = Shared::default();
        // No field: _tiStart's answer has no _tiD, typing goes nowhere.
        let (out, _) = s.handle(&msg("_tiStart", 1, empty()), &sh, 0);
        assert_eq!(out[0].get("_c"), Some(&empty()));
        let typing = msg(
            "_tiC",
            2,
            Value::dict([("_tiV", Value::Int(1)), ("_tiD", Value::Data(rti::operations(&[3; 16], None, 0, "c")))]),
        );
        assert_eq!(s.handle(&typing, &sh, 0).1, []);
        // Before the remote session opens: nothing pushed.
        sh.field = Some(field.clone());
        assert!(s.field_changed(&sh).is_empty());
        s.handle(&msg("_sessionStart", 3, empty()), &sh, 0);
        let pushed = s.field_changed(&sh);
        assert_eq!(pushed[0].get("_i"), Some(&Value::str("_tiStarted")));
        let data = pushed[0].get("_c").and_then(|c| c.get("_tiD")).and_then(Value::as_data).unwrap();
        assert_eq!(rti::read_started(data), Some(([3; 16], "ab".into())));
        assert!(s.field_changed(&sh).is_empty(), "told once");
        assert_eq!(s.handle(&typing, &sh, 0).1, [Effect::Text(rti::Edit { insert: "c".into(), ..Default::default() })]);
        let (out, _) = s.handle(&msg("_tiStart", 4, empty()), &sh, 0);
        assert!(out[0].get("_c").and_then(|c| c.get("_tiD")).is_some());
        sh.field = None;
        let gone = s.field_changed(&sh);
        assert_eq!(gone[0].get("_i"), Some(&Value::str("_tiStopped")));
        assert!(gone[0].get("_c").and_then(|c| c.get("_tiD")).is_none());
        assert!(s.field_changed(&sh).is_empty());
    }
}
