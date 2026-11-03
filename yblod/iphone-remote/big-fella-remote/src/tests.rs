//! The daemon end to end: a phone (pairing.rs's phone side, over TCP) and
//! a home screen (the control socket), keys into a recorder. pyatv plays
//! the phone against the real binary in tests/e2e.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, RwLock};
use std::time::Duration;

use ed25519_dalek::SigningKey;
use serde_json::{Value as Json, json};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{TcpStream, UnixStream};
use tokio::time::timeout;

use crate::config::Config;
use crate::crypto::Channel;
use crate::frame::{self, Frame};
use crate::input::Recorder;
use crate::keys::*;
use crate::opack::Value;
use crate::pairing::phone::{self, Identity};
use crate::tlv8::{self, Tlv};
use crate::{advertise, conn, control, daemon, pairing, rti, store};

const T: Duration = Duration::from_secs(5);

struct Tv {
    port: u16,
    keys: Recorder,
    control: PathBuf,
    dir: PathBuf,
}

async fn start(name: &str) -> Tv {
    let dir = store::tests::scratch(name);
    let cfg = Config {
        state_dir: dir.join("state"),
        control_socket: dir.join("control.sock"),
        control_uids: vec![my_uid()],
        advertise: false,
        uinput: false,
        speaker: crate::config::Speaker { enabled: false, socket: String::new() },
        ..Config::default()
    };
    let store = store::Store::open(&cfg.state_dir, true).unwrap();
    let tcp = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = tcp.local_addr().unwrap().port();
    let control = control::bind(&cfg.control_socket).unwrap();
    let ids = advertise::Ids::new(&store.id, &store.key.verifying_key().to_bytes());
    let ctx = conn::Ctx {
        ours: pairing::Ours {
            id: store.id.clone(),
            key: store.key.clone(),
            name: "big-fella".into(),
            model: cfg.model.clone(),
        },
        home_key: cfg.home_key,
        touch: cfg.touch(),
        system_info: advertise::system_info(&ids, "big-fella", &cfg.model, port),
        phones: Arc::new(RwLock::new(HashMap::new())),
    };
    let keys = Recorder::default();
    let sink = Box::new(keys.clone());
    let control_path = cfg.control_socket.clone();
    tokio::spawn(daemon::run(cfg, store, daemon::Sockets { tcp, control }, sink, ctx));
    Tv { port, keys, control: control_path, dir }
}

/// Our uid (the control socket lets only those it's told in).
fn my_uid() -> u32 {
    use std::os::unix::fs::MetadataExt;
    let p = std::env::temp_dir().join(format!("bfr-uid-{}", std::process::id()));
    std::fs::write(&p, b"").unwrap();
    let uid = std::fs::metadata(&p).unwrap().uid();
    let _ = std::fs::remove_file(&p);
    uid
}

/// The home screen.
struct Shell {
    lines: tokio::io::Lines<BufReader<tokio::net::unix::OwnedReadHalf>>,
    w: tokio::net::unix::OwnedWriteHalf,
    state: Json,
}

impl Shell {
    async fn connect(path: &PathBuf) -> Self {
        let (r, w) = UnixStream::connect(path).await.unwrap().into_split();
        let mut s = Self { lines: BufReader::new(r).lines(), w, state: Json::Null };
        s.next(|m| m.get("state").is_some()).await;
        s
    }

    async fn send(&mut self, v: Json) {
        self.w.write_all(format!("{v}\n").as_bytes()).await.unwrap();
    }

    /// Reads till a line `pred` likes (keeping the state up to date).
    async fn next(&mut self, pred: impl Fn(&Json) -> bool) -> Json {
        timeout(T, async {
            loop {
                let line = self.lines.next_line().await.unwrap().unwrap();
                let v: Json = serde_json::from_str(&line).unwrap();
                if let Some(s) = v.get("state") {
                    self.state = s.clone();
                }
                if pred(&v) {
                    return v;
                }
            }
        })
        .await
        .expect("the control socket said nothing of the kind")
    }
}

/// A phone.
struct Phone {
    s: TcpStream,
    me: Identity,
    channels: Option<(Channel, Channel)>,
    x: i64,
}

