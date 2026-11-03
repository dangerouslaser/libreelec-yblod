//! One phone's connection: pair-setup or pair-verify in the clear, then
//! the sealed session. The daemon decides what needs deciding (whether a
//! phone may pair, the PIN, keeping a pairing) and gets what the session
//! does (keys, volume, typing).

use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, RwLock};
use std::time::Duration;

use tokio::io::AsyncWriteExt;
use tokio::net::TcpStream;
use tokio::net::tcp::OwnedWriteHalf;
use tokio::sync::{mpsc, oneshot, watch};
use tokio::time::{Instant, sleep_until, timeout};
use tracing::{debug, info, warn};

use crate::crypto::Channel;
use crate::frame::{self, Frame};
use crate::opack::{self, Value};
use crate::pairing::{self, NewPhone, Ours, Setup, Verify};
use crate::session::{self, Effect, Session, Shared};
use crate::tlv8::{self, Tlv};

/// To pair or verify: a phone that doesn't is hung up on. Pairing waits for
/// someone to read the PIN off the TV and type it.
const UNVERIFIED_LIMIT: Duration = Duration::from_secs(30);
const PAIRING_LIMIT: Duration = Duration::from_secs(120);
const WRITE_LIMIT: Duration = Duration::from_secs(5);
const TICK: Duration = Duration::from_millis(40);

/// What connections share.
pub struct Ctx {
    pub ours: Ours,
    pub home_key: u16,
    pub touch: crate::touch::Tuning,
    pub system_info: Value,
    /// Paired phones' keys, by identifier (the daemon keeps it current).
    pub phones: Arc<RwLock<HashMap<String, [u8; 32]>>>,
}

#[derive(Debug)]
pub enum ToDaemon {
    /// A phone asks to pair: the PIN to show, or the TLV8 error to refuse
    /// with.
    PairStart {
        conn: u64,
        addr: IpAddr,
        tx: mpsc::Sender<ToConn>,
        reply: oneshot::Sender<Result<String, u8>>,
    },
    /// The wrong PIN, or the phone gave up.
    PairEnded {
        conn: u64,
    },
    /// Paired: keep it (false: couldn't).
    Paired {
        conn: u64,
        phone: NewPhone,
        reply: oneshot::Sender<bool>,
    },
    Verified {
        conn: u64,
        id: String,
        addr: IpAddr,
        tx: mpsc::Sender<ToConn>,
    },
    Effects {
        conn: u64,
        fx: Vec<Effect>,
    },
    Gone {
        conn: u64,
    },
}

#[derive(Debug)]
pub enum ToConn {
    Close,
}

struct Conn {
    id: u64,
    addr: IpAddr,
    ctx: Arc<Ctx>,
    daemon: mpsc::Sender<ToDaemon>,
    wr: OwnedWriteHalf,
    verified: Arc<AtomicBool>,
    setup: Option<Setup>,
    verify: Option<Verify>,
    channels: Option<(Channel, Channel)>,
    session: Option<Session>,
    deadline: Option<Instant>,
}

