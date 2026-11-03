//! Reading a line from someone who may never send a newline.

use std::io;

use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncReadExt};

/// How `read_line_with` bounds a line and ends.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LineLimit {
    /// At most this many bytes before the newline (or with it, below).
    pub max: usize,
    /// The newline counts towards `max`: a line is at most `max` bytes with
    /// its newline (`max` without one, a last line). tvd's and speakerd's
    /// sockets.
    pub newline_counts: bool,
    /// A last line without a newline before the end of the stream is a line
    /// too: Ok(true) with it in `buf` (no newline), and the next call (`buf`
    /// cleared) Ok(false). Otherwise Ok(false) with it left in `buf`.
    pub last_line: bool,
}

impl LineLimit {
    /// `max` bytes before the newline; a last line without one isn't a line
    /// (as `read_line`).
    pub const fn new(max: usize) -> Self {
        Self { max, newline_counts: false, last_line: false }
    }

    /// The newline counts towards `max`.
    pub const fn newline_counts(self) -> Self {
        Self { newline_counts: true, ..self }
    }

    /// A last line without a newline is a line.
    pub const fn last_line(self) -> Self {
        Self { last_line: true, ..self }
    }
}

/// Reads up to and including the next newline into `buf`, appending to what
/// it holds (the line so far), never more than `max` bytes before the
/// newline. Ok(true): `buf` holds a whole line, its newline last. Ok(false):
/// the end of the stream (`buf` may hold a last line without a newline).
/// Err(InvalidData): the line is longer than `max`, read no further than
/// that.
///
/// Cancel-safe: cancelled (a select! or a timeout), what was read so far
/// stays in `buf`, and calling again with it carries on.
pub async fn read_line<R: AsyncBufRead + Unpin>(reader: &mut R, buf: &mut Vec<u8>, max: usize) -> io::Result<bool> {
    read_line_with(reader, buf, LineLimit::new(max)).await
}

/// `read_line`, bounded and ended as `limit` says. Ok(true): a line in
/// `buf`, its newline last (or none: a last line, with `limit.last_line`).
pub async fn read_line_with<R: AsyncBufRead + Unpin>(
    reader: &mut R,
    buf: &mut Vec<u8>,
    limit: LineLimit,
) -> io::Result<bool> {
    let max = limit.max;
    loop {
        // Longer than max without a newline: too long either way.
        if buf.len() > max {
            return Err(too_long());
        }
        // The line's at most max bytes, its newline, and one more to tell a
        // line too long from one just long enough.
        let left = (max + 2 - buf.len()) as u64;
        let n = (&mut *reader).take(left).read_until(b'\n', buf).await?;
        if buf.last() == Some(&b'\n') {
            let len = if limit.newline_counts { buf.len() } else { buf.len() - 1 };
            return if len > max { Err(too_long()) } else { Ok(true) };
        }
        if n == 0 {
            // At most max: checked before this read, which added nothing.
            return Ok(limit.last_line && !buf.is_empty());
        }
    }
}

