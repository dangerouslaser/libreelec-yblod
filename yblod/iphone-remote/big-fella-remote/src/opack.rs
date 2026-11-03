//! OPACK, Apple's binary serialisation (CoreUtils) that Companion Link's
//! messages are written in. Written from pyatv's protocol documentation
//! (pyatv.dev/documentation/protocols, "OPACK") and checked against
//! pyatv's encoder in the end-to-end test; the decoder's reference table
//! follows pyatv's `support/opack.py` (MIT) as described there, not its code.
//!
//! Each value starts with a tag byte:
//!
//! | tag | value |
//! |---|---|
//! | 0x01, 0x02 | true, false |
//! | 0x04 | null |
//! | 0x05 | UUID, 16 bytes |
//! | 0x06 | absolute time, 8 bytes (read as an integer) |
//! | 0x08-0x2f | the integers 0-39 |
//! | 0x30-0x33 | an integer in 1, 2, 4 or 8 little-endian bytes |
//! | 0x35, 0x36 | float32, float64 (little endian) |
//! | 0x40-0x60 | a UTF-8 string of 0-32 bytes |
//! | 0x61-0x64 | a string with a 1-4 byte little-endian length |
//! | 0x70-0x90 | data of 0-32 bytes |
//! | 0x91-0x94 | data with a 1, 2, 4 or 8 byte length |
//! | 0xa0-0xc0 | a reference to an earlier value (index 0-32) |
//! | 0xc1-0xc4 | a reference with a 1-4 byte index |
//! | 0xd0-0xde | an array of 0-14 items; 0xdf: items till 0x03 |
//! | 0xe0-0xee | a dictionary of 0-14 pairs; 0xef: pairs till 0x03 |
//!
//! References: every value read that takes more than one byte (not a
//! boolean, null, a small integer, an empty string or data) and isn't an
//! array or a dictionary is added to a table, once (a value already in it,
//! of the same type, isn't added again), and 0xa0... name its entries in
//! order. That's Apple's encoder as windows-apple-remote found it against
//! iOS 27's `_systemInfo` (pyatv 0.18 also tabled "" and b"", and read
//! later references one entry off). We never write references (decoders
//! take either).
//!
//! The decoder never panics and is bounded: nesting at most MAX_DEPTH, a
//! collection's items no more than the input has bytes.

use std::fmt;

const MAX_DEPTH: usize = 32;

#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Uuid([u8; 16]),
    Int(i64),
    Float(f64),
    Str(String),
    Data(Vec<u8>),
    Array(Vec<Value>),
    /// In the order read (keys are usually strings).
    Dict(Vec<(Value, Value)>),
}

impl Value {
    pub fn str(s: &str) -> Self {
        Value::Str(s.to_owned())
    }

    /// A dictionary with string keys.
    pub fn dict<const N: usize>(pairs: [(&str, Value); N]) -> Self {
        Value::Dict(pairs.into_iter().map(|(k, v)| (Value::str(k), v)).collect())
    }

    pub fn get(&self, key: &str) -> Option<&Value> {
        match self {
            Value::Dict(pairs) => pairs.iter().find(|(k, _)| matches!(k, Value::Str(s) if s == key)).map(|(_, v)| v),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_int(&self) -> Option<i64> {
        match self {
            Value::Int(i) => Some(*i),
            Value::Float(f) if f.is_finite() && f.fract() == 0.0 => Some(*f as i64),
            _ => None,
        }
    }

    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Value::Int(i) => Some(*i as f64),
            Value::Float(f) if f.is_finite() => Some(*f),
            _ => None,
        }
    }

    pub fn as_data(&self) -> Option<&[u8]> {
        match self {
            Value::Data(d) => Some(d),
            _ => None,
        }
    }

