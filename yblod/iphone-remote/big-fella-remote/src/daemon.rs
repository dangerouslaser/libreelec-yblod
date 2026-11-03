//! The daemon: connections, pairing, the keys, the speaker and the home
//! screen, in one event loop that owns the state.
//!
//! The state the home screen gets (`{"state": ...}` on the control socket):
//!
//! ```json
//! {"name": "big-fella", "pairing": true, "keyboard": false, "remotes": 1,
//!  "phones": [{"id", "name", "model", "paired_at", "connected", "address"}],
//!  "request": null | {"pin": "4821", "address": "192.168.1.20", "seconds": 118}}
//! ```

use std::collections::{BTreeMap, HashMap};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr};
use std::sync::{Arc, Mutex, RwLock};
use std::time::Duration;

use anyhow::Result;
use rand::RngCore;
use serde_json::{Value, json};
use tokio::net::{TcpListener, UnixListener};
use tokio::sync::{mpsc, watch};
use tokio::time::{Instant, MissedTickBehavior, interval};
use tracing::{info, warn};

use crate::config::Config;
use crate::conn::{self, Ctx, ToConn, ToDaemon};
use crate::control::{self, ControlEvent};
use crate::input::InputSink;
use crate::keys::{KEY_ENTER, KEY_VOLUMEDOWN, KEY_VOLUMEUP};
use crate::pairing::{self, NewPhone};
use crate::rti::{Edit, Field};
use crate::session::{Effect, Shared};
use crate::speaker;
use crate::store::{Phone, Store, hex};
use crate::tlv8;

/// Connections at once, from one address and in all.
const MAX_PER_ADDRESS: usize = 4;
const MAX_CONNECTIONS: usize = 16;
/// The PIN stays on the screen this long at most (the phone's own pairing
/// sheet gives up before that).
const PIN_SECONDS: u64 = 120;
/// After a wrong PIN, the next try waits this long.
const BACKOFF: Duration = Duration::from_secs(3);
/// The phone's Return: the text first, then Enter this much later (two
/// ways into the shell, which could otherwise cross).
const RETURN_DELAY: Duration = Duration::from_millis(150);

pub struct Sockets {
    pub tcp: TcpListener,
    pub control: UnixListener,
}

struct ConnInfo {
    addr: IpAddr,
    phone: Option<String>,
    tx: Option<mpsc::Sender<ToConn>>,
}

struct Request {
    conn: u64,
    pin: String,
    addr: IpAddr,
    until: Instant,
}

struct Keyboard {
    client: u64,
    field: i64,
    value: Field,
}

struct Daemon {
    name: String,
    store: Store,
    phone_keys: Arc<RwLock<HashMap<String, [u8; 32]>>>,
    sink: Box<dyn InputSink>,
    speaker: Option<speaker::Link>,
    speaker_status: speaker::Status,
    /// The volume the remote's slider last asked for.
    slider: Option<f64>,
    shared: watch::Sender<Shared>,
    conns: HashMap<u64, ConnInfo>,
    request: Option<Request>,
    failed_at: Option<Instant>,
    clients: BTreeMap<u64, mpsc::Sender<String>>,
    keyboard: Option<Keyboard>,
    later: mpsc::UnboundedSender<u16>,
    /// Config::return_key: the phone's Return as Enter too.
    return_key: bool,
}

/// Addresses on this side of the router: loopback, private, link-local,
/// CGNAT, unique local (as big-fella-connect).
pub fn lan(ip: IpAddr) -> bool {
    match bf_daemon::canonical(ip) {
        IpAddr::V4(v4) => {
            v4.is_loopback()
                || v4.is_private()
                || v4.is_link_local()
                || (v4.octets()[0] == 100 && v4.octets()[1] & 0xc0 == 64)
        }
        IpAddr::V6(v6) => {
            v6.is_loopback() || (v6.segments()[0] & 0xfe00) == 0xfc00 || (v6.segments()[0] & 0xffc0) == 0xfe80
        }
    }
}

