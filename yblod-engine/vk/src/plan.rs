//! Rust view of yblod/plan.h (the CPU half of a frame, done by yblod's code).

pub const ROUTE_DUAL: u32 = 1;
pub const ROUTE_SINGLE: u32 = 2;
pub const ROUTE_PIECEWISE: u32 = 3;
pub const CHROMA_POLY: u32 = 0;
pub const CHROMA_MMR128: u32 = 1;
pub const CHROMA_MMR96: u32 = 2;
pub const CHROMA_MMR64_LUT: u32 = 3;
pub const PACK_SITED: u32 = 0;
pub const PACK_422: u32 = 1;
pub const PACK_RESIZED: u32 = 2;
/// dvvk_plan_in.el_scaler (include/dvvk_plan.h, ABI 3).
pub const EL_ANNEXB: u32 = 1;
pub const EL_BILINEAR: u32 = 2;
/// dvvk_plan.el_method, the shaders' encoding.
pub const EL_METHOD_ANNEXB: u32 = 0;
pub const EL_METHOD_BILINEAR: u32 = 1;

#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct PlanIn {
    pub width: u32,
    pub height: u32,
    pub x: u32,
    pub y: u32,
    pub dw: u32,
    pub dh: u32,
    pub chroma_top_left: u32,
    pub has_el: u32,
    pub nv12: u32,
    pub el_scaler: u32,
    pub fel: u32,
    pub packet_id: u32,
    pub refresh: u32,
    pub overlay: u32,
    pub overlay_visible_before: u32,
    pub pts: i64,
    pub rgb_to_lms: [f64; 9],
    pub white_nits: f64,
    pub cb1_contract: u32,
    /// include/dvvk_plan.h DVVK_DM_*: CM4 and L2 options for the film's
    /// metadata (0: as the stream has it).
    pub dm_options: u32,
}

#[repr(C)]
pub struct Plan {
    pub mmr_lut: [[[i64; 1024]; 3]; 2],
    pub reshape: [u8; 4544],
    pub residual: [[i32; 1024]; 3],
    pub mmr_params: [[u32; 96]; 2],
    pub route: u32,
    pub width: u32,
    pub height: u32,
    pub el_scale: u32,
    /// EL_METHOD_*: how a half-size EL is upsampled.
    pub el_method: u32,
    pub chroma_phase: u32,
    pub chroma_kind: [u32; 2],
    pub dual: u32,
    pub horizontal_fused: u32,
    pub equal: u32,
    pub row_first: u32,
    pub row_last: u32,
    pub layout: u32,
    pub sampling: u32,
    pub depth: u32,
    pub order2: u32,
    pub narrow_mask: [u32; 4],
    pub pack: u32,
    pub active: [u32; 4],
    pub black: [u32; 4],
    pub placement: [u32; 4],
    pub top_left: u32,
    pub source_w: u32,
    pub source_h: u32,
    pub packet_count: u32,
    pub overlay_visible: u32,
    pub chroma_filter: u32,
    pub tables_generation: u32,
    /// DVVK_CM4_STATUS_* | L2 blocks removed << 8.
    pub dm_status: u32,
    pub reserved: [u32; 4],
    pub gui_coeff: [f32; 32],
    pub mapping: [u16; 1024],
    pub chroma_mapping: [[u16; 1024]; 2],
    pub single_table: [[u16; 1024]; 3],
    pub luma_table: [u16; 1024],
    pub packets: [u8; 640],
}

/// yblod/plan.h dvvk_plan_desktop: static graphics display management for
/// frames the desktop fills (0 fields: the defaults).
#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct PlanDesktop {
    pub enabled: u32,
    pub min_pq: u32,
    pub max_pq: u32,
    pub avg_pq: u32,
}

impl PlanDesktop {
    /// Desktop mode, with DVVK_DESKTOP_L1="MIN,MAX,AVG" (12-bit PQ codes, 0 for
    /// a default) to try other values (docs/research/media-following-colour.md M4).
    pub fn on(l1: Option<[u32; 3]>) -> PlanDesktop {
        let mut d = PlanDesktop { enabled: 1, ..Default::default() };
        if let Some(f) = l1 {
            (d.min_pq, d.max_pq, d.avg_pq) = (f[0], f[1], f[2]);
        }
        d
    }
}

#[repr(C)]
struct RawPlanState {
    _opaque: [u8; 0],
}

/// include/dvvk_plan.h dvvk_plan_state: what one engine's planning keeps
/// from frame to frame (CB1's packet ids, the last tables per route).
pub struct PlanState(std::ptr::NonNull<RawPlanState>);

impl PlanState {
    pub fn new() -> Option<PlanState> {
        std::ptr::NonNull::new(unsafe { dvvk_plan_state_new() }).map(PlanState)
    }

    /// As a new engine's (dvvk_reset: a seek, a new file).
    pub fn reset(&mut self) {
        unsafe { dvvk_plan_state_reset(self.0.as_ptr()) };
    }
}

impl Drop for PlanState {
    fn drop(&mut self) {
        unsafe { dvvk_plan_state_free(self.0.as_ptr()) };
    }
}

extern "C" {
    fn dvvk_plan_frame_state(
        input: *const PlanIn,
        desktop: *const PlanDesktop,
        state: *mut RawPlanState,
        metadata: *const u8,
        size: usize,
        out: *mut Plan,
    ) -> i32;
    fn dvvk_plan_state_new() -> *mut RawPlanState;
    fn dvvk_plan_state_reset(state: *mut RawPlanState);
    fn dvvk_plan_state_free(state: *mut RawPlanState);
    fn dvvk_plan_layout(out: *mut usize);
}

impl Plan {
    pub fn boxed() -> Box<Plan> {
        // ~100 KB: zeroed on the heap, never on the stack.
        unsafe { Box::new_zeroed().assume_init() }
    }

    /// yblod's planning for one frame; 0 or a dv_status.
    pub fn fill(
        &mut self,
        input: &PlanIn,
        desktop: Option<&PlanDesktop>,
        state: &mut PlanState,
        metadata: &[u8],
    ) -> i32 {
        let d = desktop.map_or(std::ptr::null(), |d| d as *const PlanDesktop);
        unsafe { dvvk_plan_frame_state(input, d, state.0.as_ptr(), metadata.as_ptr(), metadata.len(), self) }
    }
}

