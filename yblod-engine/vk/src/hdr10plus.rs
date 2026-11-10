//! HDR10+ (YBLOD 0.4.0): the Rust view of include/dv_engine_vk.h's
//! dvvk_hdr10plus_packet / dvvk_hdr10plus_to_dovi, whose work is CroqueMr's CB1
//! HDR10+ host code in yblod-engine/src (yblod_hdr10plus.c and the cb1_*.c
//! ported at the commit their headers name).

use std::mem::{offset_of, size_of};

/// include/dv_engine_vk.h dvvk_hdr10plus_metadata.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct Packet {
    pub vsif: [u8; 31],
    pub application_version: u8,
    pub statistics_ticket: u64,
    pub coverage: u32,
    pub reason: u32,
    pub effective_l1: [u16; 3],
    pub l3_used: u16,
    pub maximum_curve_pq_error: f64,
    pub maximum_color_pq_error: f64,
    pub average_maxrgb: f64,
    pub maxscl: [f64; 3],
    pub pixels: u64,
    pub reserved: [u32; 4],
}

/// include/dv_engine_vk.h dvvk_hdr10_static.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct Hdr10Static {
    pub max_luminance: f32,
    pub min_luminance: f32,
    pub max_cll: u16,
    pub max_fall: u16,
    pub reserved: [u32; 2],
}

/// include/dv_engine_vk.h dvvk_hdr10plus_dovi_info.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct DoviInfo {
    pub l1_min: u16,
    pub l1_max: u16,
    pub l1_avg: u16,
    pub source_min_pq: u16,
    pub source_max_pq: u16,
    pub source_fields: u8,
    pub estimated_fields: u8,
    pub untranslated_curve: u8,
    pub untranslated_saturation: u8,
    pub scene_refresh: u8,
    pub pad: [u8; 3],
    pub reserved: [u32; 4],
}

const _: () = {
    assert!(size_of::<Packet>() == 128);
    assert!(offset_of!(Packet, statistics_ticket) == 32);
    assert!(offset_of!(Packet, average_maxrgb) == 72);
    assert!(size_of::<Hdr10Static>() == 20);
    assert!(size_of::<DoviInfo>() == 36);
};

/// DVVK_HDR10PLUS_DOVI_BYTES.
pub const DOVI_BYTES: usize = 8192;

extern "C" {
    fn yb_hdr10plus_packet(
        metadata: *const u8,
        bytes: usize,
        words: *const u32,
        flags: u32,
        overlay: i32,
        out: *mut Packet,
    ) -> i32;
    fn yb_hdr10plus_to_dovi(
        hdr10plus: *const u8,
        size: usize,
        hdr10: *const Hdr10Static,
        previous: *const u8,
        out: *mut u8,
        capacity: usize,
        out_size: *mut usize,
        info: *mut DoviInfo,
    ) -> i32;
}

/// The packet of a frame with this AVDOVIMetadata (8-aligned) and statistics record.
pub fn packet(metadata: &[u8], words: &[u32; crate::engine::STATS_WORDS], flags: u32, overlay: bool, out: &mut Packet) -> i32 {
    unsafe { yb_hdr10plus_packet(metadata.as_ptr(), metadata.len(), words.as_ptr(), flags, overlay as i32, out) }
}

