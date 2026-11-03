//! Kodi as the home screen: big-fella-remote-kodi, a control socket client
//! (as big-fella-shell's services/Remote.qml) that talks to Kodi's JSON-RPC
//! over TCP (127.0.0.1:9090, "Allow remote control from applications on
//! this system").
//!
//! - The pairing PIN: a Kodi notification while it's up
//!   (GUI.ShowNotification), and one when a phone has paired.
//! - The phone's keyboard: Kodi announces its keyboard dialog
//!   (Input.OnInputRequested, with the title and the text) and its end
//!   (Input.OnInputFinished); the bridge offers and withdraws the field on
//!   the control socket. The phone's typing comes back as edits, applied
//!   to the text the bridge keeps and sent whole (Input.SendText); the
//!   phone's Return ends the dialog (`done`). The daemon runs with
//!   `return_key = false`, so no Enter follows into the window under it.
//!
//! The buttons, swipes and volume keys go to Kodi as keys on the virtual
//! keyboard, as everywhere else (Kodi on GBM reads evdev).

use serde_json::{Value, json};

use crate::rti::Edit;

/// What the bridge does about a message, from either side.
#[derive(Debug, Clone, PartialEq)]
pub enum Out {
    /// A JSON-RPC request to Kodi (without its id).
    Kodi(Value),
    /// A line for the control socket.
    Control(Value),
}

/// The bridge's state: the keyboard dialog it offered, and the PIN it
/// showed.
#[derive(Debug, Default)]
pub struct Bridge {
    field: i64,
    open: bool,
    text: String,
    title: String,
    pin: Option<String>,
}

/// Kodi's notification time, at most (its toasts need a bound).
const PIN_MS_MAX: u64 = 120_000;

impl Bridge {
    /// A notification from Kodi (`{"method": ..., "params": ...}`).
    pub fn from_kodi(&mut self, msg: &Value) -> Vec<Out> {
        let Some(method) = msg.get("method").and_then(Value::as_str) else {
            return Vec::new();
        };
        match method {
            "Input.OnInputRequested" => {
                let data = &msg["params"]["data"];
                let kind = data.get("type").and_then(Value::as_str).unwrap_or("keyboard");
                let secret = kind.contains("password");
                self.field += 1;
                self.open = true;
                // A password's text isn't sent to the phone (as the shell).
                self.text =
                    if secret { String::new() } else { data.get("value").and_then(Value::as_str).unwrap_or("").into() };
                self.title = data.get("title").and_then(Value::as_str).unwrap_or("").chars().take(64).collect();
                vec![self.offer()]
            }
            "Input.OnInputFinished" | "System.OnQuit" | "System.OnRestart" => self.close(),
            _ => Vec::new(),
        }
    }

    /// Kodi went away (its socket closed): the field with it.
    pub fn kodi_gone(&mut self) -> Vec<Out> {
        self.close()
    }

    /// A line from the control socket.
    pub fn from_control(&mut self, msg: &Value) -> Vec<Out> {
        if let Some(state) = msg.get("state") {
            return self.state(state);
        }
        match msg.get("event").and_then(Value::as_str) {
            Some("text") if self.open => {
                let edit = Edit {
                    replace: msg.get("replace").and_then(Value::as_str).map(str::to_owned),
                    delete: msg.get("delete").and_then(Value::as_u64).unwrap_or(0).min(u64::from(u32::MAX)) as u32,
                    insert: msg.get("insert").and_then(Value::as_str).unwrap_or("").to_owned(),
                };
                let submit = msg.get("submit").and_then(Value::as_bool).unwrap_or(false);
                apply(&mut self.text, &edit);
                let mut out = vec![Out::Kodi(json!({"method": "Input.SendText",
                                                    "params": {"text": self.text, "done": submit}}))];
                if submit {
                    // Kodi's Input.OnInputFinished follows; the phone's
                    // keyboard can go now.
                    out.extend(self.close());
                } else {
                    // What's in the field now, for the phone to show.
                    out.push(self.offer());
                }
                out
            }
            Some("paired") => {
                let name = msg["phone"]["name"].as_str().unwrap_or("iPhone");
                vec![notification("iPhone remote", &format!("{name} paired"), 5000)]
            }
            _ => Vec::new(),
        }
    }