/// The C and Rust layouts agree.
pub fn layout_matches() -> bool {
    let mut c = [0usize; 6];
    unsafe { dvvk_plan_layout(c.as_mut_ptr()) };
    let r = [
        std::mem::size_of::<Plan>(),
        std::mem::offset_of!(Plan, residual),
        std::mem::offset_of!(Plan, route),
        std::mem::offset_of!(Plan, mapping),
        std::mem::offset_of!(Plan, packets),
        std::mem::offset_of!(Plan, packet_count),
    ];
    c == r
}

#[cfg(test)]
mod tests {
    //! yblod/plan.c's CPU side, golden: packetisation and its CRC, CB1's
    //! metadata order, packet ids and the letterbox row window.
    use super::*;

    extern "C" {
        fn dvvk_test_packetize(dm: *const u8, bytes: usize, id: u32, out: *mut u8) -> u32;
        fn dvvk_test_cb1_wire(dm: *mut u8, bytes: *mut usize) -> i32;
        fn dvvk_test_packet_id(
            state: *mut RawPlanState,
            contract: i32,
            player: u32,
            dm: *const u8,
            bytes: usize,
        ) -> u32;
        fn dvvk_test_row_window(first: u32, last: u32, h: u32, out: *mut u32);
    }

    /// CRC-32/MPEG-2 (poly 0x04c11db7, init ~0, no reflection, no xor out).
    fn crc(data: &[u8]) -> u32 {
        let mut v = u32::MAX;
        for &b in data {
            v ^= (b as u32) << 24;
            for _ in 0..8 {
                v = if v & 0x8000_0000 != 0 { (v << 1) ^ 0x04c1_1db7 } else { v << 1 };
            }
        }
        v
    }

    fn packetize(dm: &[u8], id: u32) -> (u32, [u8; 640]) {
        let mut out = [0u8; 640];
        let n = unsafe { dvvk_test_packetize(dm.as_ptr(), dm.len(), id, out.as_mut_ptr()) };
        (n, out)
    }

    #[test]
    fn crc_is_mpeg2() {
        assert_eq!(crc(b"123456789"), 0x0376_e6e7);
    }

    #[test]
    fn packets() {
        let dm: Vec<u8> = (0..400u32).map(|i| (i * 7 + 3) as u8).collect();
        for (bytes, count) in [(1, 1), (119, 1), (120, 2), (240, 2), (241, 3), (361, 3), (362, 4), (400, 4)] {
            let (n, out) = packetize(&dm[..bytes], 5);
            assert_eq!(n, count, "{bytes} bytes");
            let mut payload = Vec::new();
            for i in 0..n as usize {
                let p = &out[i * 128..i * 128 + 128];
                let kind = if n == 1 {
                    0
                } else if i == 0 {
                    1
                } else if i + 1 == n as usize {
                    3
                } else {
                    2
                };
                assert_eq!(p[0], kind << 6);
                assert_eq!(p[1], 0x55);
                let start = if i == 0 { 5 } else { 3 };
                if i == 0 {
                    assert_eq!(((p[3] as usize) << 8) | p[4] as usize, bytes);
                }
                payload.extend_from_slice(&p[start..124]);
                assert_eq!(u32::from_be_bytes([p[124], p[125], p[126], p[127]]), crc(&p[..124]));
            }
            assert_eq!(&payload[..bytes], &dm[..bytes]);
            assert!(payload[bytes..].iter().all(|&b| b == 0));
            assert!(out[n as usize * 128..].iter().all(|&b| b == 0));
        }
        // golden: a fixed payload's packet (computed apart from plan.c), and a
        // whole packet with its CRC checks to 0 (CRC-32/MPEG-2's residue)
        let (_, out) = packetize(&dm[..119], 0);
        assert_eq!(u32::from_be_bytes([out[124], out[125], out[126], out[127]]), 0x90dc_062d);
        assert_eq!(crc(&out[..128]), 0);
    }

    /// A metadata payload: 71 header bytes and these (level, length) blocks.
    fn payload(blocks: &[(u8, u32)]) -> Vec<u8> {
        let mut dm: Vec<u8> = (0..71u8).collect();
        dm[70] = blocks.len() as u8;
        for (n, &(level, len)) in blocks.iter().enumerate() {
            dm.extend_from_slice(&len.to_be_bytes());
            dm.push(level);
            dm.extend((0..len).map(|i| (n as u32 * 16 + i) as u8));
        }
        dm
    }

    fn wire(dm: &[u8]) -> Option<Vec<u8>> {
        let mut buf = [0u8; 512];
        buf[..dm.len()].copy_from_slice(dm);
        let mut bytes = dm.len();
        (unsafe { dvvk_test_cb1_wire(buf.as_mut_ptr(), &mut bytes) } == 0).then(|| buf[..bytes].to_vec())
    }

    fn levels(dm: &[u8]) -> Vec<u8> {
        let mut at = 71;
        let mut v = Vec::new();
        for _ in 0..dm[70] {
            let len = u32::from_be_bytes([dm[at], dm[at + 1], dm[at + 2], dm[at + 3]]) as usize;
            v.push(dm[at + 4]);
            at += 5 + len;
        }
        assert_eq!(at, dm.len());
        v
    }

    #[test]
    fn cb1_order() {
        // by level, DM v2 blocks (3, 8-11, 254) after the others, ties in stream order
        let dm = payload(&[(254, 2), (2, 9), (1, 6), (8, 10), (2, 9), (3, 2), (5, 7), (9, 1), (4, 3)]);
        let out = wire(&dm).unwrap();
        assert_eq!(levels(&out), [1, 2, 2, 4, 5, 3, 8, 9, 254]);
        assert_eq!(out.len(), dm.len());
        assert_eq!(&out[..70], &dm[..70]);
        // the two L2 blocks keep their order (their bytes differ)
        let first_l2 = 71 + 5 + 6;
        assert_eq!(out[first_l2 + 5], 16);
        // no L5: a zero one is added at the end of the non-DM-v2 blocks' order
        let out = wire(&payload(&[(1, 6), (8, 10)])).unwrap();
        assert_eq!(levels(&out), [1, 8, 5]);
        assert_eq!(&out[out.len() - 13..], &[0, 0, 0, 8, 5, 0, 0, 0, 0, 0, 0, 0, 0]);
        // malformed: refused
        assert!(wire(&dm[..dm.len() - 1]).is_none());
        assert!(wire(&dm[..60]).is_none());
        let mut long = dm.clone();
        long.push(0);
        assert!(wire(&long).is_none());
    }

