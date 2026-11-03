//! SRP-6a as HomeKit's pair-setup uses it (HAP specification; RFC 5054):
//! the 3072-bit group (generator 5), SHA-512, user name "Pair-Setup", the
//! PIN as the password, a 16-byte salt.
//!
//! - k = H(N | PAD(g)), u = H(PAD(A) | PAD(B)), x = H(s | H(I ":" P))
//! - v = g^x, B = k·v + g^b, S = (A·v^u)^b, K = H(S)
//! - M1 = H(H(N) xor H(g) | H(I) | s | A | B | K), M2 = H(A | M1 | K)
//!
//! Numbers go into the hashes as their shortest big-endian bytes except
//! where PAD says (to the group's 384 bytes): the way srptools does it,
//! which pyatv uses on both sides and which iPhones accept (atv-core's
//! notes, CompanionGames' srptools). Our b is chosen so that B never starts
//! with a zero byte, so B's bytes are the same either way. A is hashed as
//! the bytes the phone sent.

use num_bigint::BigUint;
use rand::RngCore;
use sha2::{Digest, Sha512};

const N_HEX: &[u8] = b"\
FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA6\
3B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245\
E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F2411\
7C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F\
83655D23DCA3AD961C62F356208552BB9ED529077096966D670C354E4ABC9804F1746C08\
CA18217C32905E462E36CE3BE39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9\
DE2BCBF6955817183995497CEA956AE515D2261898FA051015728E5A8AAAC42DAD33170D\
04507A33A85521ABDF1CBA64ECFB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7\
ABF5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6BF12FFA06D98A0864D8760273\
3EC86A64521F2B18177B200CBBE117577A615D6C770988C0BAD946E208E24FA074E5AB31\
43DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF";
const G: u32 = 5;
const LEN: usize = 384;
const USER: &[u8] = b"Pair-Setup";

struct Group {
    n: BigUint,
    g: BigUint,
}

fn group() -> Group {
    Group { n: BigUint::parse_bytes(N_HEX, 16).unwrap_or_default(), g: BigUint::from(G) }
}

fn pad(x: &BigUint) -> Vec<u8> {
    let b = x.to_bytes_be();
    let mut out = vec![0u8; LEN.saturating_sub(b.len())];
    out.extend_from_slice(&b);
    out
}

fn h(parts: &[&[u8]]) -> Vec<u8> {
    let mut d = Sha512::new();
    for p in parts {
        d.update(p);
    }
    d.finalize().to_vec()
}

fn x_of(salt: &[u8], pin: &str) -> BigUint {
    let inner = h(&[USER, b":", pin.as_bytes()]);
    BigUint::from_bytes_be(&h(&[salt, &inner]))
}

fn k_of(gr: &Group) -> BigUint {
    BigUint::from_bytes_be(&h(&[&gr.n.to_bytes_be(), &pad(&gr.g)]))
}

fn m1_of(gr: &Group, salt: &[u8], a: &[u8], b: &[u8], key: &[u8]) -> Vec<u8> {
    let hn = h(&[&gr.n.to_bytes_be()]);
    let hg = h(&[&gr.g.to_bytes_be()]);
    let xor: Vec<u8> = hn.iter().zip(&hg).map(|(x, y)| x ^ y).collect();
    // As a number: its shortest bytes (a leading zero byte dropped).
    let xor = BigUint::from_bytes_be(&xor).to_bytes_be();
    h(&[&xor, &h(&[USER]), salt, a, b, key])
}

fn random_bytes<const N: usize>() -> [u8; N] {
    let mut b = [0u8; N];
    rand::rngs::OsRng.fill_bytes(&mut b);
    b
}

/// The accessory's side of one pair-setup.
pub struct Server {
    gr: Group,
    salt: [u8; 16],
    v: BigUint,
    b: BigUint,
    big_b: BigUint,
}

pub struct Proven {
    /// M2, for the phone.
    pub proof: Vec<u8>,
    /// K: what the rest of pair-setup's keys come from.
    pub key: Vec<u8>,
}

impl Server {
    pub fn new(pin: &str) -> Self {
        Self::with(pin, random_bytes(), random_bytes::<32>)
    }

