//! Retrying something that failed (a speaker, a TV, a subscription): the
//! wait doubles from `min` up to `max`, and is back to `min` after a success.

use std::time::Duration;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Backoff {
    min: Duration,
    max: Duration,
    next: Duration,
}

impl Backoff {
    pub fn new(min: Duration, max: Duration) -> Self {
        Self { min, max, next: min }
    }

    /// How long to wait after this failure (and the next one waits twice
    /// as long, up to `max`).
    pub fn failed(&mut self) -> Duration {
        let wait = self.next;
        self.next = (self.next * 2).min(self.max);
        wait
    }

    /// It worked: the next failure waits `min` again.
    pub fn reset(&mut self) {
        self.next = self.min;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn doubles_up_to_max_and_resets() {
        let s = Duration::from_secs;
        let mut b = Backoff::new(s(2), s(10));
        assert_eq!([b.failed(), b.failed(), b.failed(), b.failed(), b.failed()], [s(2), s(4), s(8), s(10), s(10)]);
        b.reset();
        assert_eq!(b.failed(), s(2));
    }
}