fn too_long() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "line too long")
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use proptest::prelude::*;
    use tokio::io::{AsyncWriteExt, BufReader};

    use super::*;

    fn runtime() -> tokio::runtime::Runtime {
        tokio::runtime::Builder::new_current_thread().enable_time().build().unwrap()
    }

    #[test]
    fn lines_limits_and_the_end() {
        runtime().block_on(async {
            let mut r = BufReader::new(&b"ab\ncde\nf"[..]);
            let mut buf = Vec::new();
            assert!(read_line(&mut r, &mut buf, 3).await.unwrap());
            assert_eq!(buf, b"ab\n");
            buf.clear();
            assert!(read_line(&mut r, &mut buf, 3).await.unwrap());
            assert_eq!(buf, b"cde\n", "exactly max is fine");
            buf.clear();
            assert!(!read_line(&mut r, &mut buf, 3).await.unwrap());
            assert_eq!(buf, b"f");
            let mut buf = Vec::new();
            let err = read_line(&mut BufReader::new(&b"abcd\n"[..]), &mut buf, 3).await.unwrap_err();
            assert_eq!(err.kind(), io::ErrorKind::InvalidData);
            // An endless line is cut off, not read for ever.
            let mut endless = BufReader::new(tokio::io::repeat(b'x'));
            assert!(read_line(&mut endless, &mut Vec::new(), 1000).await.is_err());
        });
    }

    #[test]
    fn a_line_cut_by_a_timeout_carries_on() {
        runtime().block_on(async {
            let (ours, mut theirs) = tokio::io::duplex(64);
            let mut r = BufReader::new(ours);
            let mut buf = Vec::new();
            theirs.write_all(b"hel").await.unwrap();
            let cut = tokio::time::timeout(Duration::from_millis(20), read_line(&mut r, &mut buf, 100)).await;
            assert!(cut.is_err());
            assert_eq!(buf, b"hel");
            theirs.write_all(b"lo\n").await.unwrap();
            assert!(read_line(&mut r, &mut buf, 100).await.unwrap());
            assert_eq!(buf, b"hello\n");
        });
    }

    /// Reads lines as `limit` says till the end or an error.
    async fn all(data: &[u8], capacity: usize, limit: LineLimit) -> (Vec<Vec<u8>>, Option<Vec<u8>>, bool) {
        let mut r = BufReader::with_capacity(capacity, data);
        let mut got = Vec::new();
        loop {
            let mut buf = Vec::new();
            match read_line_with(&mut r, &mut buf, limit).await {
                Ok(true) => got.push(buf),
                Ok(false) => return (got, Some(buf).filter(|b| !b.is_empty()), false),
                Err(e) => {
                    assert_eq!(e.kind(), io::ErrorKind::InvalidData);
                    return (got, None, true);
                }
            }
        }
    }

    #[test]
    fn the_newline_counted() {
        runtime().block_on(async {
            let limit = LineLimit::new(3).newline_counts();
            let (got, rest, failed) = all(b"ab\ncde", 64, limit).await;
            assert_eq!((got, rest, failed), (vec![b"ab\n".to_vec()], Some(b"cde".to_vec()), false));
            let (got, _, failed) = all(b"ab\nabc\n", 64, limit).await;
            assert_eq!((got, failed), (vec![b"ab\n".to_vec()], true), "max and a newline: too long");
            let (got, _, failed) = all(b"abcd", 64, limit).await;
            assert_eq!((got.len(), failed), (0, true));
            // Not counted: max before the newline.
            let (got, _, failed) = all(b"abc\n", 64, LineLimit::new(3)).await;
            assert_eq!((got, failed), (vec![b"abc\n".to_vec()], false));
        });
    }

    #[test]
    fn a_last_line_without_a_newline() {
        runtime().block_on(async {
            let limit = LineLimit::new(3).last_line();
            let (got, rest, failed) = all(b"ab\ncde", 64, limit).await;
            assert_eq!((got, rest, failed), (vec![b"ab\n".to_vec(), b"cde".to_vec()], None, false));
            let (got, _, failed) = all(b"ab\ncdef", 64, limit).await;
            assert_eq!((got.len(), failed), (1, true), "too long, newline or not");
            let (got, rest, _) = all(b"ab\n", 64, limit).await;
            assert_eq!((got.len(), rest), (1, None), "nothing after the last newline: no line");
            // Both, as tvd's and speakerd's sockets: max without a newline.
            let both = LineLimit::new(3).newline_counts().last_line();
            let (got, _, failed) = all(b"ab\nabc", 64, both).await;
            assert_eq!((got, failed), (vec![b"ab\n".to_vec(), b"abc".to_vec()], false));
            let (got, _, failed) = all(b"abc\n", 64, both).await;
            assert_eq!((got.len(), failed), (0, true));
        });
    }

    proptest! {
        #![proptest_config(ProptestConfig::with_cases(256))]

        /// Any bytes, any buffer size, any options: the lines as split by
        /// newline, each at most max (counting the newline or not), or an
        /// error once one is longer; the last one, without a newline, as a
        /// line or left over.
        #[test]
        fn any_bytes(
            data in prop::collection::vec(prop_oneof![Just(b'\n'), any::<u8>()], 0..512),
            capacity in 1usize..64,
            max in 0usize..64,
            newline_counts: bool,
            last_line: bool,
        ) {
            runtime().block_on(async {
                let limit = LineLimit { max, newline_counts, last_line };
                let (got, rest, failed) = all(&data, capacity, limit).await;
                let mut want: Vec<Vec<u8>> = data.split_inclusive(|b| *b == b'\n').map(<[u8]>::to_vec).collect();
                let fits = |l: &Vec<u8>| {
                    let ends = l.last() == Some(&b'\n');
                    l.len() - usize::from(ends && !newline_counts) <= max
                };
                if failed {
                    let first_long = want.iter().position(|l| !fits(l)).expect("failed on a short line");
                    assert_eq!(got, want[..first_long].to_vec());
                } else {
                    assert!(want.iter().all(fits));
                    let unterminated = want.last().is_some_and(|l| l.last() != Some(&b'\n'));
                    let left = if unterminated && !last_line { want.pop() } else { None };
                    assert_eq!(got, want);
                    assert_eq!(rest, left);
                }
            });
        }
    }
}
