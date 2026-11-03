//! The remote's touch area as arrow keys, the way an Apple TV moves its
//! focus: the iPhone remote of iOS 27 has no D-pad, only the touch area
//! (windows-apple-remote's notes; atv-core turns swipes into directions
//! too). Our own gesture design:
//!
//! - every `step` of travel along the stronger axis is one arrow, while the
//!   finger moves (a long drag walks several tiles, as on tvOS);
//! - a finger that has moved and then rests near the edge it moved towards
//!   repeats that arrow every `repeat_ms`, after `edge_delay_ms` (long
//!   lists);
//! - a short touch that hardly moved is a tap (OK). The remote also sends a
//!   tap as the Select button; the session keeps the two from both counting.
//!
//! The touch area is 1000 × 1000 (pyatv: TOUCHPAD_WIDTH/HEIGHT), y down.
//! Phases (`_tPh`): 1 press, 2 or 3 move (iOS 27 sends 2, pyatv 3),
//! 4 release, 5 click (pyatv's tap, after the Select button: nothing).

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Dir {
    Up,
    Down,
    Left,
    Right,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Gesture {
    Arrow(Dir),
    Tap,
}

#[derive(Debug, Clone, Copy)]
pub struct Tuning {
    /// Travel (of 1000) per arrow.
    pub step: f64,
    /// A tap moves less than this, in less than tap_ms.
    pub tap_travel: f64,
    pub tap_ms: u64,
    /// "Near the edge": this close to it.
    pub edge: f64,
    pub edge_delay_ms: u64,
    pub repeat_ms: u64,
}

impl Default for Tuning {
    fn default() -> Self {
        Self { step: 160.0, tap_travel: 40.0, tap_ms: 400, edge: 120.0, edge_delay_ms: 450, repeat_ms: 160 }
    }
}

struct Touch {
    origin: (f64, f64),
    anchor: (f64, f64),
    last: (f64, f64),
    start: u64,
    moved: bool,
    dir: Option<Dir>,
    /// When the finger last moved (more than a jitter).
    still_since: u64,
    repeated_at: Option<u64>,
}

pub struct Pad {
    tuning: Tuning,
    touch: Option<Touch>,
}

impl Pad {
    pub fn new(tuning: Tuning) -> Self {
        Self { tuning, touch: None }
    }

    pub fn active(&self) -> bool {
        self.touch.is_some()
    }

    /// One `_hidT` event at `now` (ms).
    pub fn event(&mut self, phase: i64, x: f64, y: f64, now: u64) -> Vec<Gesture> {
        let (x, y) = (x.clamp(0.0, 1000.0), y.clamp(0.0, 1000.0));
        match phase {
            1 => {
                self.touch = Some(Touch {
                    origin: (x, y),
                    anchor: (x, y),
                    last: (x, y),
                    start: now,
                    moved: false,
                    dir: None,
                    still_since: now,
                    repeated_at: None,
                });
                Vec::new()
            }
            2 | 3 => self.moved(x, y, now),
            4 => {
                let mut out = self.moved(x, y, now);
                if let Some(t) = self.touch.take() {
                    let travel = (x - t.origin.0).abs().max((y - t.origin.1).abs());
                    if !t.moved && travel < self.tuning.tap_travel && now.saturating_sub(t.start) < self.tuning.tap_ms {
                        out.push(Gesture::Tap);
                    }
                }
                out
            }
            _ => Vec::new(),
        }
    }

    fn moved(&mut self, x: f64, y: f64, now: u64) -> Vec<Gesture> {
        let step = self.tuning.step;
        let Some(t) = self.touch.as_mut() else { return Vec::new() };
        let mut out = Vec::new();
        if (x - t.last.0).abs().max((y - t.last.1).abs()) > 3.0 {
            t.still_since = now;
            t.repeated_at = None;
        }
        t.last = (x, y);
        loop {
            let (dx, dy) = (x - t.anchor.0, y - t.anchor.1);
            let dir = if dx.abs() >= dy.abs() {
                if dx.abs() < step {
                    break;
                }
                t.anchor.0 += step * dx.signum();
                if dx > 0.0 { Dir::Right } else { Dir::Left }
            } else {
                if dy.abs() < step {
                    break;
                }
                t.anchor.1 += step * dy.signum();
                if dy > 0.0 { Dir::Down } else { Dir::Up }
            };
            // A turn starts afresh on the other axis.
            if t.dir.is_some_and(|d| axis(d) != axis(dir)) {
                t.anchor = match axis(dir) {
                    Axis::X => (t.anchor.0, y),
                    Axis::Y => (x, t.anchor.1),
                };
            }
            t.moved = true;
            t.dir = Some(dir);
            out.push(Gesture::Arrow(dir));
        }
        out
    }

    /// Time passing: the edge repeat. Call every few tens of ms while a
    /// touch is active.
    pub fn tick(&mut self, now: u64) -> Option<Gesture> {
        let tu = self.tuning;
        let t = self.touch.as_mut()?;
        let dir = t.dir?;
        let (x, y) = t.last;
        let at_edge = match dir {
            Dir::Left => x <= tu.edge,
            Dir::Right => x >= 1000.0 - tu.edge,
            Dir::Up => y <= tu.edge,
            Dir::Down => y >= 1000.0 - tu.edge,
        };
        if !at_edge || now.saturating_sub(t.still_since) < tu.edge_delay_ms {
            return None;
        }
        if t.repeated_at.is_some_and(|at| now.saturating_sub(at) < tu.repeat_ms) {
            return None;
        }
        t.repeated_at = Some(now);
        Some(Gesture::Arrow(dir))
    }
}

#[derive(PartialEq)]
enum Axis {
    X,
    Y,
}

fn axis(d: Dir) -> Axis {
    match d {
        Dir::Left | Dir::Right => Axis::X,
        Dir::Up | Dir::Down => Axis::Y,
    }
}

#[cfg(test)]
mod tests {
    use super::Dir::*;
    use super::Gesture::*;
    use super::*;

    /// A straight swipe from a to b in `steps` events, 20 ms apart.
    fn swipe(pad: &mut Pad, a: (f64, f64), b: (f64, f64), steps: u32, t0: u64) -> Vec<Gesture> {
        let mut out = pad.event(1, a.0, a.1, t0);
        for i in 1..=steps {
            let f = f64::from(i) / f64::from(steps);
            out.extend(pad.event(3, a.0 + (b.0 - a.0) * f, a.1 + (b.1 - a.1) * f, t0 + u64::from(i) * 20));
        }
        out.extend(pad.event(4, b.0, b.1, t0 + u64::from(steps + 1) * 20));
        out
    }

    #[test]
    fn swipes_are_arrows_by_distance() {
        let mut pad = Pad::new(Tuning::default());
        assert_eq!(swipe(&mut pad, (500.0, 500.0), (700.0, 520.0), 5, 0), [Arrow(Right)]);
        assert_eq!(swipe(&mut pad, (500.0, 500.0), (480.0, 100.0), 10, 1000), [Arrow(Up), Arrow(Up)]);
        assert_eq!(swipe(&mut pad, (900.0, 500.0), (100.0, 500.0), 20, 2000), [Arrow(Left); 5]);
        assert_eq!(swipe(&mut pad, (500.0, 200.0), (500.0, 380.0), 3, 3000), [Arrow(Down)]);
        // Too short for an arrow, too long for a tap: nothing.
        assert_eq!(swipe(&mut pad, (500.0, 500.0), (600.0, 500.0), 3, 4000), []);
        assert!(!pad.active());
    }

    #[test]
    fn taps() {
        let mut pad = Pad::new(Tuning::default());
        assert_eq!(swipe(&mut pad, (500.0, 500.0), (510.0, 505.0), 2, 0), [Tap]);
        // Held too long: not a tap.
        pad.event(1, 500.0, 500.0, 1000);
        assert_eq!(pad.event(4, 500.0, 500.0, 1600), []);
        // pyatv's click event (phase 5) and a move without a press: nothing.
        assert_eq!(pad.event(5, 1000.0, 1000.0, 2000), []);
        assert_eq!(pad.event(3, 100.0, 100.0, 2000), []);
    }

    #[test]
    fn a_turn_and_the_edge_repeat() {
        let mut pad = Pad::new(Tuning::default());
        pad.event(1, 500.0, 500.0, 0);
        assert_eq!(pad.event(3, 670.0, 500.0, 20), [Arrow(Right)]);
        assert_eq!(pad.event(3, 670.0, 680.0, 40), [Arrow(Down)]);
        // On to the bottom edge, then resting there.
        assert_eq!(pad.event(3, 670.0, 950.0, 60), [Arrow(Down)]);
        assert_eq!(pad.tick(100), None, "not yet");
        assert_eq!(pad.tick(520), Some(Arrow(Down)));
        assert_eq!(pad.tick(560), None, "repeat_ms apart");
        assert_eq!(pad.tick(690), Some(Arrow(Down)));
        // Moving again stops the repeat.
        assert_eq!(pad.event(3, 670.0, 900.0, 700), []);
        assert_eq!(pad.tick(800), None);
        // Resting away from the edge: nothing.
        let mut pad = Pad::new(Tuning::default());
        pad.event(1, 300.0, 500.0, 0);
        pad.event(3, 470.0, 500.0, 20);
        assert_eq!(pad.tick(2000), None);
        pad.event(4, 470.0, 500.0, 2020);
        assert_eq!(pad.tick(3000), None);
    }
}
