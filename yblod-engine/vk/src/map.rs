//! The output colour mapping (include/dvvk_map.h, docs/hdr10-output.md): the
//! output mode the caller set (HDR10, HDR10+, SDR, or a display-targeted
//! one: HDR10 Rendering Reference, LLDV), and its per-frame plan from
//! yblod/dv_map.c.

use std::mem::{offset_of, size_of};

pub const DVVK_OUTPUT_DV: u32 = 0;
pub const DVVK_OUTPUT_HDR10: u32 = 1;
pub const DVVK_OUTPUT_HDR10PLUS: u32 = 2;
pub const DVVK_OUTPUT_SDR: u32 = 3;
pub const DVVK_OUTPUT_LLDV: u32 = 4;
/// dvvk_output_mode.flags of the display-targeted outputs: DVVK_HDR10_TARGET
/// (HDR10), DVVK_LLDV_10BIT (LLDV); dvvk_target_flags.
pub const TARGET_FLAGS: u32 = 1;
/// dvvk_output_mode.flags an SDR output takes (DVVK_SDR_*: gamma 2.2,
/// limited range, no dither, an HLG source; CB1's targets: a pure power,
/// the black as given, BT.2020).
pub const SDR_FLAGS: u32 = 127;
/// DVVK_SDR_GAMMA22, DVVK_SDR_POWER, DVVK_SDR_BLACK.
const SDR_GAMMA22: u32 = 1;
const SDR_POWER: u32 = 16;
const SDR_BLACK: u32 = 32;
/// The 3D LUT's points per axis (dvvk_map_gpu.lut_n; dv_map.c sets it).
pub const LUT_N: u32 = 65;
/// map_bake's threshold: cells interpolating worse than this (12-bit codes)
/// are computed exactly.
pub const BAKE_THRESH: f32 = 0.5;
/// The same for SDR output, in its 8-bit codes, and at more points of each
/// cell (map_bake.comp): on the test titles' frames the worst sample outside
/// the marked cells is then 0.68 of a code (0.4: 0.71), and 6.7 % of a dark
/// frame's pixels are computed exactly.
pub const BAKE_THRESH_SDR: f32 = 0.35;
/// SDR output's 3D LUT (include/dvvk_map.h DVVK_MAP_SDR_NY, DVVK_MAP_SDR_NC:
/// dv_map.c sets them): its points along luma, Cb and Cr.
pub const SDR_LUT: [u32; 3] = [129, 65, 65];
/// SDR output's fix-up list in the cells buffer (words): after its cells'
/// bits, 256-aligned.
pub const fn sdr_list() -> u32 {
    ((SDR_LUT[0] - 1) * (SDR_LUT[1] - 1) * (SDR_LUT[2] - 1)).div_ceil(32).next_multiple_of(64)
}
/// include/dvvk_map.h DVVK_MAP_TABLE_WORDS: SDR output's tables (the dither
/// pattern, then the gamut LUT).
pub const TABLE_WORDS: usize = 64 * 64 + 2 * 48 * 32 * 256;
/// The gamut LUT in the tables: its first word, and its points (I, C, h).
pub const GAMUT_AT: usize = 64 * 64;
pub const GAMUT_SIZE: [u32; 3] = [48, 32, 256];
/// dvvk_map_gpu.flags: DVVK_MAP_SDR, DVVK_MAP_GAMUT, DVVK_MAP_HLG,
/// DVVK_MAP_EXPERT, DVVK_MAP_LLDV.
const MAP_SDR: u32 = 4;
const MAP_GAMUT: u32 = 8;
const MAP_HLG: u32 = 32;
const MAP_EXPERT: u32 = 256;
const MAP_LLDV: u32 = 512;

/// include/dv_engine_vk.h dvvk_output_mode.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct OutputMode {
    pub mode: u32,
    pub flags: u32,
    pub peak_nits: f32,
    pub min_nits: f32,
    pub reserved: [u32; 4],
}

/// include/dv_engine_vk.h dvvk_display_primaries: an LLDV display's own.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct DisplayPrimaries {
    pub edid_version: u32,
    pub xy: [[f32; 2]; 3],
    pub reserved: [u32; 3],
}

