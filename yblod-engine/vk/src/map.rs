//! The output colour mapping (include/dvvk_map.h, docs/hdr10-output.md): the
//! output mode the caller set, and its per-frame plan from yblod/dv_map.c.

use std::mem::{offset_of, size_of};

pub const DVVK_OUTPUT_DV: u32 = 0;
pub const DVVK_OUTPUT_HDR10: u32 = 1;
/// The 3D LUT's points per axis (dvvk_map_gpu.lut_n; dv_map.c sets it).
pub const LUT_N: u32 = 65;
/// map_bake's threshold: cells interpolating worse than this (12-bit codes)
/// are computed exactly.
pub const BAKE_THRESH: f32 = 0.5;

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
    pub bytes: [u8; 1408],
}

/// include/dvvk_map.h dvvk_map.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Map {
    pub gpu: MapGpu,
    pub key: u64,
    pub signal: HdrSignal,
}

const _: () = {
    assert!(size_of::<OutputMode>() == 32);
    assert!(size_of::<HdrSignal>() == 48);
    assert!(offset_of!(HdrSignal, max_luminance) == 24);
    assert!(size_of::<MapGpu>() == 1408);
    assert!(offset_of!(Map, key) == 1408);
    assert!(offset_of!(Map, signal) == 1416);
};

extern "C" {
    fn dvvk_map_plan(mode: *const OutputMode, metadata: *const u8, size: usize, out: *mut Map) -> i32;
    fn dvvk_map_set_black(gpu: *mut MapGpu, black: *const u32);
}

impl Map {
    /// The stream's black (12-bit Y, Cb, Cr) and its exact output codes.
    pub fn set_black(&mut self, black: [u32; 3]) {
        unsafe { dvvk_map_set_black(&mut self.gpu, black.as_ptr()) };
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
        let mut out = Box::new(Map { gpu: MapGpu { bytes: [0; 1408] }, key: 0, signal: HdrSignal::default() });
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
