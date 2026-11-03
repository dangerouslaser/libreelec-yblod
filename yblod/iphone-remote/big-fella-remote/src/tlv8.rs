//! TLV8, HomeKit's pairing records (HAP specification, "TLV8"), which
//! Companion Link's pairing messages carry in their `_pd` field: a type
//! byte, a length byte, the value. A value longer than 255 bytes is split
//! into items of the same type that follow each other, and joined on
//! reading.

pub const METHOD: u8 = 0x00;
pub const IDENTIFIER: u8 = 0x01;
pub const SALT: u8 = 0x02;
pub const PUBLIC_KEY: u8 = 0x03;
pub const PROOF: u8 = 0x04;
pub const ENCRYPTED_DATA: u8 = 0x05;
pub const STATE: u8 = 0x06;
pub const ERROR: u8 = 0x07;
pub const SIGNATURE: u8 = 0x0a;
/// Apple's own: an OPACK dictionary about the device (`name`, `model`...).
pub const INFO: u8 = 0x11;
pub const FLAGS: u8 = 0x13;

/// Error values (TLV ERROR).
pub const ERR_AUTHENTICATION: u8 = 0x02;
pub const ERR_BACKOFF: u8 = 0x03;
pub const ERR_UNAVAILABLE: u8 = 0x06;
pub const ERR_BUSY: u8 = 0x07;

/// FLAGS: a transient pairing (no keys kept), which iOS 18 falls back to on
/// a second connection.
pub const FLAG_TRANSIENT: u32 = 0x10;

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Tlv(Vec<(u8, Vec<u8>)>);

impl Tlv {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with(mut self, kind: u8, value: &[u8]) -> Self {
        self.0.push((kind, value.to_vec()));
        self
    }

    /// Reads one; None if it's cut short.
    pub fn parse(mut data: &[u8]) -> Option<Self> {
        let mut items: Vec<(u8, Vec<u8>)> = Vec::new();
        let mut last = None;
        while !data.is_empty() {
            let (&kind, rest) = data.split_first()?;
            let (&len, rest) = rest.split_first()?;
            let value = rest.get(..usize::from(len))?;
            data = &rest[usize::from(len)..];
            match items.last_mut() {
                // The next piece of a long value.
                Some((k, v)) if last == Some(kind) && *k == kind => v.extend_from_slice(value),
                _ => items.push((kind, value.to_vec())),
            }
            last = Some(kind);
        }
        Some(Self(items))
    }

    pub fn get(&self, kind: u8) -> Option<&[u8]> {
        self.0.iter().find(|(k, _)| *k == kind).map(|(_, v)| v.as_slice())
    }

    /// A little-endian integer item (STATE, FLAGS, ERROR).
    pub fn int(&self, kind: u8) -> Option<u32> {
        let v = self.get(kind)?;
        (v.len() <= 4).then(|| v.iter().rev().fold(0u32, |n, b| n << 8 | u32::from(*b)))
    }

    pub fn encode(&self) -> Vec<u8> {
        let mut out = Vec::new();
        for (kind, value) in &self.0 {
            if value.is_empty() {
                out.extend_from_slice(&[*kind, 0]);
            }
            for chunk in value.chunks(255) {
                out.push(*kind);
                out.push(chunk.len() as u8);
                out.extend_from_slice(chunk);
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use proptest::prelude::*;

    use super::*;

    #[test]
    fn long_values_split_and_join() {
        let key = vec![7u8; 384];
        let t = Tlv::new().with(STATE, &[2]).with(PUBLIC_KEY, &key).with(SALT, &[1; 16]);
        let bytes = t.encode();
        assert_eq!(&bytes[..3], &[STATE, 1, 2]);
        assert_eq!(&bytes[3..5], &[PUBLIC_KEY, 255]);
        let back = Tlv::parse(&bytes).unwrap();
        assert_eq!(back.get(PUBLIC_KEY), Some(&key[..]));
        assert_eq!(back.int(STATE), Some(2));
        assert_eq!(back, t);
        assert_eq!(Tlv::parse(&[FLAGS, 1, 0x10]).unwrap().int(FLAGS), Some(FLAG_TRANSIENT));
        assert!(Tlv::parse(&[STATE, 2, 1]).is_none());
        assert_eq!(Tlv::new().with(METHOD, &[]).encode(), [METHOD, 0]);
    }

    proptest! {
        #[test]
        fn any_bytes(data in prop::collection::vec(any::<u8>(), 0..600)) {
            let _ = Tlv::parse(&data);
        }
    }
}