/// include/dv_engine_vk.h dvvk_hdr_signal.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct HdrSignal {
    pub mode: u32,
    pub eotf: u32,
    pub primaries: [[u16; 2]; 3],
    pub white: [u16; 2],
    pub max_luminance: u16,
    pub min_luminance: u16,
    pub max_cll: u16,
    pub max_fall: u16,
    pub reserved: [u32; 4],
}

/// include/dvvk_map.h dvvk_map_gpu: the GPU's parameters, as bytes (the
/// display-targeted outputs' fields from GPU_EXPERT on).
pub const GPU_BYTES: usize = 18592;
pub const GPU_EXPERT: usize = 1504;
#[repr(C)]
#[derive(Clone, Copy)]
pub struct MapGpu {
    pub bytes: [u8; GPU_BYTES],
}

/// include/dvvk_map.h dvvk_map.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Map {
    pub gpu: MapGpu,
    pub key: u64,
    pub signal: HdrSignal,
    pub gamut_prim: [[f32; 8]; 2],
    pub gamut_luma: [f32; 2],
    /// Names what SDR output's gamut LUT is made from (0: none).
    pub gamut_key: u64,
}

const _: () = {
    assert!(size_of::<OutputMode>() == 32);
    assert!(size_of::<DisplayPrimaries>() == 40);
    assert!(size_of::<HdrSignal>() == 48);
    assert!(offset_of!(HdrSignal, max_luminance) == 24);
    assert!(size_of::<MapGpu>() == GPU_BYTES);
    assert!(offset_of!(Map, key) == GPU_BYTES);
    assert!(offset_of!(Map, signal) == GPU_BYTES + 8);
    assert!(offset_of!(Map, gamut_prim) == GPU_BYTES + 56);
    assert!(offset_of!(Map, gamut_key) == GPU_BYTES + 128);
    assert!(size_of::<Map>() == GPU_BYTES + 136);
};

extern "C" {
    fn dvvk_map_plan_display(
        mode: *const OutputMode,
        display: *const DisplayPrimaries,
        metadata: *const u8,
        size: usize,
        out: *mut Map,
    ) -> i32;
    fn dvvk_map_target_valid(mode: *const OutputMode, display: *const DisplayPrimaries) -> i32;
    fn dvvk_map_tables(map: *const Map, tables: *mut u32);
    fn dvvk_map_set_black(gpu: *mut MapGpu, tables: *const u32, black: *const u32);
}

/// Whether dvvk_set_output_mode takes `mode` (dv_map.c's sdr_display for
/// SDR: a frame's plan would refuse the rest one by one), with no display
/// primaries set.
pub fn mode_supported(mode: &OutputMode) -> bool {
    mode_supported_with(mode, &DisplayPrimaries::default())
}

/// The same with an LLDV display's primaries: the display-targeted modes
/// are a display CB1's policy takes (dvbridge_policy_validate, through
/// dv_map.c; the black's bound depends on the VSVDB's version).
pub fn mode_supported_with(mode: &OutputMode, display: &DisplayPrimaries) -> bool {
    match mode.mode {
        DVVK_OUTPUT_LLDV => {
            unsafe { dvvk_map_target_valid(mode, display) == 1 }
        }
        DVVK_OUTPUT_DV | DVVK_OUTPUT_HDR10 | DVVK_OUTPUT_HDR10PLUS => {
            mode.flags == 0 && mode.peak_nits == 0.0 && mode.min_nits == 0.0
        }
        DVVK_OUTPUT_SDR => {
            let white = if mode.peak_nits > 0.0 { mode.peak_nits } else { 203.0 };
            let exact = mode.flags & SDR_BLACK != 0;
            let black = if exact || mode.min_nits > 0.0 { mode.min_nits } else { white / 1000.0 };
            // reserved[0] is the pure power's gamma (thousandths), the others unused
            let gamma = mode.reserved[0];
            let power = mode.flags & SDR_POWER != 0;
            mode.flags & !SDR_FLAGS == 0
                && mode.peak_nits >= 0.0
                && mode.min_nits >= 0.0
                && (20.0..=1000.0).contains(&white)
                && (if exact { (0.0..=5.0).contains(&black) && black < white } else { black < white / 20.0 })
                && (if power { mode.flags & SDR_GAMMA22 == 0 && (1800..=2800).contains(&gamma) } else { gamma == 0 })
                && mode.reserved[1..] == [0; 3]
        }
        _ => false,
    }
}