    #[test]
    fn packet_ids() {
        let mut st = PlanState::new().unwrap();
        let id = |st: &mut PlanState, contract: bool, player: u32, dm: &[u8]| unsafe {
            dvvk_test_packet_id(st.0.as_ptr(), contract as i32, player, dm.as_ptr(), dm.len())
        };
        let (a, b) = (payload(&[(1, 6)]), payload(&[(1, 7)]));
        assert_eq!(id(&mut st, true, 9, &a), 0); // the first: 0, not the player's
        assert_eq!(id(&mut st, true, 9, &a), 0); // the same payload: the same id
        assert_eq!(id(&mut st, true, 9, &b), 1);
        assert_eq!(id(&mut st, true, 9, &b), 1);
        assert_eq!(id(&mut st, false, 7, &b), 7); // outside the contract: the player's
        assert_eq!(id(&mut st, true, 9, &b), 8); // back in: the next after the last sent
        for k in 0..20u32 {
            let p = payload(&[(1, k + 1)]);
            assert_eq!(id(&mut st, true, 0, &p), (9 + k) & 15);
        }
        st.reset();
        assert_eq!(id(&mut st, true, 3, &a), 0);
    }

    /// The plan's digest (FNV-1a 64 over its bytes, tables_generation and
    /// dm_status zeroed: what the GPU gets).
    fn digest(p: &Plan) -> u64 {
        let mut copy = Plan::boxed();
        unsafe { std::ptr::copy_nonoverlapping(p as *const Plan, &mut *copy as *mut Plan, 1) };
        copy.tables_generation = 0;
        copy.dm_status = 0;
        let bytes =
            unsafe { std::slice::from_raw_parts(&*copy as *const Plan as *const u8, std::mem::size_of::<Plan>()) };
        bytes.iter().fold(0xcbf2_9ce4_8422_2325u64, |h, &b| (h ^ b as u64).wrapping_mul(0x100_0000_01b3))
    }

    /// Config k of the oracle harness: 0 FEL bilinear (nearest neighbour
    /// until ABI 3, the same plan bytes: el_method 1 where nearest was 1),
    /// 1 Annex B, 2 FEL off,
    /// 3 CB1 contract with the overlay, 4 a 1920x1080 box with the overlay,
    /// 5 the same in desktop mode.
    fn plan_in(has_el: bool, k: u32) -> (PlanIn, Option<PlanDesktop>) {
        let rgb = [0.6274, 0.3293, 0.0433, 0.0691, 0.9195, 0.0114, 0.0164, 0.0880, 0.8956];
        let lms = [7222.0, 8771.0, 390.0, 2654.0, 12430.0, 1300.0, 0.0, 422.0, 15962.0];
        let mut rgb_to_lms = [0f64; 9];
        for i in 0..3 {
            for j in 0..3 {
                for q in 0..3 {
                    rgb_to_lms[3 * i + j] += lms[3 * i + q] * rgb[3 * q + j] / 16384.0;
                }
            }
        }
        let mut p = PlanIn {
            width: 3840,
            height: 2160,
            x: 0,
            y: 0,
            dw: 0,
            dh: 0,
            chroma_top_left: 1,
            has_el: has_el as u32,
            nv12: 0,
            el_scaler: EL_BILINEAR,
            fel: 1,
            packet_id: 3,
            refresh: 1,
            overlay: 0,
            overlay_visible_before: 0,
            pts: 1000,
            rgb_to_lms,
            white_nits: 203.0,
            cb1_contract: 0,
            dm_options: 0,
        };
        let mut desktop = None;
        match k {
            1 => p.el_scaler = EL_ANNEXB,
            2 => p.fel = 0,
            3 => (p.cb1_contract, p.el_scaler, p.overlay) = (1, EL_ANNEXB, 1),
            4 | 5 => {
                (p.x, p.y, p.dw, p.dh, p.overlay) = (960, 540, 1920, 1080, 1);
                if k == 5 {
                    desktop = Some(PlanDesktop { enabled: 1, ..Default::default() });
                }
            }
            _ => {}
        }
        (p, desktop)
    }

    // (fixture, has_el, digests of configs 0-5) from HEAD 68e0c78's plan.c
    // (1917-fel.2: bef7034's, planned afresh). 1917's pictures 0-2 in order:
    // 0 to 1 changes the luma curve and the chroma MMR, 1 to 2 the MMR only
    // (its NLQ and luma kept), as most of a FEL film's pictures do.
    const ROUTES: [(&str, bool, [u64; 6]); 5] = [
        (
            "1917-fel.0",
            true,
            [
                0x6c27182b02b5bc08,
                0xa46251f948e221e1,
                0x2f8d56853d7b260b,
                0x07003dbe2510b2b1,
                0xef24bb6de157c8ce,
                0xa355d1f82c07f695,
            ],
        ),
        (
            "1917-fel.1",
            true,
            [
                0x58b1649710bcaaa4,
                0xdb311f604af675a5,
                0xdc2d708f053a5816,
                0x2c53da27bb40a651,
                0x538aed247984c4ca,
                0x8ce91e699b0bc8b8,
            ],
        ),
        (
            "1917-fel.2",
            true,
            [
                0xeca979ce2ab9122b,
                0xf534770eb974efc6,
                0xcd211b6f5ee36869,
                0xc5083797f43440a2,
                0x2721122f0803f9c5,
                0x63ff49dc2195965c,
            ],
        ),
        (
            "gemini-mel.0",
            false,
            [
                0x8c9baffe77bb884d,
                0x8c9baffe77bb884d,
                0x8c9baffe77bb884d,
                0x1b76ab69de57bd7d,
                0xddbeba1eabe2d7d6,
                0xd2c21de8274ff996,
            ],
        ),
        (
            "28yl-p81.0",
            false,
            [
                0x3604de3697958807,
                0x3604de3697958807,
                0x3604de3697958807,
                0xb7a5a4d58e865234,
                0x9d7d79cb74820cc5,
                0x86abfd91acf0da33,
            ],
        ),
    ];

    fn fixture(name: &str) -> Vec<u8> {
        std::fs::read(format!("{}/yblod/fixtures/{name}.bin", env!("CARGO_MANIFEST_DIR"))).unwrap()
    }

    #[test]
    fn routes_match_head() {
        let mut plan = Plan::boxed();
        for (name, has_el, digests) in ROUTES {
            let md = fixture(name);
            for (k, &want) in digests.iter().enumerate() {
                let (input, desktop) = plan_in(has_el, k as u32);
                let mut st = PlanState::new().unwrap();
                // planned afresh, then again from the table cache
                for pass in 0..2 {
                    assert_eq!(plan.fill(&input, desktop.as_ref(), &mut st, &md), 0, "{name} config {k}");
                    assert_eq!(digest(&plan), want, "{name} config {k} pass {pass}");
                }
            }
        }
    }