/// The phone port: both stacks if the system has IPv6, else IPv4.
pub async fn bind_tcp(port: u16) -> std::io::Result<TcpListener> {
    match TcpListener::bind((Ipv6Addr::UNSPECIFIED, port)).await {
        Ok(l) => Ok(l),
        Err(_) => TcpListener::bind((Ipv4Addr::UNSPECIFIED, port)).await,
    }
}

pub async fn run(cfg: Config, store: Store, sockets: Sockets, sink: Box<dyn InputSink>, ctx: Ctx) -> Result<()> {
    let phone_keys = ctx.phones.clone();
    let ctx = Arc::new(ctx);
    let (to_daemon, mut from_conns) = mpsc::channel::<ToDaemon>(256);
    let (shared, shared_rx) = watch::channel(Shared::default());
    let (control_tx, mut control_rx) = mpsc::channel::<ControlEvent>(64);
    let (later, mut later_rx) = mpsc::unbounded_channel::<u16>();

    let allowed = {
        let cfg = cfg.clone();
        move |uid| cfg.control_allowed(uid)
    };
    tokio::spawn(control::serve(sockets.control, allowed, control_tx));
    tokio::spawn(accept(sockets.tcp, ctx, to_daemon, shared_rx));

    let (speaker, mut speaker_rx) = if cfg.speaker.enabled {
        let (l, rx) = speaker::spawn(&cfg.speaker.socket);
        (Some(l), Some(rx))
    } else {
        (None, None)
    };

    let mut d = Daemon {
        name: cfg.display_name(),
        store,
        phone_keys,
        sink,
        speaker,
        speaker_status: speaker::Status { ready: false, volume: None },
        slider: None,
        shared,
        conns: HashMap::new(),
        request: None,
        failed_at: None,
        clients: BTreeMap::new(),
        keyboard: None,
        later,
        return_key: cfg.return_key,
    };
    d.sync_keys();
    let mut second = interval(Duration::from_secs(1));
    second.set_missed_tick_behavior(MissedTickBehavior::Delay);
    loop {
        tokio::select! {
            Some(ev) = from_conns.recv() => d.conn_event(ev),
            Some(ev) = control_rx.recv() => d.control_event(ev),
            Some(key) = later_rx.recv() => d.sink.press(key),
            Some(s) = async { speaker_rx.as_mut()?.recv().await } => {
                d.speaker_status = s;
                d.publish_shared();
            }
            _ = second.tick(), if d.request.is_some() => d.expire(),
        }
    }
}

async fn accept(
    listener: TcpListener,
    ctx: Arc<Ctx>,
    to_daemon: mpsc::Sender<ToDaemon>,
    shared: watch::Receiver<Shared>,
) {
    let counts: Arc<Mutex<HashMap<IpAddr, usize>>> = Arc::default();
    let mut backoff = bf_daemon::AcceptBackoff::new();
    let mut next = 0u64;
    loop {
        let (stream, peer): (_, SocketAddr) = match listener.accept().await {
            Ok(s) => {
                backoff.succeeded();
                s
            }
            Err(e) => {
                backoff.pause("phones", &e).await;
                continue;
            }
        };
        let ip = bf_daemon::canonical(peer.ip());
        if !lan(ip) {
            warn!("a connection from {ip}, not on the LAN: refused");
            continue;
        }
        {
            let mut c = counts.lock().unwrap_or_else(|e| e.into_inner());
            let total: usize = c.values().sum();
            let mine = c.entry(ip).or_default();
            if *mine >= MAX_PER_ADDRESS || total >= MAX_CONNECTIONS {
                warn!("too many connections ({ip}: {mine}, {total} in all): refused");
                continue;
            }
            *mine += 1;
        }
        next += 1;
        let (ctx, to_daemon, shared, counts) = (ctx.clone(), to_daemon.clone(), shared.clone(), counts.clone());
        tokio::spawn(async move {
            conn::serve(next, stream, ip, ctx, to_daemon, shared).await;
            let mut c = counts.lock().unwrap_or_else(|e| e.into_inner());
            if let Some(n) = c.get_mut(&ip) {
                *n -= 1;
                if *n == 0 {
                    c.remove(&ip);
                }
            }
        });
    }
}

fn now_secs() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_secs() as i64)
}