    fn state(&mut self, state: &Value) -> Vec<Out> {
        let request = state.get("request").filter(|r| !r.is_null());
        let pin = request.and_then(|r| r.get("pin")).and_then(Value::as_str).map(str::to_owned);
        if pin == self.pin {
            return Vec::new();
        }
        self.pin = pin.clone();
        let Some(pin) = pin else {
            return Vec::new();
        };
        let seconds = request.and_then(|r| r.get("seconds")).and_then(Value::as_u64).unwrap_or(120);
        let address = request.and_then(|r| r.get("address")).and_then(Value::as_str).unwrap_or("");
        let name = state.get("name").and_then(Value::as_str).unwrap_or("this box");
        let ms = (seconds * 1000).clamp(5000, PIN_MS_MAX);
        let from = if address.is_empty() { String::new() } else { format!(" ({address})") };
        vec![notification(
            &format!("Pair an iPhone with {name}"),
            &format!("PIN {pin}  — type it on the iPhone{from}"),
            ms,
        )]
    }

    fn offer(&self) -> Out {
        Out::Control(json!({"cmd": "keyboard", "open": true, "field": self.field,
                            "text": self.text, "title": self.title}))
    }

    fn close(&mut self) -> Vec<Out> {
        if !self.open {
            return Vec::new();
        }
        self.open = false;
        self.text.clear();
        vec![Out::Control(json!({"cmd": "keyboard", "open": false}))]
    }
}

fn notification(title: &str, message: &str, ms: u64) -> Out {
    Out::Kodi(json!({"method": "GUI.ShowNotification",
                     "params": {"title": title, "message": message, "displaytime": ms}}))
}

/// The phone's edit on the text, the cursor at its end (Kodi's dialog
/// gets the whole text).
pub fn apply(text: &mut String, edit: &Edit) {
    if let Some(r) = &edit.replace {
        *text = r.clone();
    }
    for _ in 0..edit.delete {
        if text.pop().is_none() {
            break;
        }
    }
    text.push_str(&edit.insert);
    // As the daemon bounds an edit.
    if text.chars().count() > 4096 {
        *text = text.chars().take(4096).collect();
    }
}