impl Phone {
    async fn connect(port: u16, me: Identity) -> Self {
        Self { s: TcpStream::connect(("127.0.0.1", port)).await.unwrap(), me, channels: None, x: 0 }
    }

    async fn auth(&mut self, kind: u8, tlv: &Tlv) -> Option<Tlv> {
        let msg = Value::dict([("_pd", Value::Data(tlv.encode())), ("_pwTy", Value::Int(1))]);
        frame::write(&mut self.s, &frame::encode_plain(kind, &msg)).await.ok()?;
        let f = timeout(T, frame::read(&mut self.s, 1 << 20)).await.ok()?.ok()??;
        Tlv::parse(crate::opack::decode(&f.payload).ok()?.get("_pd")?.as_data()?)
    }

    async fn pair(&mut self, shell: &mut Shell, pin: Option<&str>) -> Result<(String, [u8; 32]), Tlv> {
        let m2 = self.auth(frame::PS_START, &phone::m1_setup()).await.unwrap();
        if m2.get(tlv8::ERROR).is_some() {
            return Err(m2);
        }
        let shown = shell.next(|m| m["state"]["request"].is_object()).await;
        let shown = shown["state"]["request"]["pin"].as_str().unwrap().to_owned();
        let (m3, srp) = phone::m3(&m2, pin.unwrap_or(&shown)).unwrap();
        let m4 = self.auth(frame::PS_NEXT, &m3).await.unwrap();
        if m4.get(tlv8::ERROR).is_some() {
            return Err(m4);
        }
        let m5 = phone::m5(&self.me, &srp, &m4).unwrap();
        let m6 = self.auth(frame::PS_NEXT, &m5).await.unwrap();
        phone::finish_setup(&srp, &m6).ok_or(m6)
    }

    async fn verify(&mut self, tv: Option<(&str, [u8; 32])>) -> bool {
        let (mut v, m1) = phone::m1_verify();
        let m2 = self.auth(frame::PV_START, &m1).await.unwrap();
        let (m3, keys) = phone::m3_verify(&self.me, &mut v, &m2, tv).unwrap();
        let m4 = self.auth(frame::PV_NEXT, &m3).await.unwrap();
        if m4.get(tlv8::ERROR).is_some() {
            return false;
        }
        self.channels = Some((Channel::new(&keys.send), Channel::new(&keys.receive)));
        true
    }

    async fn send(&mut self, name: &str, kind: i64, content: Value) {
        self.x += 1;
        let msg = Value::dict([
            ("_i", Value::str(name)),
            ("_t", Value::Int(kind)),
            ("_x", Value::Int(self.x)),
            ("_c", content),
        ]);
        let (out, _) = self.channels.as_mut().unwrap();
        let bytes = frame::encode_sealed(out, &msg);
        frame::write(&mut self.s, &bytes).await.unwrap();
    }

    /// Reads messages till one `pred` likes.
    async fn recv(&mut self, pred: impl Fn(&Value) -> bool) -> Value {
        timeout(T, async {
            loop {
                let f: Frame = frame::read(&mut self.s, 1 << 20).await.unwrap().expect("hung up on");
                let (_, input) = self.channels.as_mut().unwrap();
                let m = frame::open_sealed(input, &f).unwrap();
                if pred(&m) {
                    return m;
                }
            }
        })
        .await
        .expect("the TV said nothing of the kind")
    }

    async fn request(&mut self, name: &str, content: Value) -> Value {
        self.send(name, 2, content).await;
        let x = self.x;
        self.recv(|m| m.get("_x") == Some(&Value::Int(x)) && m.get("_t") == Some(&Value::Int(3))).await
    }

    async fn hung_up(&mut self) -> bool {
        let mut b = [0u8; 1];
        matches!(timeout(T, tokio::io::AsyncReadExt::read(&mut self.s, &mut b)).await, Ok(Ok(0) | Err(_)))
    }
}

fn me(n: u8) -> Identity {
    Identity { id: format!("PHONE-{n}"), key: SigningKey::from_bytes(&[n; 32]), name: format!("iPhone {n}") }
}