pub async fn serve(
    id: u64,
    stream: TcpStream,
    addr: IpAddr,
    ctx: Arc<Ctx>,
    daemon: mpsc::Sender<ToDaemon>,
    mut shared: watch::Receiver<Shared>,
) {
    let _ = stream.set_nodelay(true);
    let (mut rd, wr) = stream.into_split();
    let verified = Arc::new(AtomicBool::new(false));
    // Frames are read in a task of their own (a read cut short by select!
    // would lose bytes).
    let (frames_tx, mut frames) = mpsc::channel::<Frame>(64);
    let reader = {
        let verified = verified.clone();
        tokio::spawn(async move {
            loop {
                let max = if verified.load(Ordering::Relaxed) { frame::MAX_VERIFIED } else { frame::MAX_UNVERIFIED };
                match frame::read(&mut rd, max).await {
                    Ok(Some(f)) => {
                        if frames_tx.send(f).await.is_err() {
                            break;
                        }
                    }
                    Ok(None) => break,
                    Err(e) => {
                        debug!("connection {id}: {e}");
                        break;
                    }
                }
            }
        })
    };
    let (tx, mut cmds) = mpsc::channel::<ToConn>(4);
    let mut c = Conn {
        id,
        addr,
        ctx,
        daemon: daemon.clone(),
        wr,
        verified,
        setup: None,
        verify: None,
        channels: None,
        session: None,
        deadline: Some(Instant::now() + UNVERIFIED_LIMIT),
    };
    let start = std::time::Instant::now();
    let now = || start.elapsed().as_millis() as u64;
    let mut next_tick = Instant::now();
    loop {
        let ticking = c.session.as_ref().is_some_and(Session::wants_tick);
        let verified = c.session.is_some();
        tokio::select! {
            f = frames.recv() => {
                let Some(f) = f else { break };
                let sh = shared.borrow().clone();
                match c.frame(f, &sh, now(), &tx).await {
                    Ok(true) => {}
                    Ok(false) => break,
                    Err(e) => {
                        debug!("connection {id}: {e}");
                        break;
                    }
                }
                if ticking != c.session.as_ref().is_some_and(Session::wants_tick) {
                    next_tick = Instant::now() + TICK;
                }
            }
            changed = shared.changed(), if verified => {
                if changed.is_err() {
                    break;
                }
                let sh = shared.borrow_and_update().clone();
                let msgs = c.session.as_mut().map(|s| s.field_changed(&sh)).unwrap_or_default();
                if c.send(&msgs).await.is_err() {
                    break;
                }
            }
            cmd = cmds.recv() => match cmd {
                Some(ToConn::Close) | None => break,
            },
            _ = sleep_until(next_tick), if ticking => {
                next_tick += TICK;
                let fx = c.session.as_mut().map(|s| s.tick(now())).unwrap_or_default();
                if !fx.is_empty() && daemon.send(ToDaemon::Effects { conn: id, fx }).await.is_err() {
                    break;
                }
            }
            _ = sleep_until(c.deadline.unwrap_or_else(Instant::now)), if c.deadline.is_some() => {
                info!("connection {id} ({addr}): neither paired nor verified in time");
                break;
            }
        }
    }
    reader.abort();
    if c.setup.is_some() {
        let _ = daemon.send(ToDaemon::PairEnded { conn: id }).await;
    }
    if let Some(s) = c.session.as_mut() {
        let fx = s.release_all();
        if !fx.is_empty() {
            let _ = daemon.send(ToDaemon::Effects { conn: id, fx }).await;
        }
    }
    let _ = daemon.send(ToDaemon::Gone { conn: id }).await;
}

fn pd(tlv: &Tlv) -> Value {
    Value::dict([("_pd", Value::Data(tlv.encode()))])
}

impl Conn {
    async fn write(&mut self, bytes: &[u8]) -> std::io::Result<()> {
        timeout(WRITE_LIMIT, self.wr.write_all(bytes)).await.map_err(|_| std::io::ErrorKind::TimedOut)?
    }

    async fn send(&mut self, msgs: &[Value]) -> std::io::Result<()> {
        let Some((out, _)) = self.channels.as_mut() else { return Ok(()) };
        let bytes: Vec<u8> = msgs.iter().flat_map(|m| frame::encode_sealed(out, m)).collect();
        if bytes.is_empty() { Ok(()) } else { self.write(&bytes).await }
    }

