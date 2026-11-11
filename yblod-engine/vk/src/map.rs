//! The output colour mapping (include/dvvk_map.h, docs/hdr10-output.md): the
//! output mode the caller set (HDR10, HDR10+ or SDR), and its per-frame plan
//! from yblod/dv_map.c.

use std::mem::{offset_of, size_of};

pub const DVVK_OUTPUT_DV: u32 = 0;
pub const DVVK_OUTPUT_HDR10: u32 = 1;
pub const DVVK_OUTPUT_HDR10PLUS: u32 = 2;
pub const DVVK_OUTPUT_SDR: u32 = 3;
/// dvvk_output_mode.flags an SDR output takes (DVVK_SDR_*: gamma 2.2,
/// limited range, no dither).
pub const SDR_FLAGS: u32 = 7;
/// The 3D LUT's points per axis (dvvk_map_gpu.lut_n; dv_map.c sets it).
pub const LUT_N: u32 = 65;
/// map_bake's threshold: cells interpolating worse than this (12-bit codes)
/// are computed exactly.
pub const BAKE_THRESH: f32 = 0.5;
/// The same for SDR output, in its 8-bit codes, and at more points of each
/// cell (map_bake.comp): on the test titles' frames the worst sample outside
/// the marked cells is then 0.71 of a code (0.5: 1.06; 0.25 marks 86 % of a
/// dark frame's pixels instead of 34 %).
pub const BAKE_THRESH_SDR: f32 = 0.35;
/// include/dvvk_map.h DVVK_MAP_TABLE_WORDS: SDR output's tables (the dither
/// pattern, then the gamut LUT).
pub const TABLE_WORDS: usize = 64 * 64 + 2 * 48 * 32 * 256;
/// The gamut LUT in the tables: its first word, and its points (I, C, h).
pub const GAMUT_AT: usize = 64 * 64;
pub const GAMUT_SIZE: [u32; 3] = [48, 32, 256];
/// dvvk_map_gpu.flags: DVVK_MAP_SDR.
const MAP_SDR: u32 = 4;

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

/// include/dvvk_map.h dvvk_map_gpu: the GPU's parameters, as bytes.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct MapGpu {
    pub bytes: [u8; 1472],
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
    assert!(size_of::<HdrSignal>() == 48);
    assert!(offset_of!(HdrSignal, max_luminance) == 24);
    assert!(size_of::<MapGpu>() == 1472);
    assert!(offset_of!(Map, key) == 1472);
    assert!(offset_of!(Map, signal) == 1480);
    assert!(offset_of!(Map, gamut_prim) == 1528);
    assert!(offset_of!(Map, gamut_key) == 1600);
    assert!(size_of::<Map>() == 1608);
};

extern "C" {
    fn dvvk_map_plan(mode: *const OutputMode, metadata: *const u8, size: usize, out: *mut Map) -> i32;
    fn dvvk_map_tables(map: *const Map, tables: *mut u32);
    fn dvvk_map_set_black(gpu: *mut MapGpu, tables: *const u32, black: *const u32);
}

/// Whether dvvk_set_output_mode takes `mode` (dv_map.c's sdr_display for
/// SDR: a frame's plan would refuse the rest one by one).
pub fn mode_supported(mode: &OutputMode) -> bool {
    match mode.mode {
        DVVK_OUTPUT_DV | DVVK_OUTPUT_HDR10 | DVVK_OUTPUT_HDR10PLUS => {
            mode.flags == 0 && mode.peak_nits == 0.0 && mode.min_nits == 0.0
        }
        DVVK_OUTPUT_SDR => {
            let white = if mode.peak_nits > 0.0 { mode.peak_nits } else { 203.0 };
            let black = if mode.min_nits > 0.0 { mode.min_nits } else { white / 1000.0 };
            mode.flags & !SDR_FLAGS == 0
                && mode.peak_nits >= 0.0
                && mode.min_nits >= 0.0
                && (40.0..=1000.0).contains(&white)
                && black < white / 20.0
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

    /// SDR output's tables (TABLE_WORDS words) for this mapping: when
    /// gamut_key changes (tens of milliseconds).
    pub fn tables(&self, words: &mut [u32]) {
        assert!(words.len() >= TABLE_WORDS);
        unsafe { dvvk_map_tables(self, words.as_mut_ptr()) };
    }

    /// The stream's black (12-bit Y, Cb, Cr) and its exact output codes.
    /// `tables`: SDR output's (current for this mapping), else unused.
    pub fn set_black(&mut self, black: [u32; 3], tables: Option<&[u32]>) {
        assert!(tables.is_some_and(|t| t.len() >= TABLE_WORDS) || !self.sdr());
        let tables = tables.map_or(std::ptr::null(), |t| t.as_ptr());
        unsafe { dvvk_map_set_black(&mut self.gpu, tables, black.as_ptr()) };
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
    pub fn plan(mode: &OutputMode, metadata: &[u8]) -> Result<Box<Map>, i32> {
        let mut out = Box::new(Map {
            gpu: MapGpu { bytes: [0; 1472] },
            key: 0,
            signal: HdrSignal::default(),
            gamut_prim: [[0.0; 8]; 2],
            gamut_luma: [0.0; 2],
            gamut_key: 0,
        });
        // AVDOVIMetadata is read in place: it must be aligned as ffmpeg allocates it.
        let r = if metadata.as_ptr() as usize % 8 == 0 {
            unsafe { dvvk_map_plan(mode, metadata.as_ptr(), metadata.len(), &mut *out) }
        } else {
            let mut copy = vec![0u64; metadata.len().div_ceil(8)];
            let bytes = unsafe { std::slice::from_raw_parts_mut(copy.as_mut_ptr() as *mut u8, metadata.len()) };
            bytes.copy_from_slice(metadata);
            unsafe { dvvk_map_plan(mode, copy.as_ptr() as *const u8, metadata.len(), &mut *out) }
        };
        if r == 0 {
            Ok(out)
        } else {
            Err(r)
        }
    }
}
