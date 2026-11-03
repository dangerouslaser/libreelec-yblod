//! Companion Link's frames (pyatv's protocol documentation, "Companion"):
//! a type byte, a 3-byte big-endian length, the payload. Pairing frames
//! carry an OPACK dictionary in the clear (its `_pd` is the TLV8 record);
//! after pair-verify, E_OPACK frames carry an OPACK dictionary sealed with
//! the session's keys, the 4-byte header as associated data (the length
//! counts the 16-byte tag).

use std::io;

use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

use crate::crypto::{Channel, TAG_LEN};
use crate::opack::{self, Value};

pub const PS_START: u8 = 0x03;
pub const PS_NEXT: u8 = 0x04;
pub const PV_START: u8 = 0x05;
pub const PV_NEXT: u8 = 0x06;
pub const U_OPACK: u8 = 0x07;
pub const E_OPACK: u8 = 0x08;
pub const P_OPACK: u8 = 0x09;

/// Before pair-verify: pairing messages are a few hundred bytes (M2's
/// 384-byte key the largest).
pub const MAX_UNVERIFIED: usize = 8 * 1024;
/// After: the largest seen are `_systemInfo` and the keyboard's archives,
/// a few KB.
pub const MAX_VERIFIED: usize = 256 * 1024;

#[derive(Debug, Clone, PartialEq)]
pub struct Frame {
    pub kind: u8,
    pub payload: Vec<u8>,
}

/// Reads one frame of at most `max` payload bytes. Ok(None): the
/// connection closed between frames.
pub async fn read<R: AsyncRead + Unpin>(r: &mut R, max: usize) -> io::Result<Option<Frame>> {
    let mut header = [0u8; 4];
    match r.read_exact(&mut header[..1]).await {
        Ok(_) => {}
        Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => return Ok(None),
        Err(e) => return Err(e),
    }
    r.read_exact(&mut header[1..]).await?;
    let len = usize::from(header[1]) << 16 | usize::from(header[2]) << 8 | usize::from(header[3]);
    if len > max {
        return Err(io::Error::new(io::ErrorKind::InvalidData, format!("a {len}-byte frame")));
    }
    let mut payload = vec![0u8; len];
    r.read_exact(&mut payload).await?;
    Ok(Some(Frame { kind: header[0], payload }))
}

fn header(kind: u8, len: usize) -> [u8; 4] {
    let l = (len as u32).to_be_bytes();
    [kind, l[1], l[2], l[3]]
}

pub fn encode_plain(kind: u8, v: &Value) -> Vec<u8> {
    let payload = opack::encode(v);
    let mut out = header(kind, payload.len()).to_vec();
    out.extend_from_slice(&payload);
    out
}

pub fn encode_sealed(out: &mut Channel, v: &Value) -> Vec<u8> {
    let payload = opack::encode(v);
    let h = header(E_OPACK, payload.len() + TAG_LEN);
    let mut frame = h.to_vec();
    frame.extend_from_slice(&out.seal(&h, &payload));
    frame
}

/// A sealed frame's message. None: it doesn't open (the wrong key, a
/// counter out of step) or isn't OPACK.
pub fn open_sealed(input: &mut Channel, f: &Frame) -> Option<Value> {
    let plain = input.open(&header(f.kind, f.payload.len()), &f.payload)?;
    opack::decode(&plain).ok()
}

pub async fn write<W: AsyncWrite + Unpin>(w: &mut W, bytes: &[u8]) -> io::Result<()> {
    w.write_all(bytes).await?;
    w.flush().await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn frames_both_ways() {
        let msg = Value::dict([("_i", Value::str("_hidC")), ("_x", Value::Int(7))]);
        let mut bytes = encode_plain(PS_START, &msg);
        let (mut a, mut b) = (Channel::new(&[1; 32]), Channel::new(&[1; 32]));
        bytes.extend_from_slice(&encode_sealed(&mut a, &msg));
        let mut r = &bytes[..];
        let f = read(&mut r, 1024).await.unwrap().unwrap();
        assert_eq!((f.kind, opack::decode(&f.payload).unwrap()), (PS_START, msg.clone()));
        let f = read(&mut r, 1024).await.unwrap().unwrap();
        assert_eq!(f.kind, E_OPACK);
        assert_eq!(open_sealed(&mut b, &f), Some(msg));
        assert_eq!(read(&mut r, 1024).await.unwrap(), None);
        // Too long, or cut short.
        assert!(read(&mut &[8u8, 0, 4, 1][..], 1024).await.is_err());
        assert!(read(&mut &[8u8, 0, 0, 4, 1][..], 1024).await.is_err());
    }
}