    /// One frame. Ok(false): hang up.
    async fn frame(&mut self, f: Frame, shared: &Shared, now: u64, tx: &mpsc::Sender<ToConn>) -> std::io::Result<bool> {
        if let Some((_, input)) = self.channels.as_mut() {
            if f.kind != frame::E_OPACK {
                debug!("connection {}: frame {:#x} after verify; ignored", self.id, f.kind);
                return Ok(true);
            }
            let Some(msg) = frame::open_sealed(input, &f) else {
                warn!("connection {}: a frame that doesn't open; hanging up", self.id);
                return Ok(false);
            };
            let Some(s) = self.session.as_mut() else { return Ok(false) };
            let (out, fx) = s.handle(&msg, shared, now);
            self.send(&out).await?;
            if !fx.is_empty() && self.daemon.send(ToDaemon::Effects { conn: self.id, fx }).await.is_err() {
                return Ok(false);
            }
            return Ok(true);
        }
        let tlv = opack::decode(&f.payload)
            .ok()
            .and_then(|m| m.get("_pd").and_then(Value::as_data).and_then(Tlv::parse))
            .unwrap_or_default();
        let step = tlv.int(tlv8::STATE).unwrap_or(0);
        match (f.kind, step) {
            (frame::PS_START | frame::PS_NEXT, 1) => self.pair_m1(&tlv, tx).await,
            (frame::PS_NEXT, 3) => {
                let Some(setup) = self.setup.as_mut() else { return Ok(false) };
                let m4 = match setup.m3(&tlv) {
                    Ok(m4) => m4,
                    Err(m4) => {
                        info!("connection {} ({}): the wrong PIN", self.id, self.addr);
                        self.setup = None;
                        let _ = self.daemon.send(ToDaemon::PairEnded { conn: self.id }).await;
                        m4
                    }
                };
                self.write(&frame::encode_plain(frame::PS_NEXT, &pd(&m4))).await?;
                Ok(true)
            }
            (frame::PS_NEXT, 5) => {
                let Some(setup) = self.setup.take() else { return Ok(false) };
                match setup.m5(&self.ctx.ours, &tlv) {
                    Ok((m6, phone)) => {
                        let (reply, kept) = oneshot::channel();
                        let _ = self.daemon.send(ToDaemon::Paired { conn: self.id, phone, reply }).await;
                        let m6 =
                            if kept.await.unwrap_or(false) { m6 } else { pairing::error(6, tlv8::ERR_UNAVAILABLE) };
                        self.write(&frame::encode_plain(frame::PS_NEXT, &pd(&m6))).await?;
                    }
                    Err(m6) => {
                        warn!("connection {} ({}): pair-setup's last step failed", self.id, self.addr);
                        let _ = self.daemon.send(ToDaemon::PairEnded { conn: self.id }).await;
                        self.write(&frame::encode_plain(frame::PS_NEXT, &pd(&m6))).await?;
                    }
                }
                // Back to the time limit for verifying.
                self.deadline = Some(Instant::now() + UNVERIFIED_LIMIT);
                Ok(true)
            }
            (frame::PV_START | frame::PV_NEXT, 1) => {
                let Some((v, m2)) = Verify::start(&self.ctx.ours, &tlv) else { return Ok(false) };
                self.verify = Some(v);
                self.write(&frame::encode_plain(frame::PV_NEXT, &pd(&m2))).await?;
                Ok(true)
            }
            (frame::PV_NEXT, 3) => {
                let Some(v) = self.verify.take() else { return Ok(false) };
                let known = |id: &str| self.ctx.phones.read().ok().and_then(|p| p.get(id).copied());
                match v.finish(&tlv, known) {
                    Ok((m4, phone, keys)) => {
                        self.write(&frame::encode_plain(frame::PV_NEXT, &pd(&m4))).await?;
                        self.channels = Some((Channel::new(&keys.send), Channel::new(&keys.receive)));
                        self.session = Some(Session::new(session::Config {
                            home_key: self.ctx.home_key,
                            touch: self.ctx.touch,
                            system_info: self.ctx.system_info.clone(),
                        }));
                        self.verified.store(true, Ordering::Relaxed);
                        self.deadline = None;
                        info!("connection {} ({}): {phone} verified", self.id, self.addr);
                        let msg = ToDaemon::Verified { conn: self.id, id: phone, addr: self.addr, tx: tx.clone() };
                        Ok(self.daemon.send(msg).await.is_ok())
                    }
                    Err(m4) => {
                        // Not paired (or another key): the phone pairs next.
                        info!("connection {} ({}): not a paired phone", self.id, self.addr);
                        self.write(&frame::encode_plain(frame::PV_NEXT, &pd(&m4))).await?;
                        Ok(true)
                    }
                }
            }
            (kind, step) => {
                debug!("connection {}: frame {kind:#x} step {step} before verify; hanging up", self.id);
                Ok(false)
            }
        }
    }

    async fn pair_m1(&mut self, tlv: &Tlv, tx: &mpsc::Sender<ToConn>) -> std::io::Result<bool> {
        // iOS 18 tries a transient pairing on a second connection after a
        // failed HomeKit-keyed verify: closing it is enough
        // (CompanionGames #11).
        if tlv.int(tlv8::FLAGS).is_some_and(|f| f & tlv8::FLAG_TRANSIENT != 0) {
            debug!("connection {}: a transient pairing; hanging up", self.id);
            return Ok(false);
        }
        let (reply, answer) = oneshot::channel();
        if self
            .daemon
            .send(ToDaemon::PairStart { conn: self.id, addr: self.addr, tx: tx.clone(), reply })
            .await
            .is_err()
        {
            return Ok(false);
        }
        let m2 = match answer.await {
            Ok(Ok(pin)) => {
                let (setup, m2) = Setup::start(&pin);
                self.setup = Some(setup);
                self.deadline = Some(Instant::now() + PAIRING_LIMIT);
                m2
            }
            Ok(Err(code)) => pairing::error(2, code),
            Err(_) => return Ok(false),
        };
        let mut msg = pd(&m2);
        msg.set("_pwTy", Value::Int(1));
        self.write(&frame::encode_plain(frame::PS_NEXT, &msg)).await?;
        Ok(true)
    }
}