impl Map {
    /// dvvk_map_gpu.flags (offset 336).
    fn flags(&self) -> u32 {
        u32::from_le_bytes(self.gpu.bytes[336..340].try_into().unwrap())
    }

    /// SDR output: the display's R'G'B' (else BT.2020 PQ Y'CbCr).
    pub fn sdr(&self) -> bool {
        self.flags() & MAP_SDR != 0
    }

    /// SDR output of an HLG source (DVVK_SDR_HLG): its own pipelines.
    pub fn hlg(&self) -> bool {
        self.flags() & MAP_HLG != 0
    }

    /// A display-targeted output (CB1's Expert recipe): its own pipelines.
    pub fn expert(&self) -> bool {
        self.flags() & MAP_EXPERT != 0
    }

    /// ... and LLDV's (its pack, its overlay after the map).
    pub fn lldv(&self) -> bool {
        self.flags() & MAP_LLDV != 0
    }

    /// The tables (dither, gamut LUT) the map reads: SDR's, and an Expert
    /// output's that maps the gamut.
    pub fn needs_tables(&self) -> bool {
        self.sdr() || (self.expert() && self.flags() & MAP_GAMUT != 0)
    }

    /// SDR output's tables (TABLE_WORDS words) for this mapping: when
    /// gamut_key changes (tens of milliseconds).
    pub fn tables(&self, words: &mut [u32]) {
        assert!(words.len() >= TABLE_WORDS);
        unsafe { dvvk_map_tables(self, words.as_mut_ptr()) };
    }

    /// The stream's black (12-bit Y, Cb, Cr) and its exact output codes.
    /// `tables`: the map's (current for this mapping) where it reads them.
    pub fn set_black(&mut self, black: [u32; 3], tables: Option<&[u32]>) {
        assert!(tables.is_some_and(|t| t.len() >= TABLE_WORDS) || !self.needs_tables());
        let tables = tables.map_or(std::ptr::null(), |t| t.as_ptr());
        unsafe { dvvk_map_set_black(&mut self.gpu, tables, black.as_ptr()) };
    }

    /// SDR output's LUT size (dvvk_map_gpu.lut_ny at offset 348, lut_n at 340).
    pub fn lut_size(&self) -> [u32; 3] {
        let word = |at: usize| u32::from_le_bytes(self.gpu.bytes[at..at + 4].try_into().unwrap());
        [word(348), word(340), word(340)]
    }

    /// dvvk_map_gpu.list (offset 344): the cells buffer's fix-up list (not in the key).
    pub fn set_list(&mut self, word: u32) {
        self.gpu.bytes[344..348].copy_from_slice(&word.to_le_bytes());
    }

    /// dvvk_map_gpu.lut_n (offset 340): the engine's LUT size (the key moves with it).
    pub fn set_lut_n(&mut self, n: u32) {
        self.gpu.bytes[340..344].copy_from_slice(&n.to_le_bytes());
        self.key ^= u64::from(n) << 48;
    }