    #[test]
    fn table_cache_follows_the_configuration() {
        // one state across pictures and configurations: every plan is still
        // the fresh one, and an unchanged configuration keeps its generation
        let mut plan = Plan::boxed();
        let mut st = PlanState::new().unwrap();
        let mut last = None;
        for round in 0..2 {
            for (name, has_el, digests) in ROUTES {
                let md = fixture(name);
                // (not CB1's contract: its packet ids carry on across pictures)
                for k in [0usize, 4, 1, 2] {
                    let (input, desktop) = plan_in(has_el, k as u32);
                    assert_eq!(plan.fill(&input, desktop.as_ref(), &mut st, &md), 0);
                    assert_eq!(digest(&plan), digests[k], "{name} config {k} round {round}");
                    let again = plan.tables_generation;
                    assert_eq!(plan.fill(&input, desktop.as_ref(), &mut st, &md), 0);
                    assert_eq!(plan.tables_generation, again, "{name} config {k}: a repeat replanned");
                    last = Some(again);
                }
            }
        }
        assert!(last.is_some());
    }

    #[test]
    fn component_tables_follow_the_pictures() {
        // a FEL film's pictures one after another (the dual entry misses
        // every time; the luma, polynomial and NLQ entries carry over where
        // their parts are the same): every plan is the fresh one
        let mut plan = Plan::boxed();
        for k in [0usize, 1, 4] {
            let mut st = PlanState::new().unwrap();
            let mut generation = None;
            for i in [0usize, 1, 2, 1, 2, 0, 2] {
                let (name, has_el, digests) = ROUTES[i];
                let (input, desktop) = plan_in(has_el, k as u32);
                assert_eq!(plan.fill(&input, desktop.as_ref(), &mut st, &fixture(name)), 0);
                assert_eq!(digest(&plan), digests[k], "{name} config {k}");
                assert_ne!(
                    Some(plan.tables_generation),
                    generation,
                    "{name} config {k}: new tables, the same generation"
                );
                generation = Some(plan.tables_generation);
            }
        }
    }

    #[test]
    fn row_windows() {
        let w = |first, last, h| {
            let mut out = [7u32; 2];
            unsafe { dvvk_test_row_window(first, last, h, out.as_mut_ptr()) };
            out
        };
        assert_eq!(w(0, 2160, 2160), [0, 0]); // all rows
        assert_eq!(w(270, 1890, 2160), [264, 1896]); // 8-aligned outwards
        assert_eq!(w(0, 2159, 2160), [0, 0]); // reaches the last partial group
        assert_eq!(w(5, 5, 2160), [0, 0]); // empty
        assert_eq!(w(2160, 2200, 2160), [0, 0]);
        assert_eq!(w(100, 1077, 1080), [96, 1080]);
    }

    // ---- CM4 and L2 options (yblod/dm_cm4.c): CroqueMr's CB1 tests
    // (CB1/tests/cmv40.c: decisions, copy_and_defaults,
    // optional_append_failure) on yblod's payload, the neutral blocks
    // against yblod's own CM4 serializer, and the plans they make.

    extern "C" {
        fn dvvk_test_dm_cm4(dm: *mut u8, bytes: *mut usize, options: u32) -> u32;
        fn dv_cm4_extension(
            level: u32,
            raw: *const u8,
            bytes: usize,
            out: *mut u8,
            capacity: usize,
            out_bytes: *mut usize,
        ) -> i32;
    }

    const OFF: u32 = 0;
    const NO_L2: u32 = 1;
    const ALWAYS: u32 = 2;
    const AUTO: u32 = 3;
    const AUTO2: u32 = 4;
    const S_OFF: u32 = 0;
    const S_EXISTING: u32 = 1;
    const S_NOT_SELECTED: u32 = 2;
    const S_NEEDS_TV: u32 = 3;
    const S_APPENDED: u32 = 4;
    const S_INVALID: u32 = 5;
    const S_REJECTED: u32 = 6;

    /// DVVK_DM_OPTIONS: trigger 0 the TV peak, 1-4 1000/2000/4000/10000 nits.
    fn opts(mode: u32, trigger: u32, headroom: u32, no_l2: bool, tv: u32) -> u32 {
        mode | trigger << 3 | headroom << 6 | (no_l2 as u32) << 12 | tv << 16
    }

    /// yblod's payload with source_max_pq and these blocks (level, fields).
    fn dm(source_max_pq: u16, blocks: &[(u8, &[u16])]) -> Vec<u8> {
        let mut dm = vec![0u8; 71];
        dm[66..68].copy_from_slice(&source_max_pq.to_be_bytes());
        dm[70] = blocks.len() as u8;
        for &(level, fields) in blocks {
            dm.extend_from_slice(&(fields.len() as u32 * 2).to_be_bytes());
            dm.push(level);
            for f in fields {
                dm.extend_from_slice(&f.to_be_bytes());
            }
        }
        dm
    }

    /// (status, payload after).
    fn cm4(payload: &[u8], options: u32) -> (u32, Vec<u8>) {
        let mut buf = [0u8; 512];
        buf[..payload.len()].copy_from_slice(payload);
        let mut bytes = payload.len();
        let status = unsafe { dvvk_test_dm_cm4(buf.as_mut_ptr(), &mut bytes, options) };
        (status, buf[..bytes].to_vec())
    }

    fn decide(payload: &[u8], options: u32) -> u32 {
        cm4(payload, options).0 & 255
    }

    const L1: (u8, &[u16]) = (1, &[12, 3079, 1200]);
    const L2: (u8, &[u16]) = (2, &[2081, 2048, 2048, 2048, 2048, 2048, 4095]);