/// Kodi's JSON-RPC over TCP sends JSON objects one after another with no
/// separator: the whole ones at the front of `buf` (taken off it), and
/// whether what's left can't be JSON (then dropped).
pub fn split_messages(buf: &mut Vec<u8>) -> Vec<Value> {
    let mut out = Vec::new();
    let mut it = serde_json::Deserializer::from_slice(buf).into_iter::<Value>();
    let mut used = 0;
    loop {
        match it.next() {
            Some(Ok(v)) => {
                used = it.byte_offset();
                out.push(v);
            }
            Some(Err(e)) if e.is_eof() => break,
            Some(Err(_)) => {
                // Not JSON: nothing after it can be trusted to line up.
                used = buf.len();
                break;
            }
            None => {
                used = buf.len();
                break;
            }
        }
    }
    buf.drain(..used);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kodi(method: &str, data: Value) -> Value {
        json!({"jsonrpc": "2.0", "method": method, "params": {"data": data, "sender": "xbmc"}})
    }

    #[test]
    fn the_keyboard_dialog() {
        let mut b = Bridge::default();
        let out =
            b.from_kodi(&kodi("Input.OnInputRequested", json!({"title": "Search", "type": "keyboard", "value": "ab"})));
        assert_eq!(
            out,
            [Out::Control(json!({"cmd": "keyboard", "open": true, "field": 1, "text": "ab", "title": "Search"}))]
        );
        // The phone deletes one and types two.
        let out =
            b.from_control(&json!({"event": "text", "replace": null, "delete": 1, "insert": "çd", "submit": false}));
        assert_eq!(out[0], Out::Kodi(json!({"method": "Input.SendText", "params": {"text": "açd", "done": false}})));
        assert_eq!(
            out[1],
            Out::Control(json!({"cmd": "keyboard", "open": true, "field": 1, "text": "açd", "title": "Search"}))
        );
        // Return: the whole text, done, and the phone's keyboard goes.
        let out = b.from_control(&json!({"event": "text", "replace": "x", "delete": 0, "insert": "", "submit": true}));
        assert_eq!(
            out,
            [
                Out::Kodi(json!({"method": "Input.SendText", "params": {"text": "x", "done": true}})),
                Out::Control(json!({"cmd": "keyboard", "open": false})),
            ]
        );
        // Kodi's own end after that: nothing more.
        assert!(b.from_kodi(&kodi("Input.OnInputFinished", json!(null))).is_empty());
        // Typing with no dialog: ignored.
        assert!(b.from_control(&json!({"event": "text", "insert": "y"})).is_empty());
    }

    #[test]
    fn a_password_isnt_sent_and_kodi_going_closes() {
        let mut b = Bridge::default();
        let out = b.from_kodi(&kodi(
            "Input.OnInputRequested",
            json!({"title": "Password", "type": "password", "value": "hunter2"}),
        ));
        assert_eq!(
            out,
            [Out::Control(json!({"cmd": "keyboard", "open": true, "field": 1, "text": "", "title": "Password"}))]
        );
        assert_eq!(b.kodi_gone(), [Out::Control(json!({"cmd": "keyboard", "open": false}))]);
        assert!(b.kodi_gone().is_empty());
    }

    #[test]
    fn the_pin_once_per_request() {
        let mut b = Bridge::default();
        let up = json!({"state": {"name": "LibreELEC", "request": {"pin": "4821", "address": "192.168.1.20", "seconds": 118}}});
        let out = b.from_control(&up);
        assert_eq!(out.len(), 1);
        let Out::Kodi(n) = &out[0] else { panic!() };
        assert_eq!(n["method"], "GUI.ShowNotification");
        assert!(n["params"]["message"].as_str().unwrap().contains("4821"));
        assert_eq!(n["params"]["displaytime"], 118_000);
        assert!(b.from_control(&up).is_empty(), "the same PIN again");
        assert!(b.from_control(&json!({"state": {"request": null}})).is_empty());
        assert_eq!(b.from_control(&up).len(), 1, "a new request");
        let out = b.from_control(&json!({"event": "paired", "phone": {"id": "X", "name": "Bryan's iPhone"}}));
        let Out::Kodi(n) = &out[0] else { panic!() };
        assert_eq!(n["params"]["message"], "Bryan's iPhone paired");
    }

    #[test]
    fn edits() {
        let mut t = String::from("héllo");
        apply(&mut t, &Edit { replace: None, delete: 2, insert: "p!".into() });
        assert_eq!(t, "hélp!");
        apply(&mut t, &Edit { replace: Some("ab".into()), delete: 5, insert: "c".into() });
        assert_eq!(t, "c");
    }

    #[test]
    fn kodis_stream() {
        let mut buf = br#"{"id":1,"result":"OK"}{"method":"Input.OnInputRequested","params":{}}{"id":2,"res"#.to_vec();
        let got = split_messages(&mut buf);
        assert_eq!(got.len(), 2);
        assert_eq!(got[1]["method"], "Input.OnInputRequested");
        assert_eq!(buf, br#"{"id":2,"res"#);
        buf.extend_from_slice(br#"ult":"OK"} "#);
        assert_eq!(split_messages(&mut buf), [json!({"id": 2, "result": "OK"})]);
        assert!(buf.is_empty());
        let mut junk = b"not json {".to_vec();
        assert!(split_messages(&mut junk).is_empty());
        assert!(junk.is_empty());
    }
}
