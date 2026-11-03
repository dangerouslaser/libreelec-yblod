//! big-fella-remote-kodi: Kodi as big-fella-remote's home screen (the
//! pairing PIN and the phone's keyboard; src/kodi.rs). It connects to the
//! daemon's control socket and to Kodi's JSON-RPC, and keeps trying either
//! while it's away.
//!
//!   big-fella-remote-kodi [--control PATH] [--kodi HOST:PORT]

use std::time::Duration;

use anyhow::{Context, Result, bail};
use big_fella_remote::kodi::{Bridge, Out, split_messages};
use serde_json::Value;
use tokio::io::{AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::{TcpStream, UnixStream};
use tracing::{debug, info, warn};

const MAX_LINE: usize = 64 * 1024;
/// Kodi's messages: a whole library listing is never asked for, so this is
/// plenty; past it the buffer is dropped.
const MAX_KODI: usize = 4 << 20;
const RETRY: Duration = Duration::from_secs(3);

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    bf_daemon::init_tracing();
    let (control, kodi) = args()?;
    info!("control socket {control}, Kodi {kodi}");
    loop {
        match run(&control, &kodi).await {
            Ok(()) => info!("a connection closed; again in {}s", RETRY.as_secs()),
            Err(e) => debug!("{e:#}; again in {}s", RETRY.as_secs()),
        }
        tokio::time::sleep(RETRY).await;
    }
}

async fn run(control: &str, kodi: &str) -> Result<()> {
    let ctl = UnixStream::connect(control).await.with_context(|| format!("connecting to {control}"))?;
    let k = TcpStream::connect(kodi).await.with_context(|| format!("connecting to Kodi at {kodi}"))?;
    info!("connected to the daemon and to Kodi");
    let (ctl_read, mut ctl_write) = ctl.into_split();
    let mut ctl_read = BufReader::new(ctl_read);
    let (mut k_read, mut k_write) = k.into_split();
    let mut bridge = Bridge::default();
    let mut line = Vec::new();
    let mut kbuf = Vec::new();
    let mut chunk = vec![0u8; 16 * 1024];
    let mut id = 0u64;
    let result = loop {
        let outs = tokio::select! {
            got = bf_daemon::read_line(&mut ctl_read, &mut line, MAX_LINE) => match got {
                Ok(true) => {
                    let msg = serde_json::from_slice::<Value>(&line);
                    line.clear();
                    match msg {
                        Ok(m) => bridge.from_control(&m),
                        Err(_) => Vec::new(),
                    }
                }
                Ok(false) => break Ok(()),
                Err(e) => break Err(anyhow::Error::from(e).context("the control socket")),
            },
            n = k_read.read(&mut chunk) => match n {
                Ok(0) => break Ok(()),
                Ok(n) => {
                    kbuf.extend_from_slice(&chunk[..n]);
                    let mut outs = Vec::new();
                    for m in split_messages(&mut kbuf) {
                        if m.get("error").is_some() {
                            warn!("Kodi: {}", m["error"]);
                        }
                        outs.extend(bridge.from_kodi(&m));
                    }
                    if kbuf.len() > MAX_KODI {
                        kbuf.clear();
                    }
                    outs
                }
                Err(e) => break Err(anyhow::Error::from(e).context("Kodi's socket")),
            },
        };
        if let Err(e) = send(outs, &mut id, &mut ctl_write, &mut k_write).await {
            break Err(e);
        }
    };
    // Kodi or the daemon gone: the phone's keyboard goes too, if the
    // daemon is still there to hear it.
    let _ = send(bridge.kodi_gone(), &mut id, &mut ctl_write, &mut k_write).await;
    result
}

async fn send(
    outs: Vec<Out>,
    id: &mut u64,
    ctl: &mut (impl AsyncWriteExt + Unpin),
    kodi: &mut (impl AsyncWriteExt + Unpin),
) -> Result<()> {
    for o in outs {
        match o {
            Out::Control(v) => {
                let mut l = v.to_string();
                l.push('\n');
                ctl.write_all(l.as_bytes()).await.context("writing to the control socket")?;
            }
            Out::Kodi(mut v) => {
                *id += 1;
                v["jsonrpc"] = "2.0".into();
                v["id"] = (*id).into();
                debug!("Kodi <- {v}");
                kodi.write_all(v.to_string().as_bytes()).await.context("writing to Kodi")?;
            }
        }
    }
    Ok(())
}

fn args() -> Result<(String, String)> {
    let mut control = "/run/big-fella-remote/control.sock".to_owned();
    let mut kodi = "127.0.0.1:9090".to_owned();
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--control" => control = args.next().context("--control PATH")?,
            "--kodi" => kodi = args.next().context("--kodi HOST:PORT")?,
            "-h" | "--help" => {
                println!("usage: big-fella-remote-kodi [--control PATH] [--kodi HOST:PORT]");
                std::process::exit(0);
            }
            _ => bail!("usage: big-fella-remote-kodi [--control PATH] [--kodi HOST:PORT]"),
        }
    }
    Ok((control, kodi))
}