    #[test]
    fn cm4_decisions() {
        // CB1/tests/cmv40.c decisions(): L1 max 3079, an L2, mastering 3079 (~1000 nits)
        let m = dm(3079, &[L1, L2]);
        assert_eq!(decide(&m, 0), S_OFF);
        assert_eq!(decide(&m, opts(NO_L2, 0, 0, false, 0)), S_NOT_SELECTED);
        assert_eq!(decide(&m, opts(ALWAYS, 0, 0, false, 0)), S_APPENDED);
        assert_eq!(decide(&m, opts(AUTO, 0, 0, false, 1001)), S_APPENDED);
        assert_eq!(decide(&m, opts(AUTO, 0, 0, false, 999)), S_NOT_SELECTED);
        // CE takes 3079 as a nominal 1000 nits
        assert_eq!(decide(&m, opts(AUTO, 1, 0, false, 999)), S_APPENDED);
        let m2000 = dm(3388, &[L1, L2]); // ~2000 nits
        assert_eq!(decide(&m2000, opts(AUTO, 1, 0, false, 999)), S_NOT_SELECTED);
        assert_eq!(decide(&m2000, opts(AUTO, 2, 0, false, 999)), S_APPENDED);
        // the fixed triggers need no TV peak; the TV peak trigger does
        assert_eq!(decide(&m2000, opts(AUTO, 4, 0, false, 0)), S_APPENDED);
        assert_eq!(decide(&dm(4095, &[L1, L2]), opts(AUTO, 3, 0, false, 0)), S_NOT_SELECTED);
        assert_eq!(decide(&dm(3696, &[L1, L2]), opts(AUTO, 3, 0, false, 0)), S_APPENDED);
        assert_eq!(decide(&dm(4095, &[L1, L2]), opts(AUTO, 4, 0, false, 0)), S_APPENDED);
        assert_eq!(decide(&m, opts(AUTO, 0, 0, false, 0)), S_NEEDS_TV);
        assert_eq!(decide(&m, opts(AUTO, 0, 0, false, 10001)), S_NEEDS_TV);
        // below 2055: CE's 96-nit floor
        assert_eq!(decide(&dm(2000, &[L1, L2]), opts(AUTO, 0, 0, false, 96)), S_APPENDED);
        assert_eq!(decide(&dm(2000, &[L1, L2]), opts(AUTO, 0, 0, false, 95)), S_NOT_SELECTED);
        // Auto 2: L1 max against the TV peak + headroom (1000 + 20%: PQ 3160)
        let auto2 = |max: u16, headroom: u32, tv: u32| {
            decide(&dm(3079, &[(1, &[12, max, 1200]), L2]), opts(AUTO2, 0, headroom, false, tv))
        };
        assert_eq!(auto2(3079, 20, 1000), S_APPENDED);
        assert_eq!(auto2(3160, 20, 1000), S_APPENDED);
        assert_eq!(auto2(3161, 20, 1000), S_NOT_SELECTED);
        assert_eq!(auto2(3300, 20, 1000), S_NOT_SELECTED);
        assert_eq!(auto2(3079, 20, 0), S_NEEDS_TV);
        // headroom edges: 0 % (1000 nits: PQ 3079) and 50 % (1500 nits)
        assert_eq!(auto2(3079, 0, 1000), S_APPENDED);
        assert_eq!(auto2(3080, 0, 1000), S_NOT_SELECTED);
        assert_eq!(auto2(4095, 50, 10000), S_APPENDED); // capped at 10000 nits
        assert_eq!(auto2(3079, 51, 1000), S_INVALID);
        // CE's missing-L1 rule: absent L1 qualifies when the TV peak is known
        assert_eq!(decide(&dm(3079, &[L2]), opts(AUTO2, 0, 20, false, 1000)), S_APPENDED);
        assert_eq!(decide(&dm(3079, &[L2]), opts(AUTO2, 0, 20, false, 0)), S_NEEDS_TV);
        // no L2: every mode appends, TV peak or not
        let none = dm(3079, &[L1]);
        for mode in [NO_L2, ALWAYS, AUTO, AUTO2] {
            assert_eq!(decide(&none, opts(mode, 0, 0, false, 0)), S_APPENDED, "mode {mode}");
        }
        // already CM4: any of L3, L8-L11, L254
        for level in [3u8, 8, 9, 10, 11, 254] {
            let m = dm(3079, &[L1, L2, (level, &[0])]);
            for mode in [NO_L2, ALWAYS, AUTO, AUTO2] {
                assert_eq!(decide(&m, opts(mode, 0, 20, false, 1000)), S_EXISTING, "L{level} mode {mode}");
            }
        }
        // invalid options
        assert_eq!(decide(&m, opts(5, 0, 0, false, 0)), S_INVALID);
        assert_eq!(decide(&m, opts(AUTO, 5, 0, false, 0)), S_INVALID);
        assert_eq!(decide(&m, opts(OFF, 0, 51, false, 0)), S_INVALID);
        // a malformed payload is never made eligible (nor changed)
        for bad in [&m[..m.len() - 1], &m[..60]] {
            assert_eq!(cm4(bad, opts(ALWAYS, 0, 0, true, 0)), (S_INVALID, bad.to_vec()));
        }
        let mut long = m.clone();
        long.push(0);
        assert_eq!(cm4(&long, opts(ALWAYS, 0, 0, false, 0)), (S_INVALID, long.clone()));
        let short_l1 = dm(3079, &[(1, &[12, 3079]), L2]);
        assert_eq!(decide(&short_l1, opts(AUTO2, 0, 20, false, 1000)), S_INVALID);
    }

    #[test]
    fn cm4_headroom_threshold() {
        // Auto 2's threshold is the rounded ST 2084 code of TV x (1 + headroom)
        let pq = |nits: f64| {
            let (m1, m2, c1, c2, c3) = (0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875);
            let p = (nits.min(10000.0) / 10000.0).powf(m1);
            (4095.0 * ((c1 + c2 * p) / (1.0 + c3 * p)).powf(m2)).round() as u16
        };
        for (tv, headroom) in [(1000u32, 50u32), (774, 20), (600, 0), (4000, 35), (100, 50)] {
            let t = pq(tv as f64 * (100 + headroom) as f64 / 100.0);
            let m = |max: u16| dm(3079, &[(1, &[12, max, 1200]), L2]);
            assert_eq!(decide(&m(t), opts(AUTO2, 0, headroom, false, tv)), S_APPENDED, "{tv} +{headroom}%");
            assert_eq!(decide(&m(t + 1), opts(AUTO2, 0, headroom, false, tv)), S_NOT_SELECTED, "{tv} +{headroom}%");
        }
    }

    /// The payload's (level, payload bytes) blocks.
    fn blocks(dm: &[u8]) -> Vec<(u8, Vec<u8>)> {
        let mut at = 71;
        let mut v = Vec::new();
        for _ in 0..dm[70] {
            let len = u32::from_be_bytes([dm[at], dm[at + 1], dm[at + 2], dm[at + 3]]) as usize;
            v.push((dm[at + 4], dm[at + 5..at + 5 + len].to_vec()));
            at += 5 + len;
        }
        assert_eq!(at, dm.len());
        v
    }

