//! Pair-setup (once per phone, with the PIN on the TV) and pair-verify
//! (every connection), HomeKit's procedures as Companion Link uses them.
//! Written from the HAP specification's description and pyatv's protocol
//! documentation; both sides are here (the phone's for tests and the fake
//! phone). No I/O: TLV8 records in, TLV8 records out.
//!
//! Pair-setup, the accessory (us):
//! - M1 (state 1): a PIN is chosen and shown; M2: salt, B (SRP).
//! - M3: A and the phone's proof; M4: ours, or an authentication error
//!   (wrong PIN).
//! - M5, sealed with K's "Pair-Setup-Encrypt" key ("PS-Msg05"): the phone's
//!   identifier, Ed25519 public key and a signature over
//!   HKDF(K, "Pair-Setup-Controller-Sign") | identifier | key, and maybe
//!   OPACK details (name, model) in item 0x11; M6, sealed ("PS-Msg06"):
//!   ours, signed over HKDF(K, "Pair-Setup-Accessory-Sign") | id | key.
//!
//! Pair-verify:
//! - M1: the phone's X25519 key; M2: ours, and sealed with the shared
//!   secret's "Pair-Verify-Encrypt" key ("PV-Msg02") our identifier and a
//!   signature over our X25519 key | identifier | theirs.
//! - M3, sealed ("PV-Msg03"): the phone's identifier and its signature over
//!   its X25519 key | identifier | ours, checked against the key it paired
//!   with (pyatv's own test server skips this; windows-apple-remote and we
//!   don't); M4: done, or an authentication error (not paired: the phone
//!   then pairs).

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use rand::RngCore;
use x25519_dalek::{EphemeralSecret, PublicKey};

use crate::crypto::{self, hkdf};
use crate::opack::{self, Value};
use crate::srp;
use crate::tlv8::{self, Tlv};

/// Who we are to the phones.
pub struct Ours {
    pub id: String,
    pub key: SigningKey,
    pub name: String,
    pub model: String,
}

/// A phone that has just paired.
#[derive(Debug, Clone, PartialEq)]
pub struct NewPhone {
    pub id: String,
    pub public_key: [u8; 32],
    pub name: String,
    pub model: String,
}

fn state(n: u8) -> Tlv {
    Tlv::new().with(tlv8::STATE, &[n])
}

pub fn error(n: u8, code: u8) -> Tlv {
    state(n).with(tlv8::ERROR, &[code])
}

/// A random four-digit PIN, as the TV shows it.
pub fn new_pin() -> String {
    let n = rand::rngs::OsRng.next_u32() % 10_000;
    format!("{n:04}")
}

pub struct Setup {
    srp: srp::Server,
    key: Option<Vec<u8>>,
}

impl Setup {
    /// After M1, with the PIN that's now on the screen: M2.
    pub fn start(pin: &str) -> (Self, Tlv) {
        let srp = srp::Server::new(pin);
        let m2 = state(2)
            .with(tlv8::SALT, srp.salt())
            .with(tlv8::PUBLIC_KEY, &srp.public())
            // Apple TVs send this (0x1b = 1; pyatv's test server too).
            .with(0x1b, &[1]);
        (Self { srp, key: None }, m2)
    }

    /// M3 -> M4. Err: the wrong PIN (M4 with the error).
    pub fn m3(&mut self, m3: &Tlv) -> Result<Tlv, Tlv> {
        let auth = || error(4, tlv8::ERR_AUTHENTICATION);
        let (Some(a), Some(proof)) = (m3.get(tlv8::PUBLIC_KEY), m3.get(tlv8::PROOF)) else { return Err(auth()) };
        let proven = self.srp.verify(a, proof).ok_or_else(auth)?;
        self.key = Some(proven.key);
        Ok(state(4).with(tlv8::PROOF, &proven.proof))
    }