    /// Sets `key` in a dictionary (replacing it if it's there).
    pub fn set(&mut self, key: &str, value: Value) {
        if let Value::Dict(pairs) = self {
            match pairs.iter_mut().find(|(k, _)| matches!(k, Value::Str(s) if s == key)) {
                Some((_, v)) => *v = value,
                None => pairs.push((Value::str(key), value)),
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Error(pub &'static str);

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "OPACK: {}", self.0)
    }
}

impl std::error::Error for Error {}

pub fn encode(v: &Value) -> Vec<u8> {
    let mut out = Vec::new();
    write(v, &mut out);
    out
}

fn write_len(out: &mut Vec<u8>, inline_base: u8, sized_base: u8, len: usize, sizes: &[usize]) {
    if len <= 0x20 {
        out.push(inline_base + len as u8);
        return;
    }
    for (i, &bytes) in sizes.iter().enumerate() {
        if bytes == 8 || len < 1usize << (8 * bytes) {
            out.push(sized_base + i as u8);
            out.extend_from_slice(&(len as u64).to_le_bytes()[..bytes]);
            return;
        }
    }
}

fn write(v: &Value, out: &mut Vec<u8>) {
    match v {
        Value::Null => out.push(0x04),
        Value::Bool(b) => out.push(if *b { 0x01 } else { 0x02 }),
        Value::Uuid(u) => {
            out.push(0x05);
            out.extend_from_slice(u);
        }
        Value::Int(i) => match *i {
            0..=0x27 => out.push(0x08 + *i as u8),
            0x28..=0xff => out.extend_from_slice(&[0x30, *i as u8]),
            0x100..=0xffff => {
                out.push(0x31);
                out.extend_from_slice(&(*i as u16).to_le_bytes());
            }
            0x1_0000..=0xffff_ffff => {
                out.push(0x32);
                out.extend_from_slice(&(*i as u32).to_le_bytes());
            }
            _ => {
                out.push(0x33);
                out.extend_from_slice(&i.to_le_bytes());
            }
        },
        Value::Float(f) => {
            out.push(0x36);
            out.extend_from_slice(&f.to_le_bytes());
        }
        Value::Str(s) => {
            write_len(out, 0x40, 0x61, s.len(), &[1, 2, 3, 4]);
            out.extend_from_slice(s.as_bytes());
        }
        Value::Data(d) => {
            write_len(out, 0x70, 0x91, d.len(), &[1, 2, 4, 8]);
            out.extend_from_slice(d);
        }
        Value::Array(items) => {
            out.push(0xd0 + items.len().min(0xf) as u8);
            items.iter().for_each(|i| write(i, out));
            if items.len() >= 0xf {
                out.push(0x03);
            }
        }
        Value::Dict(pairs) => {
            out.push(0xe0 + pairs.len().min(0xf) as u8);
            for (k, v) in pairs {
                write(k, out);
                write(v, out);
            }
            if pairs.len() >= 0xf {
                out.push(0x03);
            }
        }
    }
}

/// One value, which must be the whole of `data`.
pub fn decode(data: &[u8]) -> Result<Value, Error> {
    let mut r = Reader { data, pos: 0, table: Vec::new() };
    let v = r.value(0)?;
    if r.pos != data.len() {
        return Err(Error("bytes after the value"));
    }
    Ok(v)
}

struct Reader<'a> {
    data: &'a [u8],
    pos: usize,
    table: Vec<Value>,
}

impl Reader<'_> {
    fn take(&mut self, n: usize) -> Result<&[u8], Error> {
        let end = self.pos.checked_add(n).filter(|e| *e <= self.data.len()).ok_or(Error("truncated"))?;
        let s = &self.data[self.pos..end];
        self.pos = end;
        Ok(s)
    }

    fn uint(&mut self, n: usize) -> Result<u64, Error> {
        let mut b = [0u8; 8];
        b[..n].copy_from_slice(self.take(n)?);
        Ok(u64::from_le_bytes(b))
    }

    fn len(&mut self, n: usize) -> Result<usize, Error> {
        let len = self.uint(n)?;
        usize::try_from(len).ok().filter(|l| *l <= self.data.len()).ok_or(Error("length past the end"))
    }

