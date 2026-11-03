//! accept() that fails (out of file descriptors, say) tends to fail again at
//! once: retried in a tight loop it would spin a core and flood the journal.
//! So each failure pauses the accepting, from MIN doubling to MAX (back to
//! MIN after a success), and is logged at most once per LOG_EVERY, saying how
//! many failures that one line stands for.

use std::time::{Duration, Instant};

use tracing::warn;

const MIN: Duration = Duration::from_millis(10);
const MAX: Duration = Duration::from_secs(1);
const LOG_EVERY: Duration = Duration::from_secs(10);

#[derive(Debug, Default)]
pub struct AcceptBackoff {
    /// Zero: no failure since the last success.
    delay: Duration,
    logged: Option<Instant>,
    unlogged: u64,
}

impl AcceptBackoff {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn succeeded(&mut self) {
        self.delay = Duration::ZERO;
    }

    /// A failed accept on `what`: logged (or counted); how long to pause
    /// before the next.
    pub fn failed(&mut self, what: &str, err: &std::io::Error) -> Duration {
        self.delay = if self.delay.is_zero() { MIN } else { (self.delay * 2).min(MAX) };
        let now = Instant::now();
        if self.logged.is_none_or(|at| now.duration_since(at) >= LOG_EVERY) {
            match std::mem::take(&mut self.unlogged) {
                0 => warn!("{what}: accept failed: {err}"),
                n => warn!("{what}: accept failed: {err} (and {n} more times since the last warning)"),
            }
            self.logged = Some(now);
        } else {
            self.unlogged += 1;
        }
        self.delay
    }

    /// failed(), then the pause.
    pub async fn pause(&mut self, what: &str, err: &std::io::Error) {
        tokio::time::sleep(self.failed(what, err)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pauses_double_up_to_a_second_and_reset_on_success() {
        let err = std::io::Error::other("EMFILE");
        let mut b = AcceptBackoff::new();
        assert_eq!(b.failed("t", &err), MIN);
        assert_eq!(b.failed("t", &err), MIN * 2);
        for _ in 0..20 {
            b.failed("t", &err);
        }
        assert_eq!(b.failed("t", &err), MAX);
        assert!(b.unlogged > 0, "warned once, the rest counted");
        b.succeeded();
        assert_eq!(b.failed("t", &err), MIN);
    }
}