    /// M5 -> M6 and the phone.
    pub fn m5(&self, ours: &Ours, m5: &Tlv) -> Result<(Tlv, NewPhone), Tlv> {
        let auth = || error(6, tlv8::ERR_AUTHENTICATION);
        let k = self.key.as_deref().ok_or_else(auth)?;
        let enc = hkdf(k, "Pair-Setup-Encrypt-Salt", "Pair-Setup-Encrypt-Info");
        let sealed = m5.get(tlv8::ENCRYPTED_DATA).ok_or_else(auth)?;
        let inner = crypto::open(&enc, b"PS-Msg05", sealed).and_then(|p| Tlv::parse(&p)).ok_or_else(auth)?;
        let id = inner.get(tlv8::IDENTIFIER).and_then(|b| std::str::from_utf8(b).ok()).ok_or_else(auth)?;
        let ltpk: [u8; 32] = inner.get(tlv8::PUBLIC_KEY).and_then(|b| b.try_into().ok()).ok_or_else(auth)?;
        let sig = inner.get(tlv8::SIGNATURE).and_then(|b| Signature::from_slice(b).ok()).ok_or_else(auth)?;
        let x = hkdf(k, "Pair-Setup-Controller-Sign-Salt", "Pair-Setup-Controller-Sign-Info");
        let signed = [&x[..], id.as_bytes(), &ltpk].concat();
        VerifyingKey::from_bytes(&ltpk).ok().filter(|v| v.verify(&signed, &sig).is_ok()).ok_or_else(auth)?;
        if id.is_empty() || id.len() > 128 {
            return Err(auth());
        }
        let details = inner.get(tlv8::INFO).and_then(|b| opack::decode(b).ok());
        let detail = |k: &str| details.as_ref().and_then(|d| d.get(k)).and_then(Value::as_str).unwrap_or("").to_owned();
        let phone = NewPhone { id: id.to_owned(), public_key: ltpk, name: detail("name"), model: detail("model") };

        let our_pub = ours.key.verifying_key().to_bytes();
        let x = hkdf(k, "Pair-Setup-Accessory-Sign-Salt", "Pair-Setup-Accessory-Sign-Info");
        let sig = ours.key.sign(&[&x[..], ours.id.as_bytes(), &our_pub].concat());
        let about = Value::dict([("name", Value::str(&ours.name)), ("model", Value::str(&ours.model))]);
        let inner = Tlv::new()
            .with(tlv8::IDENTIFIER, ours.id.as_bytes())
            .with(tlv8::PUBLIC_KEY, &our_pub)
            .with(tlv8::SIGNATURE, &sig.to_bytes())
            .with(tlv8::INFO, &opack::encode(&about));
        let m6 = state(6).with(tlv8::ENCRYPTED_DATA, &crypto::seal(&enc, b"PS-Msg06", &inner.encode()));
        Ok((m6, phone))
    }
}

pub struct Verify {
    theirs: [u8; 32],
    ours: [u8; 32],
    shared: [u8; 32],
}

/// The session's keys: what we send with, what we read with.
pub struct Keys {
    pub send: [u8; 32],
    pub receive: [u8; 32],
}

impl Verify {
    /// M1 -> M2. None: not a pair-verify M1.
    pub fn start(ours: &Ours, m1: &Tlv) -> Option<(Self, Tlv)> {
        let theirs: [u8; 32] = m1.get(tlv8::PUBLIC_KEY)?.try_into().ok()?;
        let secret = EphemeralSecret::random_from_rng(rand::rngs::OsRng);
        let mine = PublicKey::from(&secret).to_bytes();
        let shared = secret.diffie_hellman(&PublicKey::from(theirs)).to_bytes();
        let enc = hkdf(&shared, "Pair-Verify-Encrypt-Salt", "Pair-Verify-Encrypt-Info");
        let sig = ours.key.sign(&[&mine[..], ours.id.as_bytes(), &theirs].concat());
        let inner = Tlv::new().with(tlv8::IDENTIFIER, ours.id.as_bytes()).with(tlv8::SIGNATURE, &sig.to_bytes());
        let m2 = state(2)
            .with(tlv8::PUBLIC_KEY, &mine)
            .with(tlv8::ENCRYPTED_DATA, &crypto::seal(&enc, b"PV-Msg02", &inner.encode()));
        Some((Self { theirs, ours: mine, shared }, m2))
    }

