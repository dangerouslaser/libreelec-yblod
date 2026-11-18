//! The upscaler (dvvk_set_scaler): how a picture smaller than its
//! destination rectangle is enlarged. Bilinear is the pack's own
//! (pack.comp source_linear). FSR 1 (AMD FidelityFX Super Resolution 1,
//! shaders/common/fsr1.glsl) makes the luma instead: EASU in its own pass
//! (fsr1_easu.comp) at the destination's size, then RCAS in the pack as it
//! reads that. Chroma stays bilinear (as mpv's FSR port does it, a luma-only
//! hook), and every output mode maps the result as before. Reductions and
//! unscaled pictures are never touched.

/// dvvk_set_scaler's methods (include/dv_engine_vk.h DVVK_SCALER_*).
pub const DVVK_SCALER_BILINEAR: u32 = 0;
pub const DVVK_SCALER_FSR1_EASU: u32 = 1;
pub const DVVK_SCALER_FSR1_RCAS: u32 = 2;

/// Whether this library has the method.
pub fn valid(method: u32) -> bool {
    matches!(method, DVVK_SCALER_BILINEAR | DVVK_SCALER_FSR1_EASU | DVVK_SCALER_FSR1_RCAS)
}

/// The method a picture of `source` placed at `dest` takes: the chosen one
/// for an enlargement (neither side smaller, one larger), bilinear otherwise
/// (EASU is a 1x to 4x area upscaler, not a reduction filter).
pub fn effective(method: u32, source: [u32; 2], dest: [u32; 2]) -> u32 {
    let enlarged = dest[0] >= source[0] && dest[1] >= source[1] && dest != source;
    if enlarged {
        method
    } else {
        DVVK_SCALER_BILINEAR
    }
}

/// fsr1_easu.comp's push constants.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct EasuPush {
    pub source: [u32; 2],
    pub dest: [u32; 2],
    /// FsrEasuCon's con0: an output pixel's position in the source is
    /// ip * scale + offset
    pub scale: [f32; 2],
    pub offset: [f32; 2],
    /// the first output pixel of the dispatch (multiples of 16)
    pub origin: [u32; 2],
}

/// EASU's constants as AMD's FsrEasuCon computes them (f32, the viewport the
/// whole source), for the output pixels from `origin`. tools/dvvk-scaler-compare.c
/// computes the same numbers.
pub fn easu_push(source: [u32; 2], dest: [u32; 2], origin: [u32; 2]) -> EasuPush {
    let axis = |s: u32, d: u32| {
        let (s, rcp) = (s as f32, 1.0f32 / d as f32);
        (s * rcp, 0.5f32 * s * rcp - 0.5f32)
    };
    let (x, y) = (axis(source[0], dest[0]), axis(source[1], dest[1]));
    EasuPush { source, dest, scale: [x.0, y.0], offset: [x.1, y.1], origin }
}

