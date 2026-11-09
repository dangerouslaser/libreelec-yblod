//! The C ABI's version and layouts. The numbers are the ones
//! include/dvvk_plan.h and include/dv_engine_vk.h assert in C: a change on
//! either side fails to compile until both agree (and DVVK_ABI_VERSION, with
//! the soname, moves on).

use crate::capi::DvvkFrame;
use crate::overlay::{Dmabuf, SubPart};
use crate::plan::{Plan, PlanDesktop, PlanIn};
use std::mem::{offset_of, size_of};

/// include/dv_engine_vk.h DVVK_ABI_VERSION.
pub const ABI_VERSION: u32 = 3;
/// include/dv_engine_vk.h DVVK_LIBRARY (build.rs reads it from there).
pub const LIBRARY: &str = env!("DVVK_LIBRARY");

#[cfg(target_pointer_width = "64")]
const _: () = {
    assert!(size_of::<PlanIn>() == 160);
    assert!(offset_of!(PlanIn, pts) == 64);
    assert!(offset_of!(PlanIn, rgb_to_lms) == 72);
    assert!(offset_of!(PlanIn, white_nits) == 144);
    assert!(offset_of!(PlanIn, cb1_contract) == 152);
    assert!(offset_of!(PlanIn, dm_options) == 156);
    assert!(size_of::<Plan>() == 82040);
    assert!(offset_of!(Plan, reshape) == 49152);
    assert!(offset_of!(Plan, residual) == 53696);
    assert!(offset_of!(Plan, mmr_params) == 65984);
    assert!(offset_of!(Plan, route) == 66752);
    assert!(offset_of!(Plan, packet_count) == 66900);
    assert!(offset_of!(Plan, chroma_filter) == 66908);
    assert!(offset_of!(Plan, tables_generation) == 66912);
    assert!(offset_of!(Plan, dm_status) == 66916);
    assert!(offset_of!(Plan, gui_coeff) == 66936);
    assert!(offset_of!(Plan, mapping) == 67064);
    assert!(offset_of!(Plan, chroma_mapping) == 69112);
    assert!(offset_of!(Plan, single_table) == 73208);
    assert!(offset_of!(Plan, luma_table) == 79352);
    assert!(offset_of!(Plan, packets) == 81400);
    assert!(size_of::<PlanDesktop>() == 16);
    assert!(size_of::<DvvkFrame>() == 200);
    assert!(offset_of!(DvvkFrame, bl_surface) == 160);
    assert!(offset_of!(DvvkFrame, metadata) == 168);
    assert!(offset_of!(DvvkFrame, metadata_size) == 176);
    assert!(offset_of!(DvvkFrame, output) == 184);
    assert!(offset_of!(DvvkFrame, flags) == 188);
    assert!(offset_of!(DvvkFrame, release_wait) == 192);
    assert!(size_of::<SubPart>() == 48);
    assert!(offset_of!(SubPart, stride) == 24);
    assert!(offset_of!(SubPart, color) == 32);
    assert!(offset_of!(SubPart, data) == 40);
    assert!(size_of::<Dmabuf>() == 80);
    assert!(offset_of!(Dmabuf, modifier) == 16);
    assert!(offset_of!(Dmabuf, num_planes) == 24);
    assert!(offset_of!(Dmabuf, fd) == 28);
    assert!(offset_of!(Dmabuf, offset) == 44);
    assert!(offset_of!(Dmabuf, stride) == 60);
};

/// The ABI this library was built with (DVVK_ABI_VERSION): callers check it
/// at load, before anything else.
#[no_mangle]
pub extern "C" fn dvvk_abi_version() -> u32 {
    ABI_VERSION
}

#[cfg(test)]
mod tests {
    #[test]
    fn header_and_rust_agree() {
        let header = include_str!("../include/dv_engine_vk.h");
        let version = header.lines().find_map(|l| l.strip_prefix("#define DVVK_ABI_VERSION ")).unwrap();
        assert_eq!(version.trim().trim_end_matches('u').parse::<u32>().unwrap(), super::ABI_VERSION);
        assert!(super::LIBRARY.starts_with("libdv_engine_vk.so."));
        assert!(crate::plan::layout_matches());
    }
}