impl Daemon {
    fn sync_keys(&self) {
        if let Ok(mut k) = self.phone_keys.write() {
            *k = self.store.phones.values().filter_map(|p| Some((p.id.clone(), p.key()?))).collect();
        }
    }

    fn state(&self) -> Value {
        let now = Instant::now();
        let phones: Vec<Value> = self
            .store
            .phones
            .values()
            .map(|p| {
                let conn = self.conns.values().find(|c| c.phone.as_deref() == Some(&p.id));
                json!({"id": p.id, "name": p.name, "model": p.model, "paired_at": p.paired_at,
                       "connected": conn.is_some(), "address": conn.map(|c| c.addr.to_string())})
            })
            .collect();
        let request = self.request.as_ref().map(|r| {
            json!({"pin": r.pin, "address": r.addr.to_string(),
                   "seconds": r.until.saturating_duration_since(now).as_secs()})
        });
        json!({"state": {
            "name": self.name,
            "pairing": self.store.pairing,
            "phones": phones,
            "request": request,
            "keyboard": self.keyboard.is_some(),
            "remotes": self.conns.values().filter(|c| c.phone.is_some()).count(),
        }})
    }

    fn broadcast(&mut self, v: &Value) {
        let line = v.to_string();
        self.clients.retain(|_, tx| !matches!(tx.try_send(line.clone()), Err(mpsc::error::TrySendError::Closed(_))));
    }

    fn publish(&mut self) {
        let s = self.state();
        self.broadcast(&s);
    }

    fn publish_shared(&self) {
        let field = self.keyboard.as_ref().map(|k| k.value.clone());
        let volume = self.speaker_status.ready.then_some(self.speaker_status.volume).flatten().or(self.slider);
        self.shared.send_if_modified(|s| {
            let new = Shared { field, volume };
            let changed = *s != new;
            *s = new;
            changed
        });
    }

    fn close(&mut self, conn: u64) {
        if let Some(tx) = self.conns.get(&conn).and_then(|c| c.tx.clone()) {
            let _ = tx.try_send(ToConn::Close);
        }
    }

    fn conn_event(&mut self, ev: ToDaemon) {
        match ev {
            ToDaemon::PairStart { conn, addr, tx, reply } => {
                self.conns.entry(conn).or_insert(ConnInfo { addr, phone: None, tx: None }).tx = Some(tx);
                let answer = self.pair_start(conn, addr);
                let _ = reply.send(answer);
                self.publish();
            }
            ToDaemon::PairEnded { conn } => {
                if self.request.as_ref().is_some_and(|r| r.conn == conn) {
                    self.request = None;
                    self.failed_at = Some(Instant::now());
                    self.publish();
                }
            }
            ToDaemon::Paired { conn, phone, reply } => {
                let kept = self.paired(phone);
                if self.request.as_ref().is_some_and(|r| r.conn == conn) {
                    self.request = None;
                }
                let _ = reply.send(kept);
                self.publish();
            }
            ToDaemon::Verified { conn, id, addr, tx } => {
                self.conns.insert(conn, ConnInfo { addr, phone: Some(id), tx: Some(tx) });
                self.publish();
            }
            ToDaemon::Effects { conn, fx } => {
                for e in fx {
                    self.effect(conn, e);
                }
            }
            ToDaemon::Gone { conn } => {
                let had = self.conns.remove(&conn).is_some_and(|c| c.phone.is_some());
                let asked = self.request.as_ref().is_some_and(|r| r.conn == conn);
                if asked {
                    self.request = None;
                }
                if had || asked {
                    self.publish();
                }
            }
        }
    }

    fn pair_start(&mut self, conn: u64, addr: IpAddr) -> Result<String, u8> {
        if !self.store.pairing {
            info!("{addr} asks to pair; pairing new phones is off");
            return Err(tlv8::ERR_UNAVAILABLE);
        }
        if self.failed_at.is_some_and(|t| t.elapsed() < BACKOFF) {
            return Err(tlv8::ERR_BACKOFF);
        }
        if let Some(r) = &self.request
            && r.conn != conn
        {
            if r.addr != addr {
                info!("{addr} asks to pair while {} is: busy", r.addr);
                return Err(tlv8::ERR_BUSY);
            }
            // The same phone again (a new connection): this one instead.
            let old = r.conn;
            self.close(old);
        }
        let pin = pairing::new_pin();
        info!("{addr} asks to pair: the PIN is on the screen");
        self.request =
            Some(Request { conn, pin: pin.clone(), addr, until: Instant::now() + Duration::from_secs(PIN_SECONDS) });
        Ok(pin)
    }