    /// The neutral blocks as plan.c appends them.
    fn neutral() -> Vec<(u8, Vec<u8>)> {
        vec![(3, vec![8, 0, 8, 0, 8, 0]), (9, vec![0]), (11, vec![1, 0, 0, 0]), (254, vec![0, 2])]
    }

    #[test]
    fn cm4_output() {
        // CB1/tests/cmv40.c copy_and_defaults()
        let m = dm(3079, &[L1, L2]);
        let (status, out) = cm4(&m, opts(NO_L2, 0, 0, true, 0));
        assert_eq!(status, S_NOT_SELECTED | 1 << 8); // the decision saw the L2; the output hasn't it
        assert_eq!(blocks(&out), blocks(&dm(3079, &[L1])));
        assert_eq!(&out[..70], &m[..70]);
        let (status, out) = cm4(&m, opts(ALWAYS, 0, 0, true, 0));
        assert_eq!(status, S_APPENDED | 1 << 8);
        let mut want = blocks(&dm(3079, &[L1]));
        want.extend(neutral());
        assert_eq!(blocks(&out), want);
        // again: already CM4, nothing changes (idempotent)
        assert_eq!(cm4(&out, opts(ALWAYS, 0, 0, false, 0)), (S_EXISTING, out.clone()));
        // L2 kept: appended after it
        let (status, out) = cm4(&m, opts(ALWAYS, 0, 0, false, 0));
        assert_eq!(status, S_APPENDED);
        let mut want = blocks(&m);
        want.extend(neutral());
        assert_eq!(blocks(&out), want);
        // off: as is; L2 removal alone, independent of the mode
        assert_eq!(cm4(&m, 0), (S_OFF, m.clone()));
        let (status, out) = cm4(&m, opts(OFF, 0, 0, true, 0));
        assert_eq!((status, blocks(&out)), (S_OFF | 1 << 8, blocks(&dm(3079, &[L1]))));
        // every L2 goes (the decision still saw them)
        let three = dm(3079, &[L1, L2, (4, &[1, 2]), L2, L2, (5, &[0; 4])]);
        let (status, out) = cm4(&three, opts(AUTO, 0, 0, true, 999));
        assert_eq!(
            (status, blocks(&out)),
            (S_NOT_SELECTED | 3 << 8, blocks(&dm(3079, &[L1, (4, &[1, 2]), (5, &[0; 4])])))
        );
        // needs the TV peak: L2 removal still applies
        let (status, out) = cm4(&m, opts(AUTO2, 0, 20, true, 0));
        assert_eq!((status, blocks(&out)), (S_NEEDS_TV | 1 << 8, blocks(&dm(3079, &[L1]))));
        // CB1's ordering then puts them with the DM v2 blocks: L1, L2, L5, L3, L9, L11, L254
        let (_, out) = cm4(&dm(3079, &[(5, &[0; 4]), L1, L2]), opts(ALWAYS, 0, 0, false, 0));
        assert_eq!(levels(&wire(&out).unwrap()), [1, 2, 5, 3, 9, 11, 254]);
    }

    #[test]
    fn cm4_overflow_is_rejected() {
        // CB1/tests/cmv40.c optional_append_failure(): an L1 and 21 L2 (481
        // bytes): with the 4 blocks (33) and CB1's L5 (13) over 512
        let mut list: Vec<(u8, &[u16])> = vec![L1];
        list.extend(std::iter::repeat_n(L2, 21));
        let m = dm(3079, &list);
        assert_eq!(m.len(), 481);
        assert_eq!(cm4(&m, opts(ALWAYS, 0, 0, false, 0)), (S_REJECTED, m.clone()));
        // with an L5 already there: 494 + 33 > 512 still
        let mut with_l5 = list.clone();
        with_l5.push((5, &[0; 4]));
        let m5 = dm(3079, &with_l5);
        assert_eq!(cm4(&m5, opts(ALWAYS, 0, 0, false, 0)), (S_REJECTED, m5.clone()));
        // L2 removal is independent of the rejection
        let (status, out) = cm4(&m5, opts(AUTO, 4, 0, true, 0));
        assert_eq!(status, S_APPENDED | 21 << 8);
        assert_eq!(out.len(), 71 + 11 + 13 + 33);
        // two L2 fewer fits: 443 + 33 + CB1's L5 13 = 489
        let m = dm(3079, &list[..20]);
        let (status, out) = cm4(&m, opts(ALWAYS, 0, 0, false, 0));
        assert_eq!((status, out.len()), (S_APPENDED, 443 + 33));
        assert_eq!(wire(&out).unwrap().len(), 489);
    }

    #[test]
    fn cm4_blocks_are_yblods_native_cm4() {
        // dovi_tool's default_safe() / CroqueMr's raw RPU bits through yblod's
        // own CM4 serializer (dv_cm4_extension: what a CM4 stream's blocks
        // become): the bytes plan.c appends
        let raw: [(u32, &[u8]); 4] =
            [(3, &[0x80, 0x08, 0x00, 0x80, 0x00]), (9, &[0]), (11, &[1, 0, 0, 0]), (254, &[0, 2])];
        for ((level, bits), want) in raw.iter().zip(neutral()) {
            let mut out = [0u8; 32];
            let mut n = 0usize;
            assert_eq!(unsafe { dv_cm4_extension(*level, bits.as_ptr(), bits.len(), out.as_mut_ptr(), 32, &mut n) }, 0);
            assert_eq!((*level as u8, out[..n].to_vec()), want);
        }
    }

    /// The DM payload a plan's packets carry.
    fn payload_of(p: &Plan) -> Vec<u8> {
        let bytes = (p.packets[3] as usize) << 8 | p.packets[4] as usize;
        let mut v = p.packets[5..124].to_vec();
        for i in 1..p.packet_count as usize {
            v.extend_from_slice(&p.packets[i * 128 + 3..i * 128 + 124]);
        }
        v.truncate(bytes);
        v
    }