    fn value(&mut self, depth: usize) -> Result<Value, Error> {
        if depth > MAX_DEPTH {
            return Err(Error("nested too deep"));
        }
        let tag = self.take(1)?[0];
        let v = match tag {
            0x01 => return Ok(Value::Bool(true)),
            0x02 => return Ok(Value::Bool(false)),
            0x04 => return Ok(Value::Null),
            0x05 => Value::Uuid(self.take(16)?.try_into().unwrap_or([0; 16])),
            0x06 => Value::Int(self.uint(8)? as i64),
            0x08..=0x2f => return Ok(Value::Int(i64::from(tag - 8))),
            0x30..=0x33 => Value::Int(self.uint(1 << (tag - 0x30))? as i64),
            0x35 => Value::Float(f64::from(f32::from_le_bytes(self.take(4)?.try_into().unwrap_or([0; 4])))),
            0x36 => Value::Float(f64::from_le_bytes(self.take(8)?.try_into().unwrap_or([0; 8]))),
            0x40..=0x60 => self.string(usize::from(tag - 0x40))?,
            0x61..=0x64 => {
                let n = self.len(usize::from(tag - 0x60))?;
                self.string(n)?
            }
            0x70..=0x90 => Value::Data(self.take(usize::from(tag - 0x70))?.to_vec()),
            0x91..=0x94 => {
                let n = self.len(1 << (tag - 0x91))?;
                Value::Data(self.take(n)?.to_vec())
            }
            0xa0..=0xc0 => return self.reference(usize::from(tag - 0xa0)),
            0xc1..=0xc4 => {
                let i = self.uint(usize::from(tag - 0xc0))?;
                return self.reference(usize::try_from(i).unwrap_or(usize::MAX));
            }
            0xd0..=0xdf => {
                let mut items = Vec::new();
                if tag == 0xdf {
                    while self.peek()? != 0x03 {
                        items.push(self.value(depth + 1)?);
                    }
                    self.pos += 1;
                } else {
                    for _ in 0..tag - 0xd0 {
                        items.push(self.value(depth + 1)?);
                    }
                }
                return Ok(Value::Array(items));
            }
            0xe0..=0xef => {
                let mut pairs = Vec::new();
                if tag == 0xef {
                    while self.peek()? != 0x03 {
                        let k = self.value(depth + 1)?;
                        pairs.push((k, self.value(depth + 1)?));
                    }
                    self.pos += 1;
                } else {
                    for _ in 0..tag - 0xe0 {
                        let k = self.value(depth + 1)?;
                        pairs.push((k, self.value(depth + 1)?));
                    }
                }
                return Ok(Value::Dict(pairs));
            }
            _ => return Err(Error("unknown tag")),
        };
        let one_byte = matches!(&v, Value::Str(s) if s.is_empty()) || matches!(&v, Value::Data(d) if d.is_empty());
        if !one_byte && !self.table.contains(&v) {
            self.table.push(v.clone());
        }
        Ok(v)
    }

    fn peek(&self) -> Result<u8, Error> {
        self.data.get(self.pos).copied().ok_or(Error("truncated"))
    }

    fn string(&mut self, n: usize) -> Result<Value, Error> {
        let s = std::str::from_utf8(self.take(n)?).map_err(|_| Error("a string that isn't UTF-8"))?;
        Ok(Value::str(s))
    }

    fn reference(&self, i: usize) -> Result<Value, Error> {
        self.table.get(i).cloned().ok_or(Error("a reference to nothing"))
    }
}

#[cfg(test)]
mod tests {
    use proptest::prelude::*;

    use super::*;

    #[test]
    fn known_encodings() {
        // Byte strings as pyatv's encoder writes them (its unit tests' values).
        assert_eq!(encode(&Value::Bool(true)), [0x01]);
        assert_eq!(encode(&Value::Null), [0x04]);
        assert_eq!(encode(&Value::Int(0)), [0x08]);
        assert_eq!(encode(&Value::Int(0x27)), [0x2f]);
        assert_eq!(encode(&Value::Int(0x28)), [0x30, 0x28]);
        assert_eq!(encode(&Value::Int(0x1ff)), [0x31, 0xff, 0x01]);
        assert_eq!(encode(&Value::Int(0x1_0000)), [0x32, 0, 0, 1, 0]);
        assert_eq!(encode(&Value::str("a")), [0x41, b'a']);
        let long = "x".repeat(0x21);
        assert_eq!(encode(&Value::str(&long))[..2], [0x61, 0x21]);
        assert_eq!(encode(&Value::Data(vec![1, 2])), [0x72, 1, 2]);
        assert_eq!(encode(&Value::Data(vec![0; 0x100]))[..3], [0x92, 0x00, 0x01]);
        assert_eq!(encode(&Value::dict([("_i", Value::Int(1))])), [0xe1, 0x42, b'_', b'i', 0x09]);
        let fifteen = Value::Array(vec![Value::Int(1); 15]);
        let e = encode(&fifteen);
        assert_eq!((e[0], *e.last().unwrap()), (0xdf, 0x03));
        assert_eq!(decode(&e).unwrap(), fifteen);
    }

