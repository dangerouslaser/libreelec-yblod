//! big-fella-remote: the TV box in the iPhone's Control Center remote
//! (README.md).

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, RwLock};

use anyhow::{Context, Result, bail};
use big_fella_remote::input::{InputSink, NoInput};
use big_fella_remote::{advertise, config, conn, control, daemon, pairing, store};
use tracing::{info, warn};

const DEFAULT_CONFIG: &str = "/etc/big-fella/remote.toml";

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    bf_daemon::init_tracing();
    let cfg = config::load(&config_path()?)?;
    let store = store::Store::open(&cfg.state_dir, cfg.pairing)?;

    let tcp = daemon::bind_tcp(cfg.port).await.with_context(|| format!("listening on TCP {}", cfg.port))?;
    let port = tcp.local_addr()?.port();
    let control = control::bind(&cfg.control_socket)?;
    let name = cfg.display_name();
    let ids = advertise::Ids::new(&store.id, &store.key.verifying_key().to_bytes());
    let _mdns = if cfg.advertise {
        let m = advertise::start(&name, &cfg.mdns_host, port, advertise::txt(&ids, &cfg.model, &cfg.rp_flags))?;
        info!("announced as \"{name}\" ({}), port {port}", cfg.model);
        Some(m)
    } else {
        None
    };
    let ctx = conn::Ctx {
        ours: pairing::Ours {
            id: store.id.clone(),
            key: store.key.clone(),
            name: name.clone(),
            model: cfg.model.clone(),
        },
        home_key: cfg.home_key,
        touch: cfg.touch(),
        system_info: advertise::system_info(&ids, &name, &cfg.model, port),
        phones: Arc::new(RwLock::new(HashMap::new())),
    };
    let sink = open_input(cfg.uinput, cfg.home_key);
    // Every socket is bound (Type=notify).
    bf_daemon::notify::ready();
    daemon::run(cfg, store, daemon::Sockets { tcp, control }, sink, ctx).await
}

fn open_input(on: bool, home_key: u16) -> Box<dyn InputSink> {
    if !on {
        info!("uinput off: the remote's keys go nowhere");
        return Box::new(NoInput);
    }
    #[cfg(target_os = "linux")]
    match big_fella_remote::uinput::Uinput::open(home_key) {
        Ok(u) => return Box::new(u),
        Err(e) => warn!("no keyboard for the remote: {e:#}"),
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = home_key;
        warn!("uinput needs Linux: the remote's keys go nowhere");
    }
    Box::new(NoInput)
}

fn config_path() -> Result<PathBuf> {
    let mut args = std::env::args().skip(1);
    match (args.next().as_deref(), args.next()) {
        (None, _) => Ok(DEFAULT_CONFIG.into()),
        (Some("-c" | "--config"), Some(path)) => Ok(path.into()),
        (Some("-h" | "--help"), _) => {
            println!("usage: big-fella-remote [--config PATH]   (default {DEFAULT_CONFIG})");
            std::process::exit(0);
        }
        _ => bail!("usage: big-fella-remote [--config PATH]"),
    }
}
