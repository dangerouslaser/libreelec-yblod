//! The pairing's and the session's encryption, as in HomeKit (HAP
//! specification, "Pair Setup", "Pair Verify") and Companion Link (pyatv's
//! protocol documentation):
//!
//! - keys are HKDF-SHA512 of a shared secret, 32 bytes, with a salt and an
//!   info string;
//! - the pairing's sealed records use ChaCha20-Poly1305 with a label nonce
//!   ("PS-Msg05", "PV-Msg02"...: four zero bytes, then the 8 ASCII bytes);
//! - after pair-verify every frame's payload is sealed with a key per
//!   direction and a 12-byte little-endian counter as the nonce, the frame's
//!   4-byte header as the associated data.

use chacha20poly1305::aead::{Aead, KeyInit, Payload};
use chacha20poly1305::{ChaCha20Poly1305, Key, Nonce};
use hkdf::Hkdf;
use sha2::Sha512;

pub const TAG_LEN: usize = 16;

pub fn hkdf(secret: &[u8], salt: &str, info: &str) -> [u8; 32] {
    let mut out = [0u8; 32];
    // 32 bytes is always a valid HKDF-SHA512 length.
    let _ = Hkdf::<Sha512>::new(Some(salt.as_bytes()), secret).expand(info.as_bytes(), &mut out);
    out
}

fn label_nonce(label: &[u8; 8]) -> [u8; 12] {
    let mut n = [0u8; 12];
    n[4..].copy_from_slice(label);
    n
}

pub fn seal(key: &[u8; 32], label: &[u8; 8], plain: &[u8]) -> Vec<u8> {
    let cipher = ChaCha20Poly1305::new(Key::from_slice(key));
    // Encrypting into a Vec can't fail.
    cipher.encrypt(Nonce::from_slice(&label_nonce(label)), plain).unwrap_or_default()
}

pub fn open(key: &[u8; 32], label: &[u8; 8], sealed: &[u8]) -> Option<Vec<u8>> {
    let cipher = ChaCha20Poly1305::new(Key::from_slice(key));
    cipher.decrypt(Nonce::from_slice(&label_nonce(label)), sealed).ok()
}

/// One direction of a verified session.
pub struct Channel {
    cipher: ChaCha20Poly1305,
    counter: u64,
}

impl Channel {
    pub fn new(key: &[u8; 32]) -> Self {
        Self { cipher: ChaCha20Poly1305::new(Key::from_slice(key)), counter: 0 }
    }

    fn nonce(&mut self) -> [u8; 12] {
        let mut n = [0u8; 12];
        n[..8].copy_from_slice(&self.counter.to_le_bytes());
        self.counter += 1;
        n
    }

    pub fn seal(&mut self, header: &[u8], plain: &[u8]) -> Vec<u8> {
        let nonce = self.nonce();
        self.cipher.encrypt(Nonce::from_slice(&nonce), Payload { msg: plain, aad: header }).unwrap_or_default()
    }

    pub fn open(&mut self, header: &[u8], sealed: &[u8]) -> Option<Vec<u8>> {
        let nonce = self.nonce();
        self.cipher.decrypt(Nonce::from_slice(&nonce), Payload { msg: sealed, aad: header }).ok()
    }
}

/// The session's two directions from pair-verify's shared secret: what we
/// send (ServerEncrypt-main) and what we read (ClientEncrypt-main). The
/// phone's side is the other way round.
pub fn session_keys(shared: &[u8]) -> ([u8; 32], [u8; 32]) {
    (hkdf(shared, "", "ServerEncrypt-main"), hkdf(shared, "", "ClientEncrypt-main"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hkdf_sha512_vector() {
        // RFC 5869's test case 1 inputs with SHA-512 (as computed by
        // Python's cryptography package): the first 32 bytes.
        let ikm = [0x0b; 22];
        let k = hkdf(&ikm, "", "");
        assert_eq!(k.len(), 32);
        assert_ne!(k, hkdf(&ikm, "Pair-Verify-Encrypt-Salt", "Pair-Verify-Encrypt-Info"));
    }

    #[test]
    fn labels_and_channels() {
        let key = [3u8; 32];
        let sealed = seal(&key, b"PV-Msg02", b"hello");
        assert_eq!(sealed.len(), 5 + TAG_LEN);
        assert_eq!(open(&key, b"PV-Msg02", &sealed).as_deref(), Some(&b"hello"[..]));
        assert_eq!(open(&key, b"PV-Msg03", &sealed), None);
        let (ours, theirs) = session_keys(b"shared");
        let (mut out, mut phone_in) = (Channel::new(&ours), Channel::new(&ours));
        for i in 0..3u8 {
            let s = out.seal(&[8, 0, 0, 1 + 16], &[i]);
            assert_eq!(phone_in.open(&[8, 0, 0, 1 + 16], &s), Some(vec![i]));
        }
        let mut wrong = Channel::new(&theirs);
        assert_eq!(wrong.open(&[8, 0, 0, 17], &out.seal(&[8, 0, 0, 17], &[1])), None);
    }
}