    /// A fixture with these raw extension blocks added (ffmpeg-yblod's
    /// AVDOVIDmData: the level, then the raw trailer at 76: magic, length,
    /// bits), as cb1_cmv40_output adds them to AVDOVIMetadata.
    fn with_raw_blocks(md: &[u8], raw: &[(u8, &[u8])]) -> Vec<u8> {
        let mut md = md.to_vec();
        let offset = u64::from_le_bytes(md[24..32].try_into().unwrap()) as usize;
        let size = u64::from_le_bytes(md[32..40].try_into().unwrap()) as usize;
        let n = i32::from_le_bytes(md[40..44].try_into().unwrap()) as usize;
        assert_eq!(size, 116);
        for (k, (level, bits)) in raw.iter().enumerate() {
            let b = &mut md[offset + (n + k) * size..offset + (n + k + 1) * size];
            b.fill(0);
            b[0] = *level;
            b[76..80].copy_from_slice(&0x4142_4456u32.to_le_bytes());
            b[80..84].copy_from_slice(&(bits.len() as u32).to_le_bytes());
            b[84..84 + bits.len()].copy_from_slice(bits);
        }
        md[40..44].copy_from_slice(&((n + raw.len()) as i32).to_le_bytes());
        md
    }

    #[test]
    fn cm4_matches_a_native_cm4_stream() {
        // 1917 and Gemini Man (CM2.9: L1, L2, L4, L5, L6) with CM4 "Always"
        // plan byte for byte as the same pictures with the four neutral
        // blocks in their RPU, as yblod plans a CM4 stream: with and without
        // CB1's contract; outside it in level order, as plan.c appends them;
        // inside it also in CroqueMr's order, which CB1's ordering sorts
        let sorted: [(u8, &[u8]); 4] =
            [(3, &[0x80, 0x08, 0x00, 0x80, 0x00]), (9, &[0]), (11, &[1, 0, 0, 0]), (254, &[0, 2])];
        let croquemr: [(u8, &[u8]); 4] =
            [(3, &[0x80, 0x08, 0x00, 0x80, 0x00]), (9, &[0]), (254, &[0, 2]), (11, &[1, 0, 0, 0])];
        let mut plan = Plan::boxed();
        let mut native = Plan::boxed();
        for (name, has_el) in [("1917-fel.0", true), ("gemini-mel.0", false)] {
            let md = fixture(name);
            for k in [0u32, 1, 3, 4] {
                for (order, raw) in [("sorted", &sorted), ("CroqueMr's", &croquemr)] {
                    if k != 3 && order != "sorted" {
                        continue;
                    }
                    let (mut input, desktop) = plan_in(has_el, k);
                    let mut st = PlanState::new().unwrap();
                    assert_eq!(native.fill(&input, desktop.as_ref(), &mut st, &with_raw_blocks(&md, raw)), 0);
                    input.dm_options = opts(ALWAYS, 0, 0, false, 0);
                    let mut st = PlanState::new().unwrap();
                    assert_eq!(plan.fill(&input, desktop.as_ref(), &mut st, &md), 0, "{name} config {k}");
                    assert_eq!(plan.dm_status, S_APPENDED);
                    assert_eq!(digest(&plan), digest(&native), "{name} config {k}, {order} order");
                    let l: Vec<u8> = blocks(&payload_of(&plan)).iter().map(|b| b.0).collect();
                    assert_eq!(&l[l.len() - 4..], &[3, 9, 11, 254], "{name} config {k}");
                }
            }
        }
    }

    #[test]
    fn cm4_leaves_a_cm4_stream_alone() {
        // 28 Years Later (P8.1) is CM4 (L3, L8, L9, L254): its L9 and L254
        // are the neutral bytes plan.c would add, its L3 has their layout,
        // and every mode leaves it as it is
        let md = fixture("28yl-p81.0");
        let mut plan = Plan::boxed();
        for k in [0u32, 3] {
            let (mut input, desktop) = plan_in(false, k);
            let mut st = PlanState::new().unwrap();
            assert_eq!(plan.fill(&input, desktop.as_ref(), &mut st, &md), 0);
            let want = digest(&plan);
            let b = blocks(&payload_of(&plan));
            for (level, bytes) in neutral() {
                if level == 9 || level == 254 {
                    assert!(b.contains(&(level, bytes)), "L{level}");
                }
            }
            assert_eq!(b.iter().find(|x| x.0 == 3).unwrap().1.len(), 6);
            for mode in [NO_L2, ALWAYS, AUTO, AUTO2] {
                input.dm_options = opts(mode, 0, 20, false, 774);
                let mut st = PlanState::new().unwrap();
                assert_eq!(plan.fill(&input, desktop.as_ref(), &mut st, &md), 0);
                assert_eq!((plan.dm_status, digest(&plan)), (S_EXISTING, want), "config {k} mode {mode}");
            }
        }
    }

    // (fixture, has_el, options, digests of configs 0-5): CM4 "Always",
    // "Always" with L2 removed, and L2 removed alone (dv-engine-vk 0.1.0-18's
    // plan.c). Desktop frames (5) keep their own metadata: ROUTES' digests.
    const CM4_ROUTES: [(&str, bool, u32, [u64; 6]); 7] = [
        (
            "1917-fel.0",
            true,
            0x2,
            [
                0xf632b4898b495969,
                0xcc3748aed83d3444,
                0x83ef5ca9f978a132,
                0x897f7cf277a86844,
                0x4a206d0bd15cb887,
                0xa355d1f82c07f695,
            ],
        ),
        (
            "1917-fel.0",
            true,
            0x1002,
            [
                0x55e70634841864c5,
                0xb8f074aef4761a20,
                0xec74717c3e62665e,
                0x68d7f51d35912089,
                0x489714f802d710b2,
                0xa355d1f82c07f695,
            ],
        ),
        (
            "1917-fel.0",
            true,
            0x1000,
            [
                0x5c9dcd6e94c8bf19,
                0x0ede6c408ea00924,
                0xe39f916c3432e18a,
                0xcd1b157aee5a9218,
                0x4d2d7e308539480a,
                0xa355d1f82c07f695,
            ],
        ),
        (
            "gemini-mel.0",
            false,
            0x2,
            [
                0x28f2675beea04cb8,
                0x28f2675beea04cb8,
                0x28f2675beea04cb8,
                0x0171892e889d4450,
                0xd676c603dc36af03,
                0xd2c21de8274ff996,
            ],
        ),
        (
            "gemini-mel.0",
            false,
            0x1002,
            [
                0x202f468962e29f3b,
                0x202f468962e29f3b,
                0x202f468962e29f3b,
                0x378449230d8df239,
                0x4868dc14c0b1402a,
                0xd2c21de8274ff996,
            ],
        ),
        (
            "gemini-mel.0",
            false,
            0x1000,
            [
                0x8f8aaa020b6a1d5f,
                0x8f8aaa020b6a1d5f,
                0x8f8aaa020b6a1d5f,
                0x5ecc53e9d4850ecc,
                0x904eff576b77bdb6,
                0xd2c21de8274ff996,
            ],
        ),
        (
            "28yl-p81.0",
            false,
            0x1002,
            [
                0xdb1ac7988c267969,
                0xdb1ac7988c267969,
                0xdb1ac7988c267969,
                0x5626762a1fa8b606,
                0x1d9b5afa6370d46e,
                0x86abfd91acf0da33,
            ],
        ),
    ];