/// # Safety
/// The pointers as dvvk_hdr10plus_to_dovi documents them.
#[allow(clippy::too_many_arguments)]
pub unsafe fn to_dovi(
    hdr10plus: *const u8,
    size: usize,
    hdr10: *const Hdr10Static,
    previous: *const u8,
    out: *mut u8,
    capacity: usize,
    out_size: *mut usize,
    info: *mut DoviInfo,
) -> i32 {
    yb_hdr10plus_to_dovi(hdr10plus, size, hdr10, previous, out, capacity, out_size, info)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::plan::{Plan, PlanIn, PlanState, EL_ANNEXB, ROUTE_SINGLE};

    extern "C" {
        fn dvvk_test_hdr10plus_c(count: *mut u32) -> u32;
    }

    /// CB1's HDR10+ software tests, ported unchanged (byte layout, rational
    /// units, curve quantization, invalid inputs, L1/L3/L2/L8 coverage, inputs
    /// left unchanged), its describe checks, and YBLOD's glue (yblod/tests).
    #[test]
    fn cb1_and_yblod_c_tests() {
        let mut count = 0;
        let failures = unsafe { dvvk_test_hdr10plus_c(&mut count) };
        assert!(count > 300, "{count} checks ran");
        assert_eq!(failures, 0, "{failures} of {count} C checks failed (stderr)");
    }

    extern "C" {
        fn yb_test_hdr10plus_fixture(out: *mut u8, capacity: usize) -> usize;
    }

    /// HDR10+ -> Dolby Vision: the metadata plays as Profile 8.1 through the
    /// planner: the single-layer route, an identity composer (the 12-bit
    /// table is the 10-bit code scaled), the L1 in the packet.
    #[test]
    fn to_dovi_plans() {
        let mut src = vec![0u64; 4096];
        let size = unsafe { yb_test_hdr10plus_fixture(src.as_mut_ptr() as *mut u8, 32768) };
        assert!(size > 0);
        let mut out = vec![0u64; DOVI_BYTES / 8];
        let (mut n, mut info) = (0usize, DoviInfo::default());
        let st = Hdr10Static { max_luminance: 1000.0, min_luminance: 0.005, max_cll: 900, max_fall: 200, reserved: [0; 2] };
        let r = unsafe {
            to_dovi(src.as_ptr() as *const u8, size, &st, std::ptr::null(), out.as_mut_ptr() as *mut u8, DOVI_BYTES, &mut n, &mut info)
        };
        assert_eq!(r, 0);
        assert_eq!((info.l1_max, info.l1_avg), (3079, 1738));
        let md = unsafe { std::slice::from_raw_parts(out.as_ptr() as *const u8, n) };
        let input = PlanIn {
            width: 3840,
            height: 2160,
            x: 0,
            y: 0,
            dw: 0,
            dh: 0,
            chroma_top_left: 1,
            has_el: 0,
            nv12: 0,
            el_scaler: EL_ANNEXB,
            fel: 1,
            packet_id: 0,
            refresh: 0,
            overlay: 0,
            overlay_visible_before: 0,
            pts: 0,
            rgb_to_lms: [0.0; 9],
            white_nits: 203.0,
            cb1_contract: 1,
            dm_options: 0,
        };
        let mut plan = Plan::boxed();
        let mut state = PlanState::new().unwrap();
        assert_eq!(plan.fill(&input, None, &mut state, md), 0);
        assert_eq!(plan.route, ROUTE_SINGLE);
        // identity: every 10-bit code to the same 12-bit level (x4, as the
        // polynomial y = x maps code / 1024 to 12 bits)
        for c in 0..3 {
            for x in [0usize, 64, 512, 940, 1023] {
                assert_eq!(plan.single_table[c][x] as usize, x * 4, "component {c} code {x}");
            }
        }
        // the packet's payload: the L1 block (level 1: 3 x 16-bit, 0 3079 1738)
        let p = &plan.packets;
        let payload = &p[5..124];
        let l1 = payload.windows(11).position(|w| w[..5] == [0, 0, 0, 6, 1]).expect("L1 in the payload");
        let f = &payload[l1 + 5..l1 + 11];
        assert_eq!([u16::from_be_bytes([f[0], f[1]]), u16::from_be_bytes([f[2], f[3]]), u16::from_be_bytes([f[4], f[5]])], [0, 3079, 1738]);
        // and the mastering display (source_max_pq at payload bytes 66-67)
        assert_eq!(u16::from_be_bytes([payload[66], payload[67]]), 3079);
    }
}
