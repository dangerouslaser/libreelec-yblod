//! Which part of an output buffer a frame has to write again.
//!
//! A tunnel picture is the film (in its rectangle of the canvas), the overlay
//! over everything, and the metadata packets in the first rows. When the
//! overlay is the whole desktop (docs/research/media-following-colour.md) and
//! only the film moves, rewriting all 8.3 M pixels every frame costs 20 ms or
//! more on small GPUs. Each output buffer keeps what it was last written
//! with; a frame then rewrites only the packet rows, the film's rectangle
//! (where it is now and where it was in that buffer) and whatever the overlay
//! changed since that buffer's revision ("buffer age", as compositors do).
//! Anything else that changed (the pack variant, the colour coefficients, the
//! letterbox, a new buffer) rewrites it all. DVVK_DAMAGE=0 turns it off.

use std::collections::VecDeque;

pub type Rect = [u32; 4]; // x0, y0, x1, y1 (exclusive)

/// The pack's workgroup: 128 pixels by 4 rows.
pub const WG_W: u32 = 128;
pub const WG_H: u32 = 4;
const HISTORY: usize = 32;
// above this share of the canvas, one full dispatch is cheaper than several
const FULL_SHARE: f64 = 0.95;

#[derive(Clone, Copy, Default)]
struct Slot {
    valid: bool,
    rev: u64,
    key: u64,
    film: Option<Rect>,
}

pub struct Damage {
    enabled: bool,
    rev: u64,
    // (revision, what changed with it; None: everything)
    log: VecDeque<(u64, Option<Vec<Rect>>)>,
    pending: Option<Vec<Rect>>,
    slots: Vec<Slot>,
    canvas: (u32, u32),
    pub stats: (u64, u64), // frames, of which partial
    pub area: f64,         // sum of the written share of the canvas
}

fn union(a: Rect, b: Rect) -> Rect {
    [a[0].min(b[0]), a[1].min(b[1]), a[2].max(b[2]), a[3].max(b[3])]
}

impl Damage {
    pub fn new(canvas: (u32, u32), enabled: bool) -> Damage {
        Damage {
            enabled,
            rev: 1,
            log: VecDeque::new(),
            pending: None,
            slots: Vec::new(),
            canvas,
            stats: (0, 0),
            area: 0.0,
        }
    }

    /// Forget the rectangles set_pending gave: the next change is everywhere.
    pub fn clear_pending(&mut self) {
        self.pending = None;
    }

    /// The overlay's next change covers just these rectangles (x, y, w, h).
    pub fn set_pending(&mut self, rects: &[[u32; 4]]) {
        let (cw, ch) = self.canvas;
        self.pending = Some(
            rects
                .iter()
                .map(|r| {
                    [
                        r[0].min(cw),
                        r[1].min(ch),
                        (r[0].saturating_add(r[2])).min(cw),
                        (r[1].saturating_add(r[3])).min(ch),
                    ]
                })
                .filter(|r| r[2] > r[0] && r[3] > r[1])
                .collect(),
        );
    }

    /// The overlay changed: in `rect` only, or everywhere (None), unless the
    /// caller said where with set_pending.
    pub fn changed(&mut self, rect: Option<Rect>) {
        let rects = match self.pending.take() {
            Some(p) => Some(p),
            None => rect.map(|r| vec![r]),
        };
        self.rev += 1;
        self.log.push_back((self.rev, rects));
        while self.log.len() > HISTORY {
            self.log.pop_front();
        }
    }

    /// An output buffer was (re)attached: its contents are unknown.
    pub fn invalidate(&mut self, slot: usize) {
        if let Some(s) = self.slots.get_mut(slot) {
            s.valid = false;
        }
    }