    fn paired(&mut self, p: NewPhone) -> bool {
        let name = if p.name.trim().is_empty() { "iPhone".to_owned() } else { p.name.chars().take(64).collect() };
        let phone = Phone {
            id: p.id.clone(),
            name,
            model: p.model.chars().take(32).collect(),
            public_key: hex(&p.public_key),
            paired_at: now_secs(),
        };
        match self.store.add(phone.clone()) {
            Ok(()) => {
                info!("paired {} ({})", phone.name, phone.id);
                self.sync_keys();
                self.broadcast(&json!({"event": "paired", "phone": {"id": phone.id, "name": phone.name}}));
                true
            }
            Err(e) => {
                warn!("keeping the pairing: {e:#}");
                false
            }
        }
    }

    fn expire(&mut self) {
        if self.request.as_ref().is_some_and(|r| Instant::now() >= r.until) {
            if let Some(r) = self.request.take() {
                info!("{}: the PIN wasn't entered in time", r.addr);
                self.close(r.conn);
            }
            self.publish();
        }
    }

    fn effect(&mut self, conn: u64, e: Effect) {
        match e {
            Effect::Key { code, down } => self.sink.key(code, down),
            Effect::Press(code) => self.sink.press(code),
            Effect::Volume(up) => self.volume(up),
            Effect::SetVolume(v) => {
                let was = self.speaker_status.volume.or(self.slider).unwrap_or(0.5);
                self.slider = Some(v);
                if (v - was).abs() > 0.001 {
                    self.volume(v > was);
                }
                self.publish_shared();
            }
            Effect::Text(edit) => self.text(edit),
            Effect::About { name, model } => {
                let id = self.conns.get(&conn).and_then(|c| c.phone.clone());
                if let Some(p) = id.and_then(|id| self.store.phones.get(&id).cloned())
                    && ((p.name == "iPhone" && !name.trim().is_empty()) || (p.model.is_empty() && !model.is_empty()))
                {
                    let mut p = p;
                    if p.name == "iPhone" && !name.trim().is_empty() {
                        p.name = name.chars().take(64).collect();
                    }
                    if p.model.is_empty() {
                        p.model = model.chars().take(32).collect();
                    }
                    if self.store.add(p).is_ok() {
                        self.publish();
                    }
                }
            }
        }
    }

    fn volume(&mut self, up: bool) {
        match &self.speaker {
            Some(link) if self.speaker_status.ready => {
                link.send(if up { speaker::Cmd::VolumeUp } else { speaker::Cmd::VolumeDown })
            }
            // The volume keys: the shell's (KWin's global shortcuts), which
            // drive PipeWire when there's no speakerd.
            _ => self.sink.press(if up { KEY_VOLUMEUP } else { KEY_VOLUMEDOWN }),
        }
    }

    fn text(&mut self, mut edit: Edit) {
        if self.keyboard.is_none() {
            return;
        }
        let submit = match edit.insert.find(['\n', '\r']) {
            Some(i) => {
                edit.insert.truncate(i);
                true
            }
            None => false,
        };
        if !(edit.replace.is_none() && edit.delete == 0 && edit.insert.is_empty()) || submit {
            self.broadcast(&json!({"event": "text", "replace": edit.replace, "delete": edit.delete,
                                   "insert": edit.insert, "submit": submit}));
        }
        if submit && self.return_key {
            let later = self.later.clone();
            tokio::spawn(async move {
                tokio::time::sleep(RETURN_DELAY).await;
                let _ = later.send(KEY_ENTER);
            });
        }
    }

