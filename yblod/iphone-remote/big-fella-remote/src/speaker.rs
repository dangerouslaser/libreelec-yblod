//! speakerd's socket (docs/speakerd.md), as remote-bridged uses it for the
//! LG remote's volume (remote-bridged/src/speaker.rs, usersock.rs: the same
//! rules): the iPhone's volume buttons go there while speakerd is up and
//! has its speaker (connected, not in standby). The daemon falls back to
//! the volume keys otherwise, so they never go dead.
//!
//! speakerd is the user's service: its socket is in /run/user/UID. We
//! connect as root only to a socket its folder's owner made, and only if
//! the process at the other end is theirs.

use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::Value;
use tokio::io::{AsyncWriteExt, BufReader};
use tokio::net::UnixStream;
use tokio::sync::mpsc::{UnboundedReceiver, UnboundedSender, unbounded_channel};
use tokio::time::timeout;
use tracing::{debug, info};

const RUN_USER: &str = "/run/user";
const RETRY: Duration = Duration::from_secs(2);
const WRITE_TIMEOUT: Duration = Duration::from_secs(1);
const REPLY_LIMIT: bf_daemon::LineLimit = bf_daemon::LineLimit::new(64 * 1024).newline_counts();

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Cmd {
    VolumeUp,
    VolumeDown,
}

impl Cmd {
    fn line(self) -> &'static str {
        match self {
            Cmd::VolumeUp => r#"{"cmd": "volume_up"}"#,
            Cmd::VolumeDown => r#"{"cmd": "volume_down"}"#,
        }
    }
}

/// What speakerd said last: whether it can take the buttons, and the
/// volume (0-1) if it knows it.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Status {
    pub ready: bool,
    pub volume: Option<f64>,
}

pub fn status(state: &Value) -> Status {
    let ready = state.get("connected") == Some(&Value::Bool(true)) && state.get("power") != Some(&Value::Bool(false));
    let max = state.get("max_volume").and_then(Value::as_f64).filter(|m| *m > 0.0).unwrap_or(100.0);
    let volume = state.get("volume").and_then(Value::as_f64).map(|v| (v / max).clamp(0.0, 1.0));
    Status { ready, volume }
}

#[derive(Clone)]
pub struct Link {
    tx: UnboundedSender<Cmd>,
}

impl Link {
    pub fn send(&self, cmd: Cmd) {
        let _ = self.tx.send(cmd);
    }
}

/// Starts following speakerd: the receiver gets its status on every change.
pub fn spawn(socket: &str) -> (Link, UnboundedReceiver<Status>) {
    let (tx, cmds) = unbounded_channel();
    let (status_tx, status) = unbounded_channel();
    let socket = Some(socket.trim()).filter(|s| !s.is_empty()).map(PathBuf::from);
    tokio::spawn(run(socket, cmds, status_tx));
    (Link { tx }, status)
}

async fn run(socket: Option<PathBuf>, mut cmds: UnboundedReceiver<Cmd>, status_tx: UnboundedSender<Status>) {
    let gone = Status { ready: false, volume: None };
    let mut logged = false;
    loop {
        if let Some((path, uid)) = find(&socket, "speakerd.sock") {
            match connect(&path, uid).await {
                Ok(stream) => {
                    info!("speakerd at {}", path.display());
                    logged = false;
                    session(stream, &mut cmds, &status_tx).await;
                    info!("speakerd gone");
                    let _ = status_tx.send(gone);
                }
                Err(e) if !logged => {
                    debug!("speakerd at {}: {e}", path.display());
                    logged = true;
                }
                Err(_) => {}
            }
        }
        tokio::time::sleep(RETRY).await;
        while cmds.try_recv().is_ok() {} // too late for them
    }
}