async fn settle(keys: &Recorder, n: usize) -> Vec<(u16, bool)> {
    for _ in 0..100 {
        if keys.0.lock().unwrap().len() >= n {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    std::mem::take(&mut *keys.0.lock().unwrap())
}

#[tokio::test]
async fn pair_verify_and_drive() {
    let tv = start("e2e").await;
    let mut shell = Shell::connect(&tv.control).await;
    assert_eq!(shell.state["pairing"], json!(true));

    // Not paired: verify says so.
    let mut p = Phone::connect(tv.port, me(1)).await;
    assert!(!p.verify(None).await);

    // Pairing with the PIN on the screen.
    let mut p = Phone::connect(tv.port, me(1)).await;
    let (tv_id, tv_key) = p.pair(&mut shell, None).await.expect("paired");
    let paired = shell.next(|m| m["event"] == "paired").await;
    assert_eq!(paired["phone"]["name"], "iPhone 1");
    shell.next(|m| m["state"]["request"].is_null() && m["state"]["phones"][0]["id"] == "PHONE-1").await;

    // Again, as the phone does: verify, then the remote.
    let mut p = Phone::connect(tv.port, me(1)).await;
    assert!(p.verify(Some((&tv_id, tv_key))).await);
    shell.next(|m| m["state"]["phones"][0]["connected"] == true).await;
    let info = p.request("_systemInfo", Value::dict([("name", Value::str("Kitchen iPhone"))])).await;
    assert_eq!(info.get("_c").and_then(|c| c.get("model")), Some(&Value::str("AppleTV5,3")));
    p.request("_sessionStart", Value::dict([("_srvT", Value::str("com.apple.tvremoteservices"))])).await;
    p.request("_touchStart", Value::Dict(vec![])).await;
    for (code, state) in [(5, 1), (5, 2), (7, 1), (7, 2)] {
        p.request("_hidC", Value::dict([("_hBtS", Value::Int(state)), ("_hidC", Value::Int(code))])).await;
    }
    for (ph, x) in [(1, 300), (2, 400), (2, 500), (4, 500)] {
        p.send("_hidT", 1, Value::dict([("_tPh", Value::Int(ph)), ("_cx", Value::Int(x)), ("_cy", Value::Int(500))]))
            .await;
    }
    let keys = settle(&tv.keys, 6).await;
    assert_eq!(
        keys,
        [(KEY_ESC, true), (KEY_ESC, false), (172, true), (172, false), (KEY_RIGHT, true), (KEY_RIGHT, false)]
    );
    // _systemInfo's name replaced the placeholder? (pairing gave one: kept.)
    assert_eq!(shell.state["phones"][0]["name"], "iPhone 1");

    // The keyboard: the shell offers a field; the phone hears and types.
    shell.send(json!({"cmd": "keyboard", "open": true, "field": 1, "text": "ab", "title": "Search"})).await;
    let started = p.recv(|m| m.get("_i") == Some(&Value::str("_tiStarted"))).await;
    let data = started.get("_c").and_then(|c| c.get("_tiD")).and_then(Value::as_data).unwrap();
    let (session, text) = rti::read_started(data).unwrap();
    assert_eq!(text, "ab");
    let ops = rti::operations(&session, None, 1, "çd\n");
    p.send("_tiC", 1, Value::dict([("_tiV", Value::Int(1)), ("_tiD", Value::Data(ops))])).await;
    let t = shell.next(|m| m["event"] == "text").await;
    assert_eq!((t["delete"].clone(), t["insert"].clone(), t["submit"].clone()), (json!(1), json!("çd"), json!(true)));
    // The Return: Enter, a moment after.
    assert_eq!(settle(&tv.keys, 2).await, [(KEY_ENTER, true), (KEY_ENTER, false)]);
    shell.send(json!({"cmd": "keyboard", "open": false})).await;
    p.recv(|m| m.get("_i") == Some(&Value::str("_tiStopped"))).await;

    // Volume without speakerd: the volume keys.
    p.request("_hidC", Value::dict([("_hBtS", Value::Int(1)), ("_hidC", Value::Int(8))])).await;
    p.request("_hidC", Value::dict([("_hBtS", Value::Int(2)), ("_hidC", Value::Int(8))])).await;
    assert_eq!(settle(&tv.keys, 2).await, [(KEY_VOLUMEUP, true), (KEY_VOLUMEUP, false)]);

    // A held button and the phone gone: it goes up.
    p.request("_hidC", Value::dict([("_hBtS", Value::Int(1)), ("_hidC", Value::Int(1))])).await;
    drop(p);
    assert_eq!(settle(&tv.keys, 2).await, [(KEY_UP, true), (KEY_UP, false)]);

    // Forgotten in Settings: hung up on, and refused.
    let mut p = Phone::connect(tv.port, me(1)).await;
    assert!(p.verify(Some((&tv_id, tv_key))).await);
    shell.next(|m| m["state"]["remotes"] == 1).await;
    shell.send(json!({"cmd": "forget", "phone": "PHONE-1", "id": 3})).await;
    shell.next(|m| m["ok"] == true && m["id"] == 3).await;
    assert!(p.hung_up().await);
    let mut p = Phone::connect(tv.port, me(1)).await;
    assert!(!p.verify(Some((&tv_id, tv_key))).await);
    let _ = std::fs::remove_dir_all(&tv.dir);
}

#[tokio::test]
async fn pairing_refusals() {
    let tv = start("refusals").await;
    let mut shell = Shell::connect(&tv.control).await;

    // The wrong PIN: refused, the PIN goes from the screen.
    let mut p = Phone::connect(tv.port, me(2)).await;
    let shown = {
        let m2 = p.auth(frame::PS_START, &phone::m1_setup()).await.unwrap();
        let s = shell.next(|m| m["state"]["request"].is_object()).await;
        let pin = s["state"]["request"]["pin"].as_str().unwrap().to_owned();
        let wrong = format!("{:04}", (pin.parse::<u32>().unwrap() + 1) % 10_000);
        let (m3, _) = phone::m3(&m2, &wrong).unwrap();
        let m4 = p.auth(frame::PS_NEXT, &m3).await.unwrap();
        assert_eq!(m4.get(tlv8::ERROR), Some(&[tlv8::ERR_AUTHENTICATION][..]));
        pin
    };
    shell.next(|m| m["state"]["request"].is_null()).await;
    // Straight away again: back off.
    let mut q = Phone::connect(tv.port, me(2)).await;
    let m2 = q.auth(frame::PS_START, &phone::m1_setup()).await.unwrap();
    assert_eq!(m2.get(tlv8::ERROR), Some(&[tlv8::ERR_BACKOFF][..]));
    assert!(!shown.is_empty());

    // Pairing turned off in Settings.
    shell.send(json!({"cmd": "pairing", "value": false})).await;
    shell.next(|m| m["state"]["pairing"] == false).await;
    tokio::time::sleep(Duration::from_millis(3100)).await;
    let mut p = Phone::connect(tv.port, me(3)).await;
    let m2 = p.auth(frame::PS_START, &phone::m1_setup()).await.unwrap();
    assert_eq!(m2.get(tlv8::ERROR), Some(&[tlv8::ERR_UNAVAILABLE][..]));

    // On again; cancelled from the TV: the phone's hung up on.
    shell.send(json!({"cmd": "pairing", "value": true})).await;
    let mut p = Phone::connect(tv.port, me(3)).await;
    p.auth(frame::PS_START, &phone::m1_setup()).await.unwrap();
    shell.next(|m| m["state"]["request"].is_object()).await;
    shell.send(json!({"cmd": "cancel"})).await;
    shell.next(|m| m["state"]["request"].is_null()).await;
    assert!(p.hung_up().await);

    // A transient pairing (iOS 18's second connection): hung up on.
    let mut p = Phone::connect(tv.port, me(4)).await;
    let m1 = phone::m1_setup().with(tlv8::FLAGS, &[0x10]);
    assert!(p.auth(frame::PS_START, &m1).await.is_none());

    // Junk instead of frames: hung up on.
    let mut p = Phone::connect(tv.port, me(4)).await;
    p.s.write_all(&[0xff, 0xff, 0xff, 0xff, 1, 2, 3]).await.unwrap();
    assert!(p.hung_up().await);
    let _ = std::fs::remove_dir_all(&tv.dir);
}