    fn with(pin: &str, salt: [u8; 16], mut secret: impl FnMut() -> [u8; 32]) -> Self {
        let gr = group();
        let v = gr.g.modpow(&x_of(&salt, pin), &gr.n);
        let k = k_of(&gr);
        loop {
            let b = BigUint::from_bytes_be(&secret());
            let big_b = (&k * &v + gr.g.modpow(&b, &gr.n)) % &gr.n;
            if big_b.to_bytes_be().len() == LEN {
                return Self { gr, salt, v, b, big_b };
            }
        }
    }

    pub fn salt(&self) -> &[u8] {
        &self.salt
    }

    pub fn public(&self) -> Vec<u8> {
        self.big_b.to_bytes_be()
    }

    /// The phone's A and M1: Some if it knew the PIN.
    pub fn verify(&self, a_bytes: &[u8], m1: &[u8]) -> Option<Proven> {
        let a = BigUint::from_bytes_be(a_bytes);
        if a_bytes.len() > LEN || (&a % &self.gr.n) == BigUint::default() {
            return None;
        }
        let u = BigUint::from_bytes_be(&h(&[&pad(&a), &pad(&self.big_b)]));
        if u == BigUint::default() {
            return None;
        }
        let s = (&a * self.v.modpow(&u, &self.gr.n)).modpow(&self.b, &self.gr.n);
        let key = h(&[&s.to_bytes_be()]);
        let expected = m1_of(&self.gr, &self.salt, a_bytes, &self.public(), &key);
        if !constant_time_eq(&expected, m1) {
            return None;
        }
        Some(Proven { proof: h(&[a_bytes, m1, &key]), key })
    }
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

/// The phone's side (for tests and the fake phone): A, M1 and K for the
/// accessory's salt and B; M2 to check.
pub struct Client {
    pub public: Vec<u8>,
    pub proof: Vec<u8>,
    pub key: Vec<u8>,
    expect: Vec<u8>,
}

impl Client {
    pub fn new(pin: &str, salt: &[u8], b_bytes: &[u8]) -> Option<Self> {
        let gr = group();
        let a = BigUint::from_bytes_be(&random_bytes::<32>());
        let big_a = gr.g.modpow(&a, &gr.n);
        let big_b = BigUint::from_bytes_be(b_bytes);
        if (&big_b % &gr.n) == BigUint::default() {
            return None;
        }
        let u = BigUint::from_bytes_be(&h(&[&pad(&big_a), &pad(&big_b)]));
        let x = x_of(salt, pin);
        let k = k_of(&gr);
        let gx = gr.g.modpow(&x, &gr.n);
        // S = (B - k·g^x)^(a + u·x), kept positive mod N.
        let kgx = (&k * &gx) % &gr.n;
        let base = (&big_b + &gr.n - kgx) % &gr.n;
        let s = base.modpow(&(&a + &u * &x), &gr.n);
        let key = h(&[&s.to_bytes_be()]);
        let public = big_a.to_bytes_be();
        let proof = m1_of(&gr, salt, &public, b_bytes, &key);
        let expect = h(&[&public, &proof, &key]);
        Some(Self { public, proof, key, expect })
    }

    pub fn check(&self, m2: &[u8]) -> bool {
        constant_time_eq(&self.expect, m2)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_right_pin_and_the_wrong_one() {
        let server = Server::new("1234");
        assert_eq!(server.public().len(), LEN);
        let phone = Client::new("1234", server.salt(), &server.public()).unwrap();
        let proven = server.verify(&phone.public, &phone.proof).expect("same PIN");
        assert!(phone.check(&proven.proof));
        assert_eq!(proven.key, phone.key);
        let wrong = Client::new("4321", server.salt(), &server.public()).unwrap();
        assert!(server.verify(&wrong.public, &wrong.proof).is_none());
        // A = 0 or N would make S known to anyone.
        assert!(server.verify(&[0], &phone.proof).is_none());
        assert!(server.verify(&group().n.to_bytes_be(), &phone.proof).is_none());
    }

    #[test]
    fn b_is_always_full_length() {
        // Secrets that give a short B are skipped (the first tries here).
        let mut n = 0u8;
        let s = Server::with("0000", [1; 16], || {
            n += 1;
            [n; 32]
        });
        assert_eq!(s.public().len(), LEN);
    }
}
