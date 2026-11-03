//! Who we say we are: the mDNS service (`_companion-link._tcp`) and the
//! `_systemInfo` answer, both an Apple TV's.
//!
//! The values are facts gathered by receivers that the iPhone's remote is
//! known to list and drive (research: docs/research/ios-remote.md):
//! CompanionGames and windows-apple-remote (rpMd AppleTV5,3, rpVr 715.2,
//! rpFl 0xB6782, and the `_systemInfo` fields), atv-core (rpFl gates the
//! volume buttons). On a real Apple TV rpHN, rpHA, rpAD, rpHI and rpBA
//! rotate for privacy; ours are stable, derived from our public key, so a
//! phone sees the same TV after a restart.
//!
//! The box has no Avahi (docs/slim.md), so the daemon answers mDNS itself
//! (the mdns-sd crate, a thread of its own).

use std::collections::HashMap;

use anyhow::{Context, Result};
use mdns_sd::{ServiceDaemon, ServiceInfo};
use sha2::{Digest, Sha256};

use crate::opack::Value;
use crate::store::hex;

pub const SERVICE: &str = "_companion-link._tcp.local.";
pub const SOURCE_VERSION: &str = "715.2";

/// What's derived from our identity.
pub struct Ids {
    /// Our pairing identifier (a UUID).
    pub id: String,
    /// 12 hex digits each.
    pub hn: String,
    pub ha: String,
    pub ad: String,
    pub hi: String,
    /// A MAC address, as rpBA and `_pubID`.
    pub ba: String,
    seed: Vec<u8>,
}

impl Ids {
    pub fn new(id: &str, public_key: &[u8; 32]) -> Self {
        let digest = |label: &str| hex(&Sha256::new().chain_update(label).chain_update(public_key).finalize());
        let d = digest("big-fella-remote ids");
        let mac = digest("big-fella-remote mac");
        // A locally administered unicast address.
        let first = (u8::from_str_radix(&mac[..2], 16).unwrap_or(0) & 0xfc) | 0x02;
        let ba = std::iter::once(format!("{first:02X}"))
            .chain((1..6).map(|i| mac[2 * i..2 * i + 2].to_uppercase()))
            .collect::<Vec<_>>()
            .join(":");
        Self {
            id: id.to_owned(),
            hn: d[0..12].into(),
            ha: d[12..24].into(),
            ad: d[24..36].into(),
            hi: d[36..48].into(),
            ba,
            seed: public_key.to_vec(),
        }
    }

    /// A UUID derived from our key and `label`.
    fn uuid(&self, label: &str) -> String {
        let h = hex(&Sha256::new().chain_update(label).chain_update(&self.seed).finalize()).to_uppercase();
        format!("{}-{}-{}-{}-{}", &h[..8], &h[8..12], &h[12..16], &h[16..20], &h[20..32])
    }
}

pub fn txt(ids: &Ids, model: &str, flags: &str) -> HashMap<String, String> {
    [
        ("rpMac", "2"),
        ("rpFl", flags),
        ("rpMd", model),
        ("rpVr", SOURCE_VERSION),
        ("rpHN", &ids.hn),
        ("rpHA", &ids.ha),
        ("rpAD", &ids.ad),
        ("rpHI", &ids.hi),
        ("rpBA", &ids.ba),
        ("rpMRtID", &ids.id),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_owned(), v.to_owned()))
    .collect()
}

/// Our answer to `_systemInfo`, the fields an Apple TV sends.
pub fn system_info(ids: &Ids, name: &str, model: &str, port: u16) -> Value {
    let s = Value::str;
    let i = Value::Int;
    let services = [
        "com.apple.tvremoteservices",
        "com.apple.bluetooth.remote",
        "com.apple.siri.wakeup",
        "com.apple.home.messaging",
        "com.apple.workflow.remotewidgets",
        "com.apple.devicediscoveryui.rapportwake",
    ];
    Value::dict([
        ("name", s(name)),
        ("model", s(model)),
        ("_sv", s(SOURCE_VERSION)),
        ("_i", s(&ids.hi)),
        ("_idsID", s(&ids.uuid("ids"))),
        ("_pubID", s(&ids.ba)),
        ("_mrID", s(&ids.id)),
        ("_mRtID", s(&ids.id)),
        ("_lP", i(i64::from(port))),
        ("_stA", Value::Array(services.iter().map(|x| s(x)).collect())),
        ("_sf", i(65536)),
        ("_bf", i(1920)),
        ("_cf", i(512)),
        ("_clFl", i(128)),
        ("_msSt", i(1)),
        ("_msRo", i(1)),
        ("_dCapF", i(1)),
        (
            "_siriInfo",
            Value::dict([
                ("collectorElectionVersion", Value::Float(1.0)),
                (
                    "peerData",
                    Value::dict([
                        ("productType", s(model)),
                        // tvOS's idiom.
                        ("userInterfaceIdiom", s("ZEUS")),
                        ("userAssignedDeviceName", s(name)),
                        ("assistantIdentifier", s(&ids.uuid("assistant"))),
                        ("sharedUserIdentifier", s(&ids.uuid("user"))),
                        ("isLocationSharingDevice", Value::Bool(false)),
                        ("isSiriCloudSyncEnabled", Value::Bool(false)),
                    ]),
                ),
                (
                    "audio-session-coordination.system-info",
                    Value::dict([
                        ("isSupportedAndEnabled", Value::Bool(false)),
                        ("mediaRemoteGroupIdentifier", s(&ids.uuid("group"))),
                        ("mediaRemoteRouteIdentifier", s(&ids.id)),
                    ]),
                ),
            ]),
        ),
    ])
}

/// Starts answering mDNS for us. Keep the daemon: dropping it stops it
/// (after saying goodbye).
/// `host`: the name our records go under (empty: the host name).
pub fn start(name: &str, host: &str, port: u16, txt: HashMap<String, String>) -> Result<ServiceDaemon> {
    let mdns = ServiceDaemon::new().context("starting mDNS")?;
    let host = match host.trim() {
        "" => crate::config::hostname().unwrap_or_else(|| "big-fella".into()),
        h => h.to_owned(),
    };
    let host = format!("{}.local.", host.split('.').next().unwrap_or("big-fella"));
    let info = ServiceInfo::new(SERVICE, name, &host, "", port, txt).context("our mDNS service")?.enable_addr_auto();
    mdns.register(info).context("announcing us over mDNS")?;
    Ok(mdns)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stable_ids() {
        let a = Ids::new("ID", &[1; 32]);
        let b = Ids::new("ID", &[1; 32]);
        let c = Ids::new("ID", &[2; 32]);
        assert_eq!((a.hn.as_str(), a.ba.as_str()), (b.hn.as_str(), b.ba.as_str()));
        assert_ne!(a.hn, c.hn);
        assert_eq!(a.hn.len(), 12);
        assert_eq!(a.ba.len(), 17);
        let first = u8::from_str_radix(&a.ba[..2], 16).unwrap();
        assert_eq!(first & 0x03, 0x02, "locally administered, unicast");
        let t = txt(&a, "AppleTV5,3", "0xB6782");
        assert_eq!(t["rpMd"], "AppleTV5,3");
        assert_eq!(t["rpMRtID"], "ID");
        let si = system_info(&a, "big-fella", "AppleTV5,3", 49153);
        assert_eq!(si.get("_lP"), Some(&Value::Int(49153)));
        assert_eq!(si.get("_i").and_then(Value::as_str), Some(a.hi.as_str()));
    }
}