    #[test]
    fn cm4_routes_match() {
        let mut plan = Plan::boxed();
        let mut failed = Vec::new();
        for (name, has_el, options, digests) in CM4_ROUTES {
            let md = fixture(name);
            let base = ROUTES.iter().find(|r| r.0 == name).unwrap().2;
            let mut got = [0u64; 6];
            for (k, slot) in got.iter_mut().enumerate() {
                let (mut input, desktop) = plan_in(has_el, k as u32);
                input.dm_options = options;
                let mut st = PlanState::new().unwrap();
                assert_eq!(plan.fill(&input, desktop.as_ref(), &mut st, &md), 0, "{name} config {k}");
                *slot = digest(&plan);
                if desktop.is_some() {
                    assert_eq!((plan.dm_status, *slot), (0, base[k]), "{name}: the desktop's metadata is its own");
                } else {
                    assert_ne!(*slot, base[k], "{name} config {k}: unchanged");
                }
            }
            if got != digests {
                failed.push(format!("(\"{name}\", {has_el}, {options:#x}, {got:#018x?}),"));
            }
        }
        assert!(failed.is_empty(), "new digests:\n{}", failed.join("\n"));
    }
}

/// The EL upsampling's CPU reference (yblod-engine/src/pixel_spatial.c,
/// dv_bilinear_scale2x and dv_annex_b_scale2x): what the shaders' bilinear
/// (shaders/common/dv_common.glsl el_bilinear_*) computes, and that it samples
/// at Annex B's phases.
#[cfg(test)]
mod el_tests {
    extern "C" {
        fn dv_bilinear_scale2x(
            input: *const u16,
            count: usize,
            w: u32,
            h: u32,
            chroma: u32,
            scratch: *mut u16,
            scratch_count: usize,
            out: *mut u16,
            out_count: usize,
        ) -> i32;
        fn dv_annex_b_scale2x(
            input: *const u16,
            count: usize,
            w: u32,
            h: u32,
            chroma: u32,
            scratch: *mut u16,
            scratch_count: usize,
            out: *mut u16,
            out_count: usize,
        ) -> i32;
    }

    fn scale(bilinear: bool, input: &[u16], w: usize, h: usize, chroma: bool) -> Vec<u16> {
        let (mut scratch, mut out) = (vec![0u16; w], vec![0u16; 4 * w * h]);
        let f = if bilinear { dv_bilinear_scale2x } else { dv_annex_b_scale2x };
        let r = unsafe {
            f(input.as_ptr(), input.len(), w as u32, h as u32, chroma as u32, scratch.as_mut_ptr(), w, out.as_mut_ptr(), out.len())
        };
        assert_eq!(r, 0);
        out
    }

    /// The shaders' bilinear, written out as they compute it: the vertical
    /// pass (fel_vertical_pair: el_bilinear_quarter(near, far); the chroma's
    /// 64/192 of fel_phase_vertical_uv) then the horizontal one
    /// (HORIZONTAL / el_bilinear_mid: (a + b + 1) / 2), edges clamped.
    fn shader_model(input: &[u16], w: usize, h: usize, chroma: bool) -> Vec<u16> {
        let at = |x: isize, y: isize| input[y.clamp(0, h as isize - 1) as usize * w + x.clamp(0, w as isize - 1) as usize] as i64;
        let vertical = |x: usize, row: usize| -> i64 {
            let (r, odd) = ((row / 2) as isize, row % 2 == 1);
            let (near, far) = (at(x as isize, r), at(x as isize, if odd { r + 1 } else { r - 1 }));
            if chroma {
                (192 * near + 64 * far + 128) / 256
            } else {
                (3 * near + far + 2) / 4
            }
        };
        let mut out = vec![0u16; 4 * w * h];
        for y in 0..2 * h {
            for x in 0..2 * w {
                let ix = x / 2;
                let v = if x % 2 == 0 { vertical(ix, y) } else { (vertical(ix, y) + vertical((ix + 1).min(w - 1), y) + 1) / 2 };
                out[y * 2 * w + x] = v as u16;
            }
        }
        out
    }

    #[test]
    fn bilinear_reference_is_the_shaders_arithmetic() {
        let (w, h) = (37, 23);
        let mut seed = 0x2545_f491_4f6c_dd1du64;
        let input: Vec<u16> = (0..w * h)
            .map(|_| {
                seed ^= seed << 13;
                seed ^= seed >> 7;
                seed ^= seed << 17;
                (seed % 1024) as u16
            })
            .collect();
        for chroma in [false, true] {
            assert_eq!(scale(true, &input, w, h, chroma), shader_model(&input, w, h, chroma), "chroma {chroma}");
        }
        // the extremes stay codes: no ringing, unlike Annex B
        let out = scale(true, &input, w, h, false);
        assert!(out.iter().all(|&v| v <= 1023));
    }

    #[test]
    fn bilinear_samples_at_annex_b_phases() {
        // A plane linear in x and y: both filters reproduce a ramp exactly at
        // their sample positions (Annex B's taps are normalized and centred
        // on the same points), so equal values mean equal phases. Away from
        // the clamped edges (Annex B's 8-tap and 4-tap reach).
        let (w, h) = (40, 24);
        let input: Vec<u16> = (0..w * h).map(|i| (8 * (i % w) + 16 * (i / w) + 64) as u16).collect();
        for chroma in [false, true] {
            let (b, a) = (scale(true, &input, w, h, chroma), scale(false, &input, w, h, chroma));
            for y in 4..2 * h - 4 {
                for x in 8..2 * w - 8 {
                    assert_eq!(b[y * 2 * w + x], a[y * 2 * w + x], "chroma {chroma} at {x},{y}");
                }
            }
            // and they do differ on detail (a step): the filters aren't the same
            let step: Vec<u16> = (0..w * h).map(|i| if i % w < w / 2 { 100 } else { 900 }).collect();
            assert_ne!(scale(true, &step, w, h, chroma), scale(false, &step, w, h, chroma));
        }
        // invalid shapes are refused
        assert_ne!(unsafe { dv_bilinear_scale2x(input.as_ptr(), input.len(), 0, 0, 0, std::ptr::null_mut(), 0, std::ptr::null_mut(), 0) }, 0);
    }
}