/// Where fsr1_easu.comp runs, in the destination's pixels: the film's part
/// of the destination rectangle (`active` and `placement` in the canvas, as
/// the plan has them) and RCAS's one pixel beyond it, rounded out to the
/// pass's 16x16 workgroups. (origin, workgroups); None: nothing of the film
/// shows.
pub fn easu_region(active: [u32; 4], placement: [u32; 4]) -> Option<([u32; 2], [u32; 2])> {
    let [px, py, dw, dh] = placement;
    let x0 = active[0].max(px) - px;
    let y0 = active[1].max(py) - py;
    let x1 = active[2].min(px + dw).saturating_sub(px);
    let y1 = active[3].min(py + dh).saturating_sub(py);
    if x1 <= x0 || y1 <= y0 {
        return None;
    }
    let origin = [x0.saturating_sub(1) & !15, y0.saturating_sub(1) & !15];
    let (x1, y1) = ((x1 + 1).min(dw), (y1 + 1).min(dh));
    Some((origin, [(x1 - origin[0]).div_ceil(16), (y1 - origin[1]).div_ceil(16)]))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn methods() {
        for m in [DVVK_SCALER_BILINEAR, DVVK_SCALER_FSR1_EASU, DVVK_SCALER_FSR1_RCAS] {
            assert!(valid(m));
        }
        // unknown methods are refused (dvvk_set_scaler: -2), never taken as bilinear
        for m in [3, 4, 0x100, u32::MAX] {
            assert!(!valid(m), "{m}");
        }
    }

    #[test]
    fn c_api() {
        let header = include_str!("../include/dv_engine_vk.h");
        let line = format!(
            "enum {{ DVVK_SCALER_BILINEAR = {DVVK_SCALER_BILINEAR}, DVVK_SCALER_FSR1_EASU = {DVVK_SCALER_FSR1_EASU}, \
             DVVK_SCALER_FSR1_RCAS = {DVVK_SCALER_FSR1_RCAS} }};"
        );
        assert!(header.contains(&line), "{line}");
        assert!(header.contains("int dvvk_set_scaler(dvvk_engine *, uint32_t method);"));
        // a NULL engine (the methods themselves: `methods`, Engine::set_scaler)
        assert_eq!(unsafe { crate::capi::dvvk_set_scaler(std::ptr::null_mut(), DVVK_SCALER_FSR1_EASU) }, -1);
    }

    #[test]
    fn only_enlargements() {
        let fsr = DVVK_SCALER_FSR1_RCAS;
        assert_eq!(effective(fsr, [1920, 1080], [3840, 2160]), fsr);
        assert_eq!(effective(DVVK_SCALER_FSR1_EASU, [1920, 1080], [3840, 2160]), DVVK_SCALER_FSR1_EASU);
        // one side larger, the other the same
        assert_eq!(effective(fsr, [3840, 1600], [3840, 2160]), fsr);
        assert_eq!(effective(fsr, [1440, 1080], [1920, 1080]), fsr);
        // unscaled, reduced, or larger one way and smaller the other: bilinear
        assert_eq!(effective(fsr, [3840, 2160], [3840, 2160]), DVVK_SCALER_BILINEAR);
        assert_eq!(effective(fsr, [3840, 2160], [1920, 1080]), DVVK_SCALER_BILINEAR);
        assert_eq!(effective(fsr, [3840, 2160], [4096, 2000]), DVVK_SCALER_BILINEAR);
        assert_eq!(effective(DVVK_SCALER_BILINEAR, [1920, 1080], [3840, 2160]), DVVK_SCALER_BILINEAR);
    }

    #[test]
    fn easu_constants() {
        // FsrEasuCon: 2x is 0.5 and 0.5 * 0.5 - 0.5
        let p = easu_push([1920, 1080], [3840, 2160], [0, 0]);
        assert_eq!((p.scale, p.offset), ([0.5, 0.5], [-0.25, -0.25]));
        let p = easu_push([1280, 720], [3836, 2156], [16, 32]);
        assert_eq!(p.scale[0], 1280f32 * (1.0 / 3836f32));
        assert_eq!(p.offset[1], 0.5 * 720f32 * (1.0 / 2156f32) - 0.5);
        assert_eq!(std::mem::size_of::<EasuPush>(), 40);
    }

    #[test]
    fn regions() {
        // full screen, no bars: everything
        assert_eq!(easu_region([0, 0, 3840, 2160], [0, 0, 3840, 2160]), Some(([0, 0], [240, 135])));
        // a letterboxed film: its rows and one beyond, from a workgroup boundary
        assert_eq!(easu_region([0, 276, 3840, 1884], [0, 0, 3840, 2160]), Some(([0, 272], [240, 101])));
        // a destination in the canvas: the region is in the destination's pixels
        assert_eq!(easu_region([100, 50, 3836, 2154], [4, 2, 3836, 2156]), Some(([80, 32], [235, 133])));
        assert_eq!(easu_region([0, 0, 100, 100], [200, 200, 1920, 1080]), None);
    }
}