    /// The frame's mapping: Ok(map), or the frame refused (dv_status).
    /// `display`: an LLDV display's own primaries (version 0: none).
    pub fn plan(mode: &OutputMode, display: &DisplayPrimaries, metadata: &[u8]) -> Result<Box<Map>, i32> {
        let mut out = Box::new(Map {
            gpu: MapGpu { bytes: [0; GPU_BYTES] },
            key: 0,
            signal: HdrSignal::default(),
            gamut_prim: [[0.0; 8]; 2],
            gamut_luma: [0.0; 2],
            gamut_key: 0,
        });
        // AVDOVIMetadata is read in place: it must be aligned as ffmpeg allocates it.
        let r = if metadata.as_ptr() as usize % 8 == 0 {
            unsafe { dvvk_map_plan_display(mode, display, metadata.as_ptr(), metadata.len(), &mut *out) }
        } else {
            let mut copy = vec![0u64; metadata.len().div_ceil(8)];
            let bytes = unsafe { std::slice::from_raw_parts_mut(copy.as_mut_ptr() as *mut u8, metadata.len()) };
            bytes.copy_from_slice(metadata);
            unsafe { dvvk_map_plan_display(mode, display, copy.as_ptr() as *const u8, metadata.len(), &mut *out) }
        };
        if r == 0 {
            Ok(out)
        } else {
            Err(r)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hdr10plus::{static_to_dovi, Hdr10Static, DOVI_BYTES};

    /// A plain HDR10 video's metadata (dvvk_hdr10_to_dovi: P3-D65 mastering,
    /// 1000 cd/m2), as words so that it is aligned as ffmpeg's.
    fn metadata() -> Vec<u64> {
        let mut out = vec![0u64; DOVI_BYTES / 8];
        let mut n = 0usize;
        let st = Hdr10Static { max_luminance: 1000.0, min_luminance: 0.005, max_cll: 900, max_fall: 200, primaries: 1, reserved: 0 };
        assert_eq!(unsafe { static_to_dovi(&st, out.as_mut_ptr() as *mut u8, DOVI_BYTES, &mut n) }, 0);
        out.truncate(n.div_ceil(8));
        out
    }

    fn bytes(md: &[u64]) -> &[u8] {
        unsafe { std::slice::from_raw_parts(md.as_ptr() as *const u8, md.len() * 8) }
    }

    fn sdr(flags: u32, peak_nits: f32, min_nits: f32, gamma: u32) -> OutputMode {
        OutputMode { mode: DVVK_OUTPUT_SDR, flags, peak_nits, min_nits, reserved: [gamma, 0, 0, 0] }
    }

    fn f32_at(m: &Map, at: usize) -> f32 {
        f32::from_le_bytes(m.gpu.bytes[at..at + 4].try_into().unwrap())
    }

    /// dvvk_set_output_mode's checks (mode_supported) and the planner's
    /// (dv_map.c sdr_display) take and refuse the same SDR displays: what
    /// callers pass today, CB1's whole range, and requests an older library
    /// would not understand.
    #[test]
    fn sdr_modes_validated() {
        let md = metadata();
        let (power, black, bt2020) = (SDR_POWER, SDR_BLACK, 64);
        let cases = [
            // today's
            (sdr(0, 0.0, 0.0, 0), true),
            (sdr(0, 203.0, 0.0, 0), true),
            (sdr(1 | 2 | 4, 100.0, 0.1, 0), true),
            (sdr(0, 1000.0, 49.0, 0), true),
            (sdr(0, 1000.0, 50.0, 0), false),
            (sdr(0, 1000.5, 0.0, 0), false),
            // CB1's peaks: 20 to 500 (ours to 1000)
            (sdr(0, 20.0, 0.0, 0), true),
            (sdr(0, 19.9, 0.0, 0), false),
            // a pure power, 1.8 to 2.8
            (sdr(power, 100.0, 0.0, 1800), true),
            (sdr(power, 100.0, 0.0, 2800), true),
            (sdr(power, 100.0, 0.0, 1799), false),
            (sdr(power, 100.0, 0.0, 2801), false),
            (sdr(power, 100.0, 0.0, 0), false),
            (sdr(power | 1, 100.0, 0.0, 2200), false),
            (sdr(0, 100.0, 0.0, 2400), false), // a gamma without DVVK_SDR_POWER
            // the black as given: 0 to 5 cd/m2, below the white
            (sdr(black, 100.0, 0.0, 0), true),
            (sdr(power | black, 20.0, 5.0, 2600), true),
            (sdr(power | black, 100.0, 5.01, 2400), false),
            (sdr(power | black, 20.0, 20.0, 2400), false),
            (sdr(black, 100.0, -0.0001, 0), false),
            (sdr(black, 100.0, f32::NAN, 0), false),
            (sdr(0, 20.0, 1.0, 0), false), // without the flag: below white / 20
            // BT.2020, with the rest
            (sdr(bt2020, 0.0, 0.0, 0), true),
            (sdr(power | black | bt2020 | 2 | 8, 100.0, 0.0, 2400), true),
            // what no library knows yet
            (sdr(128, 100.0, 0.0, 0), false),
            (OutputMode { reserved: [0, 1, 0, 0], ..sdr(0, 100.0, 0.0, 0) }, false),
            (OutputMode { reserved: [2400, 0, 0, 1], ..sdr(power, 100.0, 0.0, 2400) }, false),
        ];
        for (mode, ok) in cases {
            assert_eq!(mode_supported(&mode), ok, "{mode:?}");
            assert_eq!(Map::plan(&mode, &DisplayPrimaries::default(), bytes(&md)).is_ok(), ok, "the planner on {mode:?}");
        }
    }

    /// CB1's targets as the plan's display: a pure power with a true zero
    /// black (V = (L / white)^(1 / gamma)), the same curve as BT.1886 or
    /// gamma 2.2 where they coincide, the given black, BT.2020's primaries in
    /// the signal and the map's output matrix; what callers pass today plans
    /// as before.
    #[test]
    fn sdr_targets_plan() {
        let md = metadata();
        let plan = |m: OutputMode| Map::plan(&m, &DisplayPrimaries::default(), bytes(&md)).unwrap();
        let trc = |m: &Map| [1424, 1428, 1432, 1436].map(|at| f32_at(m, at));
        let flags = |m: &Map| u32::from_le_bytes(m.gpu.bytes[336..340].try_into().unwrap());
        // Reference: 100 cd/m2, gamma 2.4, black 0 (light 1 = 10000 cd/m2)
        let reference = plan(sdr(SDR_POWER | SDR_BLACK, 100.0, 0.0, 2400));
        let t = trc(&reference);
        assert!((t[0] - 100.0).abs() < 1e-3 && t[1..] == [0.0, 1.0 / 2.4, 0.0], "{t:?}");
        assert_eq!(f32_at(&reference, 320), 0.0, "the tone curve ends at signal black");
        assert_eq!((reference.signal.max_luminance, reference.signal.min_luminance), (100, 0));
        assert_eq!(reference.signal.primaries, [[32000, 16500], [15000, 30000], [7500, 3000]]);
        // BT.1886 with a true zero black is the same curve
        let bt1886 = trc(&plan(sdr(SDR_BLACK, 100.0, 0.0, 0)));
        assert!((bt1886[0] - 100.0).abs() < 1e-3 && bt1886[1..] == [0.0, 1.0 / 2.4, 0.0], "{bt1886:?}");
        // today's default black (white / 1000) is not a true zero
        let default = plan(sdr(0, 100.0, 0.0, 0));
        assert!(trc(&default)[3] > 0.0 && f32_at(&default, 320) > 0.0);
        assert_eq!(default.signal.min_luminance, 1000);
        // the sampler's weights for the gamut LUT, but with CB1's targets above a zero black (128)
        let floor = plan(sdr(SDR_POWER | SDR_BLACK, 100.0, 0.1, 2400));
        assert_eq!((flags(&reference) & 128, flags(&default) & (64 | 128), flags(&floor) & 128), (0, 0, 128));
        // Bright room: a 2.2 power is DVVK_SDR_GAMMA22's, bytes and all
        let bright = plan(sdr(SDR_POWER | SDR_BLACK, 200.0, 0.0, 2200));
        let g22 = plan(sdr(SDR_GAMMA22 | SDR_BLACK, 200.0, 0.0, 0));
        assert_eq!((bright.key, bright.gpu.bytes), (g22.key, g22.gpu.bytes));
        let t = trc(&bright);
        assert!((t[0] - 50.0).abs() < 1e-3 && t[1..] == [0.0, 1.0 / 2.2, 0.0], "{t:?}");
        // a custom gamma and a black: V = ((L - black) / (white - black))^(1 / gamma)
        let custom = trc(&plan(sdr(SDR_POWER | SDR_BLACK, 50.0, 2.0, 2600)));
        let (lo, hi) = (2.0e-4f32, 50.0e-4f32);
        assert!((custom[0] - 1.0 / (hi - lo)).abs() < 1e-2 && (custom[1] + lo / (hi - lo)).abs() < 1e-6);
        assert_eq!(custom[2], 1.0 / 2.6);
        // BT.2020: its primaries in the signal, another LMS -> RGB, nothing else
        let wide = plan(sdr(SDR_POWER | SDR_BLACK | 64, 100.0, 0.0, 2400));
        assert_eq!(wide.signal.primaries, [[35400, 14600], [8500, 39850], [6550, 2300]]);
        assert_eq!(wide.signal.white, [15635, 16450]);
        assert_eq!(flags(&wide) & !8, flags(&reference) & !8 | 64);
        assert_ne!(wide.gpu.bytes[160..208], reference.gpu.bytes[160..208]);
        assert_eq!(trc(&wide), trc(&reference));
    }

    fn target(mode: u32, flags: u32, peak_nits: f32, min_nits: f32, gamut: u32) -> OutputMode {
        OutputMode { mode, flags, peak_nits, min_nits, reserved: [gamut, 0, 0, 0] }
    }

    /// LLDV takes the displays CB1's policy takes
    /// (dvbridge_policy_validate: peak 50 to 10000, the black's bound by the
    /// VSVDB's version) and nothing else; plain HDR10 as before.
    #[test]
    fn target_modes_validated() {
        let none = DisplayPrimaries::default();
        let v = |edid_version| DisplayPrimaries {
            edid_version,
            xy: [[0.68, 0.32], [0.265, 0.69], [0.15, 0.06]],
            reserved: [0; 3],
        };
        let (h, l) = (DVVK_OUTPUT_HDR10, DVVK_OUTPUT_LLDV);
        let cases = [
            // plain HDR10: no display
            (target(h, 0, 0.0, 0.0, 0), none, true),
            (target(h, 0, 1000.0, 0.0, 0), none, false),
            // LLDV: without primaries the black up to 0.5, a version 1 block 1, version 2 1.029
            (target(l, 0, 600.0, 0.0, 0), none, true),
            (target(l, 1, 600.0, 0.5, 0), none, true),
            (target(l, 0, 600.0, 0.8, 0), none, false),
            (target(l, 0, 600.0, 0.8, 0), v(1), true),
            (target(l, 0, 600.0, 1.02, 0), v(1), false),
            (target(l, 0, 600.0, 1.02, 0), v(2), true),
            (target(l, 0, 600.0, 1.03, 0), v(2), false),
            (target(l, 0, 600.0, 0.0, 0), v(3), false),
            (target(l, 2, 600.0, 0.0, 0), none, false),
            (target(l, 0, 40.0, 0.0, 0), none, false),
            (target(l, 0, 600.0, 0.0, 0), DisplayPrimaries { xy: [[0.0, 0.32], [0.265, 0.69], [0.15, 0.06]], ..v(2) }, false),
            (target(l, 0, 600.0, 0.0, 0), DisplayPrimaries { reserved: [1, 0, 0], ..v(2) }, false),
        ];
        let md = metadata();
        for (mode, display, ok) in cases {
            assert_eq!(mode_supported_with(&mode, &display), ok, "{mode:?} {display:?}");
            assert_eq!(Map::plan(&mode, &display, bytes(&md)).is_ok(), ok, "the planner on {mode:?} {display:?}");
        }
    }

    /// What a player signals: LLDV its display, its useful bits, no
    /// InfoFrame; plain HDR10 the film's, as before.
    #[test]
    fn target_signals() {
        let md = metadata();
        let none = DisplayPrimaries::default();
        let plan = |m: OutputMode, d: &DisplayPrimaries| Map::plan(&m, d, bytes(&md)).unwrap();
        let plain = plan(target(DVVK_OUTPUT_HDR10, 0, 0.0, 0.0, 0), &none);
        assert!(!plain.expert() && plain.signal.max_luminance == 1000);
        let lldv = plan(target(DVVK_OUTPUT_LLDV, 0, 600.0, 0.0, 0), &none);
        assert!(lldv.expert() && lldv.lldv());
        let s = lldv.signal;
        assert_eq!((s.mode, s.eotf, s.max_luminance, s.min_luminance, s.reserved[0]), (4, 2, 600, 0, 12));
        assert_eq!(s.primaries, [[35400, 14600], [8500, 39850], [6550, 2300]]);
        let ten = plan(target(DVVK_OUTPUT_LLDV, 1, 600.0, 0.005, 0), &none);
        assert_eq!((ten.signal.min_luminance, ten.signal.reserved[0]), (50, 10));
        let edid = DisplayPrimaries { edid_version: 2, xy: [[0.6758, 0.3203], [0.2539, 0.6836], [0.1442, 0.0516]], reserved: [0; 3] };
        let own = plan(target(DVVK_OUTPUT_LLDV, 0, 774.87, 0.0, 0), &edid);
        assert_eq!(own.signal.primaries[0], [33790, 16015]);
        assert_eq!(own.signal.max_luminance, 775);
    }
}