    /// M3 -> M4: the phone's identifier and the session keys if it's a phone
    /// `known` has the key of; else M4 with an error, for the phone to pair.
    pub fn finish(&self, m3: &Tlv, known: impl Fn(&str) -> Option<[u8; 32]>) -> Result<(Tlv, String, Keys), Tlv> {
        let auth = || error(4, tlv8::ERR_AUTHENTICATION);
        let enc = hkdf(&self.shared, "Pair-Verify-Encrypt-Salt", "Pair-Verify-Encrypt-Info");
        let sealed = m3.get(tlv8::ENCRYPTED_DATA).ok_or_else(auth)?;
        let inner = crypto::open(&enc, b"PV-Msg03", sealed).and_then(|p| Tlv::parse(&p)).ok_or_else(auth)?;
        let id = inner.get(tlv8::IDENTIFIER).and_then(|b| std::str::from_utf8(b).ok()).ok_or_else(auth)?;
        let sig = inner.get(tlv8::SIGNATURE).and_then(|b| Signature::from_slice(b).ok()).ok_or_else(auth)?;
        let key = known(id).and_then(|k| VerifyingKey::from_bytes(&k).ok()).ok_or_else(auth)?;
        key.verify(&[&self.theirs[..], id.as_bytes(), &self.ours].concat(), &sig).map_err(|_| auth())?;
        let (send, receive) = crypto::session_keys(&self.shared);
        Ok((state(4), id.to_owned(), Keys { send, receive }))
    }
}

/// The phone's side, for tests and the fake phone.
pub mod phone {
    use super::*;

    pub struct Identity {
        pub id: String,
        pub key: SigningKey,
        pub name: String,
    }

    pub fn m1_setup() -> Tlv {
        Tlv::new().with(tlv8::METHOD, &[0]).with(tlv8::STATE, &[1])
    }

    /// M2 and the PIN -> M3, and what M4 and M5 need.
    pub fn m3(m2: &Tlv, pin: &str) -> Option<(Tlv, srp::Client)> {
        let c = srp::Client::new(pin, m2.get(tlv8::SALT)?, m2.get(tlv8::PUBLIC_KEY)?)?;
        let m3 = state(3).with(tlv8::PUBLIC_KEY, &c.public).with(tlv8::PROOF, &c.proof);
        Some((m3, c))
    }

    /// M4 -> M5. None: the TV didn't prove it knew the PIN.
    pub fn m5(me: &Identity, srp: &srp::Client, m4: &Tlv) -> Option<Tlv> {
        if !srp.check(m4.get(tlv8::PROOF)?) {
            return None;
        }
        let enc = hkdf(&srp.key, "Pair-Setup-Encrypt-Salt", "Pair-Setup-Encrypt-Info");
        let x = hkdf(&srp.key, "Pair-Setup-Controller-Sign-Salt", "Pair-Setup-Controller-Sign-Info");
        let public = me.key.verifying_key().to_bytes();
        let sig = me.key.sign(&[&x[..], me.id.as_bytes(), &public].concat());
        let about = Value::dict([("name", Value::str(&me.name)), ("model", Value::str("iPhone17,1"))]);
        let inner = Tlv::new()
            .with(tlv8::IDENTIFIER, me.id.as_bytes())
            .with(tlv8::PUBLIC_KEY, &public)
            .with(tlv8::SIGNATURE, &sig.to_bytes())
            .with(tlv8::INFO, &opack::encode(&about));
        Some(state(5).with(tlv8::ENCRYPTED_DATA, &crypto::seal(&enc, b"PS-Msg05", &inner.encode())))
    }

