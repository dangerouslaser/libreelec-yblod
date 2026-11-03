//! What's kept between runs, in the state folder
//! (/var/lib/big-fella-remote, 0700; every file 0600, written whole):
//!
//! | file | what |
//! |---|---|
//! | `identity.json` | our pairing identifier (a UUID) and Ed25519 key's seed |
//! | `phones.json` | paired phones: identifier, name, model, Ed25519 public key, when |
//! | `settings.json` | `{"pairing": true}`: whether new phones may pair |
//!
//! The key never leaves this folder: not in the log, not on the control
//! socket.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use ed25519_dalek::SigningKey;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use tracing::{info, warn};

/// A paired phone.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Phone {
    /// Its pairing identifier, as it sent it.
    pub id: String,
    pub name: String,
    pub model: String,
    /// Ed25519, hex.
    pub public_key: String,
    /// Seconds since the epoch.
    pub paired_at: i64,
}

impl Phone {
    pub fn key(&self) -> Option<[u8; 32]> {
        hex_decode(&self.public_key)?.try_into().ok()
    }
}

#[derive(Serialize, Deserialize)]
struct IdentityFile {
    id: String,
    seed: String,
}

#[derive(Serialize, Deserialize)]
struct Settings {
    pairing: bool,
}

pub struct Store {
    dir: PathBuf,
    /// Our pairing identifier.
    pub id: String,
    pub key: SigningKey,
    pub pairing: bool,
    pub phones: BTreeMap<String, Phone>,
}

impl Store {
    pub fn open(dir: &Path, pairing_default: bool) -> Result<Self> {
        fs::create_dir_all(dir).with_context(|| format!("creating {}", dir.display()))?;
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(dir, fs::Permissions::from_mode(0o700))
                .with_context(|| format!("chmod {}", dir.display()))?;
        }
        let identity = fs::read(dir.join("identity.json"))
            .ok()
            .and_then(|b| serde_json::from_slice::<IdentityFile>(&b).ok())
            .and_then(|f| Some((f.id, <[u8; 32]>::try_from(hex_decode(&f.seed)?).ok()?)))
            .filter(|(id, _)| valid_id(id));
        let (id, seed) = match identity {
            Some(pair) => pair,
            None => {
                let mut seed = [0u8; 32];
                rand::rngs::OsRng.fill_bytes(&mut seed);
                let id = new_uuid();
                let file = IdentityFile { id: id.clone(), seed: hex(&seed) };
                write_private(&dir.join("identity.json"), &serde_json::to_vec(&file)?)?;
                info!("our pairing identifier is now {id} (phones paired before must pair again)");
                (id, seed)
            }
        };
        let pairing = fs::read(dir.join("settings.json"))
            .ok()
            .and_then(|b| serde_json::from_slice::<Settings>(&b).ok())
            .map_or(pairing_default, |s| s.pairing);
        let phones: BTreeMap<String, Phone> = match fs::read(dir.join("phones.json")) {
            Ok(b) => match serde_json::from_slice::<Vec<Phone>>(&b) {
                Ok(list) => list.into_iter().filter(|p| p.key().is_some()).map(|p| (p.id.clone(), p)).collect(),
                Err(e) => {
                    warn!("phones.json: {e}; no phones paired");
                    BTreeMap::new()
                }
            },
            Err(_) => BTreeMap::new(),
        };
        Ok(Self { dir: dir.to_owned(), id, key: SigningKey::from_bytes(&seed), pairing, phones })
    }

    pub fn set_pairing(&mut self, on: bool) -> Result<()> {
        self.pairing = on;
        write_private(&self.dir.join("settings.json"), &serde_json::to_vec(&Settings { pairing: on })?)
    }

    pub fn add(&mut self, phone: Phone) -> Result<()> {
        self.phones.insert(phone.id.clone(), phone);
        self.save()
    }

    pub fn forget(&mut self, id: &str) -> Result<bool> {
        let had = self.phones.remove(id).is_some();
        if had {
            self.save()?;
        }
        Ok(had)
    }

    fn save(&self) -> Result<()> {
        let list: Vec<&Phone> = self.phones.values().collect();
        write_private(&self.dir.join("phones.json"), &serde_json::to_vec_pretty(&list)?)
    }
}

fn write_private(path: &Path, bytes: &[u8]) -> Result<()> {
    bf_daemon::atomic_write(path, bytes, 0o600).with_context(|| format!("writing {}", path.display()))
}

fn valid_id(id: &str) -> bool {
    !id.is_empty() && id.len() <= 64 && id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
}

/// A random (version 4) UUID, upper case, as Apple's identifiers are written.
pub fn new_uuid() -> String {
    let mut b = [0u8; 16];
    rand::rngs::OsRng.fill_bytes(&mut b);
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    let h = hex(&b).to_uppercase();
    format!("{}-{}-{}-{}-{}", &h[..8], &h[8..12], &h[12..16], &h[16..20], &h[20..])
}

pub fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

pub fn hex_decode(s: &str) -> Option<Vec<u8>> {
    if !s.len().is_multiple_of(2) {
        return None;
    }
    (0..s.len()).step_by(2).map(|i| u8::from_str_radix(s.get(i..i + 2)?, 16).ok()).collect()
}

#[cfg(test)]
pub mod tests {
    use super::*;

    pub fn scratch(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("bfr-{}-{name}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        d
    }

    #[test]
    fn identity_is_made_once_and_phones_persist() {
        let dir = scratch("store");
        let mut a = Store::open(&dir, true).unwrap();
        assert!(valid_id(&a.id) && a.id.len() == 36);
        let b = Store::open(&dir, false).unwrap();
        assert_eq!((&a.id, a.key.to_bytes()), (&b.id, b.key.to_bytes()));
        assert!(!b.pairing, "no settings yet: the default");
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = |p: &str| fs::metadata(dir.join(p)).unwrap().permissions().mode() & 0o777;
            assert_eq!((mode("identity.json"), mode(".")), (0o600, 0o700));
        }
        let phone = Phone {
            id: "8C2C5A11-07D4-4E0A-9C3E-4C5E2B6A7F10".into(),
            name: "Bryan's iPhone".into(),
            model: "iPhone17,1".into(),
            public_key: hex(&[9; 32]),
            paired_at: 1,
        };
        a.add(phone.clone()).unwrap();
        a.set_pairing(false).unwrap();
        let mut c = Store::open(&dir, true).unwrap();
        assert!(!c.pairing);
        assert_eq!(c.phones.get(&phone.id), Some(&phone));
        assert_eq!(c.phones[&phone.id].key(), Some([9; 32]));
        assert!(c.forget(&phone.id).unwrap());
        assert!(!c.forget(&phone.id).unwrap());
        assert!(Store::open(&dir, true).unwrap().phones.is_empty());
        // A broken identity is replaced.
        fs::write(dir.join("identity.json"), "{").unwrap();
        assert_ne!(Store::open(&dir, true).unwrap().id, a.id);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn hex_both_ways() {
        assert_eq!(hex(&[0, 0xab]), "00ab");
        assert_eq!(hex_decode("00ab"), Some(vec![0, 0xab]));
        assert_eq!(hex_decode("0g"), None);
        assert_eq!(hex_decode("abc"), None);
        assert_eq!(hex_decode("é1"), None);
    }
}