    /// The rectangles to write into output `slot` this frame (workgroup
    /// aligned), or None for the whole canvas. `key` sums up everything else
    /// the picture depends on; `film` is the film's rectangle; `packet_rows`
    /// how many rows the metadata packets take.
    pub fn plan(
        &mut self,
        slot: usize,
        key: u64,
        film: Option<Rect>,
        packet_rows: u32,
        force_full: bool,
    ) -> Option<Vec<Rect>> {
        if self.slots.len() <= slot {
            self.slots.resize(slot + 1, Slot::default());
        }
        let s = self.slots[slot];
        self.slots[slot] = Slot { valid: true, rev: self.rev, key, film };
        self.stats.0 += 1;
        if !self.enabled || force_full || !s.valid || s.key != key {
            self.area += 1.0;
            return None;
        }
        let mut rects: Vec<Rect> = Vec::new();
        if s.rev != self.rev {
            // every overlay change since this buffer was written
            let Some(first) = self.log.front() else {
                self.area += 1.0;
                return None;
            };
            if first.0 > s.rev + 1 {
                self.area += 1.0;
                return None; // too old: not in the log any more
            }
            for (rev, change) in &self.log {
                if *rev <= s.rev {
                    continue;
                }
                match change {
                    Some(r) => rects.extend_from_slice(r),
                    None => {
                        self.area += 1.0;
                        return None;
                    }
                }
            }
        }
        if film != s.film {
            rects.extend(s.film);
            rects.extend(film);
        } else if let Some(f) = film {
            rects.push(f);
        }
        if packet_rows > 0 {
            rects.push([0, 0, self.canvas.0, packet_rows]);
        }
        // a pixel's chroma blends its neighbours: 2 pixels around, then the
        // workgroup grid
        let (cw, ch) = self.canvas;
        let mut aligned: Vec<Rect> = rects
            .into_iter()
            .filter(|r| r[2] > r[0] && r[3] > r[1])
            .map(|r| {
                [
                    r[0].saturating_sub(2) / WG_W * WG_W,
                    r[1].saturating_sub(2) / WG_H * WG_H,
                    (r[2] + 2).min(cw).div_ceil(WG_W) * WG_W,
                    (r[3] + 2).min(ch).div_ceil(WG_H) * WG_H,
                ]
            })
            .collect();
        // merge overlapping rectangles (few: the film, the packets, a
        // handful of damage)
        let mut merged = true;
        while merged {
            merged = false;
            'outer: for i in 0..aligned.len() {
                for j in i + 1..aligned.len() {
                    let (a, b) = (aligned[i], aligned[j]);
                    if a[0] <= b[2] && b[0] <= a[2] && a[1] <= b[3] && b[1] <= a[3] {
                        aligned[i] = union(a, b);
                        aligned.remove(j);
                        merged = true;
                        break 'outer;
                    }
                }
            }
        }
        let total: u64 = aligned.iter().map(|r| (r[2] - r[0]) as u64 * (r[3] - r[1]) as u64).sum();
        let share = total as f64 / (cw as f64 * ch as f64);
        if share > FULL_SHARE {
            self.area += 1.0;
            return None;
        }
        self.stats.1 += 1;
        self.area += share;
        Some(aligned)
    }
}

/// The tiles (`tile` pixels square, `tiles` across and down) the pixel
/// rectangles touch, as few tile rectangles (x0, y0, x1, y1 in tiles):
/// overlapping ones merged into their union, and the whole grid once they
/// cover most of it. A tile may come out in two rectangles only if the
/// caller's use is idempotent per tile (cb1_tiles.comp's is).
pub fn tile_rects(rects: &[Rect], tile: u32, tiles: (u32, u32)) -> Vec<Rect> {
    let all = vec![[0, 0, tiles.0, tiles.1]];
    let mut out: Vec<Rect> = rects
        .iter()
        .filter(|r| r[2] > r[0] && r[3] > r[1])
        .map(|r| {
            [
                (r[0] / tile).min(tiles.0),
                (r[1] / tile).min(tiles.1),
                r[2].div_ceil(tile).min(tiles.0),
                r[3].div_ceil(tile).min(tiles.1),
            ]
        })
        .filter(|r| r[2] > r[0] && r[3] > r[1])
        .collect();
    let mut merged = true;
    while merged {
        merged = false;
        'outer: for i in 0..out.len() {
            for j in i + 1..out.len() {
                let (a, b) = (out[i], out[j]);
                if a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3] {
                    out[i] = union(a, b);
                    out.remove(j);
                    merged = true;
                    break 'outer;
                }
            }
        }
    }
    let area: u64 = out.iter().map(|r| (r[2] - r[0]) as u64 * (r[3] - r[1]) as u64).sum();
    if area as f64 > FULL_SHARE * tiles.0 as f64 * tiles.1 as f64 {
        all
    } else {
        out
    }
}

#[cfg(test)]
mod tile_tests {
    use super::*;
    #[test]
    fn rects_cover_their_tiles_and_merge() {
        let grid = (120, 68);
        assert!(tile_rects(&[], 32, grid).is_empty());
        assert!(tile_rects(&[[5, 5, 5, 9]], 32, grid).is_empty());
        assert_eq!(tile_rects(&[[1800, 200, 2056, 456]], 32, grid), vec![[56, 6, 65, 15]]);
        // overlapping: one union; apart: kept apart
        assert_eq!(tile_rects(&[[0, 0, 40, 40], [33, 33, 70, 70]], 32, grid), vec![[0, 0, 3, 3]]);
        assert_eq!(tile_rects(&[[0, 0, 32, 32], [64, 64, 96, 96]], 32, grid).len(), 2);
        // clamped to the grid; most of it: all of it
        assert_eq!(tile_rects(&[[3800, 2100, 5000, 5000]], 32, grid), vec![[118, 65, 120, 68]]);
        assert_eq!(tile_rects(&[[0, 0, 3840, 2100]], 32, grid), vec![[0, 0, 120, 68]]);
        assert_eq!(tile_rects(&[[0, 0, 3840, 2000]], 32, grid), vec![[0, 0, 120, 63]]);
        // every pixel of every input lies in an output tile
        let input = [[100, 100, 300, 130], [290, 120, 900, 600], [3000, 10, 3001, 11]];
        let out = tile_rects(&input, 32, grid);
        for r in input {
            for (x, y) in [(r[0], r[1]), (r[2] - 1, r[3] - 1)] {
                assert!(out.iter().any(|t| x / 32 >= t[0] && x / 32 < t[2] && y / 32 >= t[1] && y / 32 < t[3]));
            }
        }
    }
}