    /// M6 -> the TV's identifier and public key.
    pub fn finish_setup(srp: &srp::Client, m6: &Tlv) -> Option<(String, [u8; 32])> {
        let enc = hkdf(&srp.key, "Pair-Setup-Encrypt-Salt", "Pair-Setup-Encrypt-Info");
        let inner = Tlv::parse(&crypto::open(&enc, b"PS-Msg06", m6.get(tlv8::ENCRYPTED_DATA)?)?)?;
        let id = std::str::from_utf8(inner.get(tlv8::IDENTIFIER)?).ok()?.to_owned();
        let key: [u8; 32] = inner.get(tlv8::PUBLIC_KEY)?.try_into().ok()?;
        let sig = Signature::from_slice(inner.get(tlv8::SIGNATURE)?).ok()?;
        let x = hkdf(&srp.key, "Pair-Setup-Accessory-Sign-Salt", "Pair-Setup-Accessory-Sign-Info");
        VerifyingKey::from_bytes(&key).ok()?.verify(&[&x[..], id.as_bytes(), &key].concat(), &sig).ok()?;
        Some((id, key))
    }

    pub struct Verifying {
        secret: Option<EphemeralSecret>,
        public: [u8; 32],
    }

    pub fn m1_verify() -> (Verifying, Tlv) {
        let secret = EphemeralSecret::random_from_rng(rand::rngs::OsRng);
        let public = PublicKey::from(&secret).to_bytes();
        (Verifying { secret: Some(secret), public }, state(1).with(tlv8::PUBLIC_KEY, &public))
    }

    /// M2 -> M3 and the session keys (the phone's: send = ClientEncrypt).
    /// `tv` is the TV's identifier and key from pairing (None: don't check,
    /// a phone that never paired).
    pub fn m3_verify(me: &Identity, v: &mut Verifying, m2: &Tlv, tv: Option<(&str, [u8; 32])>) -> Option<(Tlv, Keys)> {
        let theirs: [u8; 32] = m2.get(tlv8::PUBLIC_KEY)?.try_into().ok()?;
        let shared = v.secret.take()?.diffie_hellman(&PublicKey::from(theirs)).to_bytes();
        let enc = hkdf(&shared, "Pair-Verify-Encrypt-Salt", "Pair-Verify-Encrypt-Info");
        let inner = Tlv::parse(&crypto::open(&enc, b"PV-Msg02", m2.get(tlv8::ENCRYPTED_DATA)?)?)?;
        if let Some((id, key)) = tv {
            let sig = Signature::from_slice(inner.get(tlv8::SIGNATURE)?).ok()?;
            if inner.get(tlv8::IDENTIFIER)? != id.as_bytes() {
                return None;
            }
            VerifyingKey::from_bytes(&key)
                .ok()?
                .verify(&[&theirs[..], id.as_bytes(), &v.public].concat(), &sig)
                .ok()?;
        }
        let sig = me.key.sign(&[&v.public[..], me.id.as_bytes(), &theirs].concat());
        let inner = Tlv::new().with(tlv8::IDENTIFIER, me.id.as_bytes()).with(tlv8::SIGNATURE, &sig.to_bytes());
        let m3 = state(3).with(tlv8::ENCRYPTED_DATA, &crypto::seal(&enc, b"PV-Msg03", &inner.encode()));
        let (tv_send, tv_receive) = crypto::session_keys(&shared);
        Some((m3, Keys { send: tv_receive, receive: tv_send }))
    }
}

#[cfg(test)]
mod tests {
    use super::phone::*;
    use super::*;

    fn key(seed: u8) -> SigningKey {
        SigningKey::from_bytes(&[seed; 32])
    }

    fn ours() -> Ours {
        Ours {
            id: "1B2C3D4E-0000-4000-8000-000000000001".into(),
            key: key(1),
            name: "big-fella".into(),
            model: "AppleTV5,3".into(),
        }
    }