    fn control_event(&mut self, ev: ControlEvent) {
        match ev {
            ControlEvent::Connected { client, tx } => {
                let _ = tx.try_send(self.state().to_string());
                self.clients.insert(client, tx);
            }
            ControlEvent::Gone { client } => {
                self.clients.remove(&client);
                if self.keyboard.as_ref().is_some_and(|k| k.client == client) {
                    self.keyboard = None;
                    self.publish_shared();
                    self.publish();
                }
            }
            ControlEvent::Command { client, cmd } => {
                let name = cmd.get("cmd").and_then(Value::as_str).unwrap_or("").to_owned();
                let id = cmd.get("id").cloned();
                let result = self.command(client, &name, &cmd);
                let line = match result {
                    Ok(()) => id.map(|id| json!({"ok": true, "cmd": name, "id": id})),
                    Err(e) => Some(json!({"error": e, "cmd": name, "id": id})),
                };
                if let (Some(line), Some(tx)) = (line, self.clients.get(&client)) {
                    let _ = tx.try_send(line.to_string());
                }
            }
        }
    }

    fn command(&mut self, client: u64, name: &str, cmd: &Value) -> Result<(), String> {
        match name {
            "state" => {
                if let Some(tx) = self.clients.get(&client) {
                    let _ = tx.try_send(self.state().to_string());
                }
            }
            "pairing" => {
                let on = cmd.get("value").and_then(Value::as_bool).ok_or("value: true or false")?;
                self.store.set_pairing(on).map_err(|e| format!("{e:#}"))?;
                if !on && let Some(r) = self.request.take() {
                    self.close(r.conn);
                }
                self.publish();
            }
            "forget" => {
                let id = cmd.get("phone").and_then(Value::as_str).ok_or("phone: its id")?.to_owned();
                if !self.store.forget(&id).map_err(|e| format!("{e:#}"))? {
                    return Err("no such phone".into());
                }
                info!("forgot {id}");
                self.sync_keys();
                let gone: Vec<u64> = self
                    .conns
                    .iter()
                    .filter(|(_, c)| c.phone.as_deref() == Some(id.as_str()))
                    .map(|(k, _)| *k)
                    .collect();
                for c in gone {
                    self.close(c);
                }
                self.publish();
            }
            "cancel" => {
                if let Some(r) = self.request.take() {
                    info!("pairing {} cancelled on the TV", r.addr);
                    self.close(r.conn);
                    self.publish();
                }
            }
            "keyboard" => {
                let open = cmd.get("open").and_then(Value::as_bool).ok_or("open: true or false")?;
                if open {
                    let field = cmd.get("field").and_then(Value::as_i64).unwrap_or(0);
                    let text: String =
                        cmd.get("text").and_then(Value::as_str).unwrap_or("").chars().take(4096).collect();
                    let title: String =
                        cmd.get("title").and_then(Value::as_str).unwrap_or("").chars().take(64).collect();
                    match self.keyboard.as_mut() {
                        Some(k) if k.client == client && k.field == field => {
                            k.value.text = text;
                            k.value.title = title;
                        }
                        _ => {
                            let mut session = [0u8; 16];
                            rand::rngs::OsRng.fill_bytes(&mut session);
                            self.keyboard = Some(Keyboard { client, field, value: Field { session, text, title } });
                        }
                    }
                } else if self.keyboard.as_ref().is_some_and(|k| k.client == client) {
                    self.keyboard = None;
                }
                self.publish_shared();
                self.publish();
            }
            _ => return Err(format!("unknown command: {name}")),
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lan_addresses() {
        let ip = |s: &str| s.parse::<IpAddr>().unwrap();
        for ok in [
            "127.0.0.1",
            "192.168.1.5",
            "10.1.2.3",
            "172.16.0.1",
            "169.254.1.1",
            "100.64.1.1",
            "fe80::1",
            "fd00::1",
            "::1",
            "::ffff:192.168.1.9",
        ] {
            assert!(lan(ip(ok)), "{ok}");
        }
        for no in ["8.8.8.8", "100.128.0.1", "2001:db8::1", "::ffff:8.8.8.8"] {
            assert!(!lan(ip(no)), "{no}");
        }
    }
}