    #[test]
    fn references() {
        // {"a": "xyz", "b": <ref 1>}: the table holds "a", "xyz", "b" in that
        // order; 0xa1 is "xyz".
        let data = [0xe2, 0x41, b'a', 0x43, b'x', b'y', b'z', 0x41, b'b', 0xa1];
        let v = decode(&data).unwrap();
        assert_eq!(v.get("b").and_then(Value::as_str), Some("xyz"));
        // A value already in the table isn't added twice: "a" again, then a
        // reference to the third entry ("b").
        let data = [0xe3, 0x41, b'a', 0x41, b'b', 0x41, b'b', 0x41, b'a', 0x41, b'c', 0xa2];
        let v = decode(&data).unwrap();
        assert_eq!(v.get("c").and_then(Value::as_str), Some("c"), "{v:?}");
        // Small integers, booleans and "" aren't entries.
        let data = [0xe2, 0x41, b'a', 0x09, 0x41, b'b', 0xa1];
        assert_eq!(decode(&data).unwrap().get("b").and_then(Value::as_str), Some("b"));
        let data = [0xe3, 0x41, b'a', 0x40, 0x41, b'b', 0x70, 0x41, b'c', 0xa1];
        assert_eq!(decode(&data).unwrap().get("c").and_then(Value::as_str), Some("b"));
        // Same value, other type: its own entry (1 as an integer, then 1.0).
        let mut data = vec![0xe2, 0x41, b'a', 0x30, 0x01, 0x41, b'b', 0x36];
        data.extend_from_slice(&1.0f64.to_le_bytes());
        data.extend_from_slice(&[0x41, b'c', 0xa3]);
        let v = decode(&[&[0xe3][..], &data[1..]].concat()).unwrap();
        assert_eq!(v.get("c"), Some(&Value::Float(1.0)));
        assert!(decode(&[0xa5]).is_err());
        assert_eq!(decode(&[0xc1, 0x00]), Err(Error("a reference to nothing")));
    }

    #[test]
    fn malformed() {
        for bad in [&[][..], &[0x61, 0x05, b'a'], &[0xe1, 0x41], &[0xdf, 0x09], &[0x45, 0xff, 0xfe, 0, 0, 0], &[0x00]] {
            assert!(decode(bad).is_err(), "{bad:?}");
        }
        assert!(decode(&[0x09, 0x09]).is_err(), "trailing bytes");
        let deep = vec![0xd1; 100];
        assert_eq!(decode(&deep), Err(Error("nested too deep")));
        // A length far beyond the input doesn't allocate it.
        assert!(decode(&[0x94, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x7f]).is_err());
    }

    fn arb_value() -> impl Strategy<Value = Value> {
        let leaf = prop_oneof![
            Just(Value::Null),
            any::<bool>().prop_map(Value::Bool),
            any::<[u8; 16]>().prop_map(Value::Uuid),
            any::<i64>().prop_map(Value::Int),
            any::<f64>().prop_filter("NaN", |f| !f.is_nan()).prop_map(Value::Float),
            ".{0,40}".prop_map(Value::Str),
            prop::collection::vec(any::<u8>(), 0..300).prop_map(Value::Data),
        ];
        leaf.prop_recursive(4, 64, 20, |inner| {
            prop_oneof![
                prop::collection::vec(inner.clone(), 0..20).prop_map(Value::Array),
                prop::collection::vec((".{0,8}".prop_map(Value::Str), inner), 0..20).prop_map(Value::Dict),
            ]
        })
    }

    proptest! {
        #[test]
        fn round_trips(v in arb_value()) {
            prop_assert_eq!(decode(&encode(&v)).unwrap(), v);
        }

        #[test]
        fn any_bytes_never_panic(data in prop::collection::vec(any::<u8>(), 0..256)) {
            let _ = decode(&data);
        }
    }
}