    #[test]
    fn setup_then_verify() {
        let ours = ours();
        let me = Identity { id: "PHONE-1".into(), key: key(2), name: "iPhone".into() };
        let (mut setup, m2) = Setup::start("4821");
        let (m3, srp) = m3(&m2, "4821").unwrap();
        let m4 = setup.m3(&m3).unwrap();
        let m5 = m5(&me, &srp, &m4).unwrap();
        let (m6, phone) = setup.m5(&ours, &m5).unwrap();
        assert_eq!(
            phone,
            NewPhone {
                id: "PHONE-1".into(),
                public_key: me.key.verifying_key().to_bytes(),
                name: "iPhone".into(),
                model: "iPhone17,1".into()
            }
        );
        let (tv_id, tv_key) = finish_setup(&srp, &m6).unwrap();
        assert_eq!((tv_id.as_str(), tv_key), (ours.id.as_str(), ours.key.verifying_key().to_bytes()));

        let (mut v, m1) = m1_verify();
        let (server, m2) = Verify::start(&ours, &m1).unwrap();
        let (m3, phone_keys) = m3_verify(&me, &mut v, &m2, Some((&tv_id, tv_key))).unwrap();
        let known = |id: &str| (id == "PHONE-1").then_some(phone.public_key);
        let (m4, id, keys) = server.finish(&m3, known).unwrap();
        assert_eq!((m4.int(tlv8::STATE), m4.get(tlv8::ERROR), id.as_str()), (Some(4), None, "PHONE-1"));
        assert_eq!((keys.send, keys.receive), (phone_keys.receive, phone_keys.send));
    }

    #[test]
    fn wrong_pin_and_strangers() {
        let ours = ours();
        let (mut setup, m2) = Setup::start("4821");
        let (m3, _) = m3(&m2, "1111").unwrap();
        let m4 = setup.m3(&m3).unwrap_err();
        assert_eq!(m4.get(tlv8::ERROR), Some(&[tlv8::ERR_AUTHENTICATION][..]));
        assert!(setup.m5(&ours, &Tlv::new()).is_err(), "no M5 without M3");

        // Never paired, or paired with another key: M4 says so.
        let stranger = Identity { id: "PHONE-2".into(), key: key(3), name: String::new() };
        let (mut v, m1) = m1_verify();
        let (server, m2) = Verify::start(&ours, &m1).unwrap();
        let (m3, _) = m3_verify(&stranger, &mut v, &m2, None).unwrap();
        assert!(server.finish(&m3, |_| None).is_err());
        assert!(server.finish(&m3, |_| Some(key(4).verifying_key().to_bytes())).is_err());
        assert!(server.finish(&Tlv::new(), |_| None).is_err());
        assert!(Verify::start(&ours, &Tlv::new()).is_none());
    }

    #[test]
    fn a_forged_m5_is_refused() {
        let ours = ours();
        let me = Identity { id: "PHONE-1".into(), key: key(2), name: "iPhone".into() };
        let (mut setup, m2) = Setup::start("0000");
        let (m3, srp) = m3(&m2, "0000").unwrap();
        let m4 = setup.m3(&m3).unwrap();
        // Signed with a key other than the one it claims.
        let enc = hkdf(&srp.key, "Pair-Setup-Encrypt-Salt", "Pair-Setup-Encrypt-Info");
        let x = hkdf(&srp.key, "Pair-Setup-Controller-Sign-Salt", "Pair-Setup-Controller-Sign-Info");
        let claimed = key(5).verifying_key().to_bytes();
        let sig = me.key.sign(&[&x[..], me.id.as_bytes(), &claimed].concat());
        let inner = Tlv::new()
            .with(tlv8::IDENTIFIER, b"PHONE-1")
            .with(tlv8::PUBLIC_KEY, &claimed)
            .with(tlv8::SIGNATURE, &sig.to_bytes());
        let forged = state(5).with(tlv8::ENCRYPTED_DATA, &crypto::seal(&enc, b"PS-Msg05", &inner.encode()));
        assert!(setup.m5(&ours, &forged).is_err());
        assert!(m5(&me, &srp, &m4).is_some());
    }

    #[test]
    fn pins_are_four_digits() {
        for _ in 0..100 {
            let p = new_pin();
            assert!(p.len() == 4 && p.bytes().all(|b| b.is_ascii_digit()), "{p}");
        }
    }
}
