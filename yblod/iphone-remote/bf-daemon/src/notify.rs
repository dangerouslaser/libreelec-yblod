//! systemd's readiness notification (sd_notify(3), for Type=notify): one
//! datagram, "READY=1", to $NOTIFY_SOCKET once the sockets are bound, so
//! `systemctl start` and `restart` return only then, and fail if the daemon
//! exits first. Nothing when not started by systemd.

use std::ffi::OsStr;
use std::io;

/// Tells systemd the daemon is up.
pub fn ready() {
    let Some(socket) = std::env::var_os("NOTIFY_SOCKET") else {
        return;
    };
    if let Err(e) = send(&socket, "READY=1") {
        tracing::warn!("telling systemd we're ready ({}): {e}", socket.to_string_lossy());
    }
}

/// `state` to the notification socket at `socket` (a path, or "@name" for
/// an abstract one).
fn send(socket: &OsStr, state: &str) -> io::Result<()> {
    use std::os::unix::ffi::OsStrExt;
    use std::os::unix::net::UnixDatagram;
    let sock = UnixDatagram::unbound()?;
    match socket.as_bytes().strip_prefix(b"@") {
        #[cfg(target_os = "linux")]
        Some(name) => {
            use std::os::linux::net::SocketAddrExt;
            let addr = std::os::unix::net::SocketAddr::from_abstract_name(name)?;
            sock.send_to_addr(state.as_bytes(), &addr)?;
        }
        #[cfg(not(target_os = "linux"))]
        Some(_) => return Err(io::Error::other("abstract sockets need Linux")),
        None => {
            sock.send_to(state.as_bytes(), std::path::Path::new(socket))?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sends_one_datagram() {
        let path = std::env::temp_dir().join(format!("notify-test-{}.sock", std::process::id()));
        let _ = std::fs::remove_file(&path);
        let listener = std::os::unix::net::UnixDatagram::bind(&path).unwrap();
        send(path.as_os_str(), "READY=1").unwrap();
        let mut buf = [0u8; 64];
        let n = listener.recv(&mut buf).unwrap();
        assert_eq!(&buf[..n], b"READY=1");
        std::fs::remove_file(&path).unwrap();
        assert!(send(path.as_os_str(), "READY=1").is_err(), "nobody listening");
    }
}
