//! The control socket: how the home screen (and tests) see the paired
//! iPhones, show the pairing PIN, offer the phone's keyboard and get its
//! typing. JSON lines both ways, like big-fella-connect's (README: "The
//! control socket" lists the messages).
//!
//! Only root and the people's accounts may connect (the socket's peer
//! credentials: Config::control_allowed); at most MAX_CLIENTS at once,
//! lines of at most MAX_LINE bytes.

use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;

use anyhow::{Context, Result};
use bf_daemon::AcceptBackoff;
use serde_json::Value;
use tokio::io::{AsyncWriteExt, BufReader};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::mpsc;
use tracing::{debug, info, warn};

pub const MAX_CLIENTS: usize = 8;
pub const MAX_LINE: usize = 64 * 1024;
const OUT_QUEUE: usize = 256;

#[derive(Debug)]
pub enum ControlEvent {
    Connected { client: u64, tx: mpsc::Sender<String> },
    Command { client: u64, cmd: Value },
    Gone { client: u64 },
}

/// The socket, made afresh (an old one from a crash is removed), open to
/// every local user: who may stay is decided per connection.
pub fn bind(path: &Path) -> Result<UnixListener> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).with_context(|| format!("creating {}", dir.display()))?;
    }
    let _ = std::fs::remove_file(path);
    let listener = UnixListener::bind(path).with_context(|| format!("listening on {}", path.display()))?;
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o666))?;
    Ok(listener)
}

pub async fn serve(listener: UnixListener, allowed: impl Fn(u32) -> bool, events: mpsc::Sender<ControlEvent>) {
    let count = Arc::new(AtomicUsize::new(0));
    let mut next = 0u64;
    let mut backoff = AcceptBackoff::new();
    loop {
        let sock = match listener.accept().await {
            Ok((s, _)) => {
                backoff.succeeded();
                s
            }
            Err(e) => {
                backoff.pause("control socket", &e).await;
                continue;
            }
        };
        let uid = match sock.peer_cred() {
            Ok(c) => c.uid(),
            Err(e) => {
                warn!("control socket: no peer credentials: {e}");
                continue;
            }
        };
        if !allowed(uid) {
            warn!("control socket: uid {uid} may not use it");
            continue;
        }
        if count.load(Ordering::Relaxed) >= MAX_CLIENTS {
            warn!("control socket: too many clients");
            continue;
        }
        count.fetch_add(1, Ordering::Relaxed);
        next += 1;
        let (events, count) = (events.clone(), count.clone());
        let client = next;
        debug!("control client {client} (uid {uid})");
        tokio::spawn(async move {
            client_loop(client, sock, events).await;
            count.fetch_sub(1, Ordering::Relaxed);
        });
    }
}

async fn client_loop(client: u64, sock: UnixStream, events: mpsc::Sender<ControlEvent>) {
    let (read, mut write) = sock.into_split();
    let mut read = BufReader::new(read);
    let (tx, mut rx) = mpsc::channel::<String>(OUT_QUEUE);
    if events.send(ControlEvent::Connected { client, tx }).await.is_err() {
        return;
    }
    let mut line = Vec::new();
    loop {
        tokio::select! {
            // Cancel-safe: a line cut by the other branch carries on.
            got = bf_daemon::read_line(&mut read, &mut line, MAX_LINE) => match got {
                Ok(true) => {
                    let cmd = serde_json::from_slice::<Value>(&line);
                    line.clear();
                    let Ok(cmd) = cmd else {
                        debug!("control client {client}: not JSON");
                        continue;
                    };
                    if events.send(ControlEvent::Command { client, cmd }).await.is_err() {
                        break;
                    }
                }
                Ok(false) => break,
                Err(e) => {
                    info!("control client {client}: {e}");
                    break;
                }
            },
            out = rx.recv() => match out {
                Some(mut l) => {
                    l.push('\n');
                    let w = tokio::time::timeout(Duration::from_secs(5), write.write_all(l.as_bytes()));
                    if !matches!(w.await, Ok(Ok(()))) {
                        break;
                    }
                }
                None => break,
            },
        }
    }
    let _ = events.send(ControlEvent::Gone { client }).await;
}
