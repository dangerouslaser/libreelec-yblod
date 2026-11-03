//! What big-fella's daemons (tvd, speakerd, remote-bridged,
//! big-fella-connect, big-fella-remote) share: accepting with backoff, systemd's readiness
//! notification, bounded line reads, atomic file writes, retry backoff, the
//! log's setup and JSON reply lines.

mod accept;
mod backoff;
mod fs;
mod lines;
pub mod notify;
mod reply;

use std::net::IpAddr;

pub use accept::AcceptBackoff;
pub use backoff::Backoff;
pub use fs::atomic_write;
pub use lines::{LineLimit, read_line, read_line_with};
pub use reply::{error_line, reply_line};

/// An address as compared: IPv4-mapped IPv6 (::ffff:a.b.c.d, how a dual-stack
/// socket sees an IPv4 peer) as the IPv4 address.
pub fn canonical(ip: IpAddr) -> IpAddr {
    match ip {
        IpAddr::V6(v6) => v6.to_ipv4_mapped().map_or(ip, IpAddr::V4),
        v4 => v4,
    }
}

/// The log: RUST_LOG's filter (info by default), colours only on a terminal
/// (not in the journal).
pub fn init_tracing() {
    use tracing_subscriber::EnvFilter;
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .with_ansi(std::io::IsTerminal::is_terminal(&std::io::stdout()))
        .init();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_addresses() {
        let ip = |s: &str| s.parse::<IpAddr>().unwrap();
        assert_eq!(canonical(ip("::ffff:192.168.1.5")), ip("192.168.1.5"));
        assert_eq!(canonical(ip("192.168.1.5")), ip("192.168.1.5"));
        assert_eq!(canonical(ip("::1")), ip("::1"));
        assert_eq!(canonical(ip("fe80::1")), ip("fe80::1"));
    }
}