async fn session(stream: UnixStream, cmds: &mut UnboundedReceiver<Cmd>, status_tx: &UnboundedSender<Status>) {
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut line = Vec::new();
    loop {
        tokio::select! {
            read = bf_daemon::read_line_with(&mut reader, &mut line, REPLY_LIMIT) => {
                if !matches!(read, Ok(true)) {
                    return;
                }
                let msg = serde_json::from_slice::<Value>(&line);
                line.clear();
                if let Ok(msg) = msg && let Some(state) = msg.get("state") {
                    let _ = status_tx.send(status(state));
                }
            }
            Some(cmd) = cmds.recv() => {
                let line = format!("{}\n", cmd.line());
                if !matches!(timeout(WRITE_TIMEOUT, writer.write_all(line.as_bytes())).await, Ok(Ok(()))) {
                    return;
                }
            }
        }
    }
}

/// The socket and the uid it must belong to: `socket` if given, else the
/// first user's /run/user/UID/`name`.
fn find(socket: &Option<PathBuf>, name: &str) -> Option<(PathBuf, u32)> {
    if let Some(path) = socket {
        return owner(path, None).map(|uid| (path.clone(), uid));
    }
    let mut uids: Vec<u32> =
        std::fs::read_dir(RUN_USER).ok()?.filter_map(|e| e.ok()?.file_name().to_str()?.parse().ok()).collect();
    uids.sort_unstable();
    uids.into_iter().find_map(|uid| {
        let path = Path::new(RUN_USER).join(uid.to_string()).join(name);
        owner(&path, Some(uid)).map(|uid| (path, uid))
    })
}

/// Whose socket `path` is, if it's fit to connect to as root: a socket (not
/// a symlink) owned by its folder's owner (not a symlink either), that's
/// `uid` if given.
fn owner(path: &Path, uid: Option<u32>) -> Option<u32> {
    use std::os::unix::fs::{FileTypeExt, MetadataExt};
    let socket = std::fs::symlink_metadata(path).ok()?;
    let dir = std::fs::symlink_metadata(path.parent()?).ok()?;
    let fit = socket.file_type().is_socket() && dir.is_dir() && socket.uid() == dir.uid();
    (fit && uid.is_none_or(|uid| uid == socket.uid())).then_some(socket.uid())
}

/// Connects to `path`, served by `uid` (SO_PEERCRED).
async fn connect(path: &Path, uid: u32) -> io::Result<UnixStream> {
    let stream = UnixStream::connect(path).await?;
    match stream.peer_cred()?.uid() {
        peer if peer == uid => Ok(stream),
        peer => Err(io::Error::other(format!("served by uid {peer}, not {uid}"))),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use tokio::io::AsyncBufReadExt;
    use tokio::net::UnixListener;

    use super::*;

    #[test]
    fn readiness_and_volume() {
        assert_eq!(
            status(&json!({"connected": true, "volume": 30, "max_volume": 60})),
            Status { ready: true, volume: Some(0.5) }
        );
        assert!(!status(&json!({"connected": true, "power": false})).ready);
        assert_eq!(status(&json!({"connected": false})), Status { ready: false, volume: None });
    }

    #[tokio::test]
    async fn follows_speakerd_and_sends_commands() {
        let dir = PathBuf::from(format!("/tmp/bfr-speaker-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("speakerd.sock");
        let listener = UnixListener::bind(&path).unwrap();
        let (link, mut status) = spawn(&path.to_string_lossy());
        let (sock, _) = listener.accept().await.unwrap();
        let (rd, mut wr) = sock.into_split();
        let mut rd = BufReader::new(rd).lines();
        wr.write_all(b"{\"state\": {\"connected\": true, \"volume\": 20}}\n").await.unwrap();
        let s = timeout(Duration::from_secs(2), status.recv()).await.unwrap().unwrap();
        assert_eq!(s, Status { ready: true, volume: Some(0.2) });
        link.send(Cmd::VolumeDown);
        assert_eq!(rd.next_line().await.unwrap().unwrap(), r#"{"cmd": "volume_down"}"#);
        drop((rd, wr));
        assert!(!timeout(Duration::from_secs(2), status.recv()).await.unwrap().unwrap().ready);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
