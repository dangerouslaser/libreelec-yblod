//! The engine: a frame's plan (yblod's host code), its surfaces imported once,
//! the route's shaders and the pack into an output buffer.
//!
//! Phase 1: staged shaders 1:1 with yblod's kernels, one synchronous submit
//! per frame (the comparison harness). The asynchronous ring is phase 2.

use crate::device::{Device, Error, Result};
use crate::gpu::{self, Bind, DeviceBuffer, HostBuffer, OneShot, Pipeline, PushDescriptor};
use crate::interop::{dmabuf, va};
use crate::overlay::{self, Sources};
use crate::plan::{self, Plan, PlanIn};
use ash::vk;
use std::collections::HashMap;
extern "C" {
    fn dvvk_cb1_coeff(metadata: *const u8, nv12: u32, out: *mut f32) -> i32;
    fn dvvk_cb1_luts(degamma: *mut f32, pq: *mut f32);
}

pub const CANVAS_W: u32 = 3840;
pub const CANVAS_H: u32 = 2160;
const MAX_W: u32 = 4096;
const MAX_H: u32 = 4096;

pub struct FrameIn<'a> {
    pub plan: PlanIn,
    pub bl_surface: u32,
    pub el_surface: u32,
    pub metadata: &'a [u8],
    pub output: u32,
    /// The overlay comes from the engine's sources (set_subtitles /
    /// set_shell): whether there is one, and the metadata's overlay edge,
    /// are the engine's to decide.
    pub auto_overlay: bool,
    /// Explicit sync: the frame writes its output only once the release
    /// timeline reaches this point (the compositor is done with the buffer).
    pub release_wait: u64,
    /// Desktop mode: static graphics display management (the film is a small
    /// part of a frame the desktop fills).
    pub desktop: bool,
}

pub struct Output {
    buffer: dmabuf::ImportedBuffer,
    stride: u32,
    fd: i32, // a dup, for the implicit fence
}

#[repr(C)]
#[derive(Clone, Copy)]
struct PackPush {
    active: [u32; 4],
    black: [u32; 4],
    placement: [u32; 4],
    w: u32,
    h: u32,
    stride_words: u32,
    packet_count: u32,
    top_left: u32,
    source_w: u32,
    source_h: u32,
    el_method: u32,     // plan::EL_METHOD_*: the fused FEL pack's EL upsampling
    gui_flags: u32,     // the fused overlay: 1 invalidate the cache, 2 the shell rows bottom first
    origin: [u32; 2],   // the dispatch's first workgroup (a part of the canvas, damage.rs)
    chroma_filter: u32, // sited pack: 1 CB1's Annex B 4:2:2 filters
}

#[repr(C)]
#[derive(Clone, Copy)]
struct PreparePush {
    w: u32,
    h: u32,
    has_shell: u32,
    has_subs: u32,
    tiles_x: u32,
    tile: u32,
    origin: [u32; 2],
    invalidate: u32,
    flip: u32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct ResizePush {
    source: [u32; 2],
    dest: [u32; 2],
    top_left: u32,
}

struct FelPipelines {
    vertical_pair: Pipeline,
    // 32-bit stores, two columns per invocation (DVVK_VERIFY's reference keeps vertical_pair)
    vertical_pair_w32: Pipeline,
    luma_phase_guide: Pipeline,
    phase_vertical_uv: Pipeline,
    mmr_dual_horizontal: Pipeline,
    scale_horizontal: Pipeline,
    table_add: Pipeline,
    mmr_dual: Pipeline,        // mmr64_lut_dual (EL planes already full chroma size)
    mmr_single: [Pipeline; 3], // mmr64_lut, mmr96, mmr (128)
    equal: [Pipeline; 3],      // luma_equal, phase, phase_guide (full-size EL)
    piecewise: [Pipeline; 4],  // 4:2:2 P010, 4:2:2 P010 order-2 chroma, 4:2:0 NV12, 4:2:0 P010 (CB1)
}

// The pack variants: [(source * PACK_OVERLAYS + overlay) * PACK_KINDS + kind];
// source 0 staged planes, 1 fused single layer, 2 fused FEL; overlay 0 none,
// 1 prepared, 2 fused shell, 3 native CB1; kind plan::PACK_*.
const PACK_SOURCES: u32 = 3;
const PACK_OVERLAYS: u32 = 4;
const PACK_KINDS: u32 = 3;
// The Annex B (CB1) sited pack, sources 0 and 1: [source * 3 + i].
const ANNEXB_OVERLAYS: [u32; 3] = [0, 3, 1];
// Every other pipeline Engine::new creates: fel_chroma, the 18 staged FEL /
// piecewise kernels (FelPipelines), single_polynomial, overlay_prepare x2,
// resize_prepare, cb1_tiles. (prepare_end checks the total.)
// And map_bake's three passes (the HDR10 output's 3D LUT), map_fixup.
const OTHER_PIPELINES: u32 = 1 + 18 + 1 + 2 + 1 + 1 + 3 + 1;

/// What of a frame's plan picks its pack variant.
#[derive(Clone, Copy, Debug)]
struct PackRoute {
    route: u32,
    equal: u32,
    el_method: u32,
    pack: u32,
    chroma_filter: u32,
}

impl PackRoute {
    fn of(p: &Plan) -> PackRoute {
        PackRoute { route: p.route, equal: p.equal, el_method: p.el_method, pack: p.pack, chroma_filter: p.chroma_filter }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum PackVariant {
    /// Engine::pack_annexb[i]: CB1's sited pack with the Annex B chroma tile.
    Annexb(usize),
    /// Engine::pack[i].
    Regular(usize),
}

/// Where the pack's samples come from: 0 the staged planes, 1 fused single
/// layer, 2 fused FEL (pass A chroma + the pack's luma).
fn pack_source(r: &PackRoute) -> u32 {
    if r.route == plan::ROUTE_SINGLE && r.pack != plan::PACK_RESIZED {
        // Resized frames read 4 taps per sample: cheaper from the planes.
        1
    } else if r.route == plan::ROUTE_DUAL && r.equal == 0 && r.el_method == plan::EL_METHOD_BILINEAR {
        // Bilinear is fused: its 2-tap EL costs little in the pack's luma.
        // Annex B stays staged: fused (its vertical taps shared through a
        // workgroup tile), 1917 took 12.8 ms against 11.1 ms staged on
        // Tiger Lake at a fixed 1000 MHz (the fused pack's luma costs more
        // than the staged kernels save).
        2
    } else {
        0
    }
}

/// The frame's source and pack variant for overlay kind `overlay` (0 none,
/// 1 prepared, 2 fused shell, 3 native CB1).
fn select_pack(r: &PackRoute, overlay: u32) -> (u32, PackVariant) {
    let source = pack_source(r);
    if r.chroma_filter != 0 && r.pack == plan::PACK_SITED && source == 1 {
        if let Some(k) = ANNEXB_OVERLAYS.iter().position(|&o| o == overlay) {
            return (source, PackVariant::Annexb(k));
        }
    }
    (source, PackVariant::Regular(((source * PACK_OVERLAYS + overlay) * PACK_KINDS + r.pack) as usize))
}

/// The pack's dispatches: (first workgroup, workgroups) over the canvas, or
/// per damage rectangle (x aligned to damage::WG_W, rows rounded out to wg_h).
fn partition(regions: Option<&[crate::damage::Rect]>, wg_h: u32) -> Vec<([u32; 2], [u32; 2])> {
    use crate::damage::WG_W;
    let rows = CANVAS_H.div_ceil(wg_h);
    match regions {
        None => vec![([0, 0], [(CANVAS_W / 4).div_ceil(32), rows])],
        Some(rects) => rects
            .iter()
            .map(|r| {
                let (top, bottom) = (r[1] / wg_h, r[3].div_ceil(wg_h).min(rows));
                ([r[0] / WG_W, top], [(r[2] - r[0]) / WG_W, bottom - top])
            })
            .collect(),
    }
}

#[cfg(test)]
mod pack_tests {
    use super::*;

    fn routes() -> impl Iterator<Item = PackRoute> {
        let mut v = Vec::new();
        for route in [plan::ROUTE_DUAL, plan::ROUTE_SINGLE, plan::ROUTE_PIECEWISE] {
            for equal in 0..2 {
                for el_method in 0..2 {
                    for pack in [plan::PACK_SITED, plan::PACK_422, plan::PACK_RESIZED] {
                        for chroma_filter in 0..2 {
                            v.push(PackRoute { route, equal, el_method, pack, chroma_filter });
                        }
                    }
                }
            }
        }
        v.into_iter()
    }

    #[test]
    fn every_route_and_overlay_has_one_built_variant() {
        for r in routes() {
            for overlay in 0..PACK_OVERLAYS {
                let (source, v) = select_pack(&r, overlay);
                assert!(source < PACK_SOURCES);
                match v {
                    PackVariant::Annexb(i) => {
                        assert!(i < ANNEXB_OVERLAYS.len());
                        assert_eq!(ANNEXB_OVERLAYS[i], overlay);
                        assert!(r.chroma_filter != 0 && r.pack == plan::PACK_SITED && source == 1);
                    }
                    PackVariant::Regular(i) => {
                        assert_eq!(i as u32, (source * PACK_OVERLAYS + overlay) * PACK_KINDS + r.pack);
                        assert!((i as u32) < PACK_SOURCES * PACK_OVERLAYS * PACK_KINDS);
                        // the CB1 sited pack of a prepared source takes the tiled variant whenever one exists
                        assert!(!(r.chroma_filter != 0 && r.pack == plan::PACK_SITED && source == 1 && overlay != 2));
                    }
                }
            }
        }
    }

    #[test]
    fn sources() {
        let r = |route, equal, el_method, pack| PackRoute { route, equal, el_method, pack, chroma_filter: 0 };
        assert_eq!(pack_source(&r(plan::ROUTE_SINGLE, 0, 0, plan::PACK_SITED)), 1);
        assert_eq!(pack_source(&r(plan::ROUTE_SINGLE, 0, 0, plan::PACK_RESIZED)), 0);
        assert_eq!(pack_source(&r(plan::ROUTE_DUAL, 0, 1, plan::PACK_RESIZED)), 2);
        assert_eq!(pack_source(&r(plan::ROUTE_DUAL, 0, 0, plan::PACK_SITED)), 0);
        assert_eq!(pack_source(&r(plan::ROUTE_DUAL, 1, 1, plan::PACK_SITED)), 0);
        assert_eq!(pack_source(&r(plan::ROUTE_PIECEWISE, 0, 1, plan::PACK_422)), 0);
    }

    /// What the planner (yblod/plan.c) and the engine decide that picks a pack:
    /// the route the metadata gives, the EL's spatial resampling flag, the EL
    /// scaler, NV12, CB1's contract asked for, a resized (boxed) picture,
    /// desktop mode, the overlay, the shell's buffer (none, sRGB, linear half
    /// float, scaled), subtitles, DVVK_OVERLAY_PREPARE, the overlay white at
    /// 203, CB1's overlay coefficients, the sources read.
    #[derive(Clone, Copy, Debug)]
    struct Routing {
        route: u32,
        el_flag: u32,
        el_scaler: u32,
        nv12: bool,
        cb1: bool,
        resized: bool,
        desktop: bool,
        overlay: bool,
        shell: u32,
        subs: bool,
        overlay_prepare: bool,
        white_203: bool,
        cb1_coeff: bool,
        sources_used: bool,
    }

    fn routings() -> Vec<Routing> {
        let mut v = Vec::new();
        for bits in 0u32..1 << 12 {
            let b = |i: u32| bits >> i & 1 != 0;
            for route in [plan::ROUTE_DUAL, plan::ROUTE_SINGLE, plan::ROUTE_PIECEWISE] {
                for shell in 0..4 {
                    v.push(Routing {
                        route,
                        el_flag: b(0) as u32,
                        el_scaler: b(1) as u32,
                        nv12: b(2),
                        cb1: b(3),
                        resized: b(4),
                        desktop: b(5),
                        overlay: b(6),
                        shell,
                        subs: b(7),
                        overlay_prepare: b(8),
                        white_203: b(9),
                        cb1_coeff: b(10),
                        sources_used: b(11),
                    });
                }
            }
        }
        v
    }

    /// The contract after the engine's rules (submit: no CB1 for a resized
    /// picture or desktop mode), as plan.c's dvvk_plan_frame_state sees it.
    fn contract(r: &Routing) -> bool {
        r.cb1 && !r.resized && !r.desktop
    }

    /// plan.c's pack fields for these inputs; None: it refuses the picture.
    fn planned(r: &Routing) -> Option<PackRoute> {
        let contract = contract(r);
        let full = !r.nv12 && !contract; // DV_SINGLE_FULL_HEIGHT
        let resized_pack = if r.resized { plan::PACK_RESIZED } else { plan::PACK_SITED };
        // el_scaler 1 Annex B, 0 bilinear; the contract is always Annex B
        let bilinear = r.el_scaler == 0 && !contract;
        let (equal, el_method, pack) = match r.route {
            // NV12 pictures are piecewise only
            plan::ROUTE_DUAL if !r.nv12 => ((r.el_flag == 0) as u32, bilinear as u32, resized_pack),
            plan::ROUTE_SINGLE if !r.nv12 => (0, 0, resized_pack),
            plan::ROUTE_PIECEWISE if !(full && r.resized) => (0, 0, if full { plan::PACK_422 } else { resized_pack }),
            _ => return None,
        };
        if contract && pack != plan::PACK_SITED {
            return None;
        }
        Some(PackRoute { route: r.route, equal, el_method, pack, chroma_filter: contract as u32 })
    }

    /// Engine::pack_overlay for these inputs.
    fn overlay_kind(r: &Routing) -> u32 {
        let (srgb, shell) = (r.shell == 1, r.shell != 0);
        let cb1 = !r.overlay_prepare
            && r.sources_used
            && contract(r)
            && r.overlay
            && r.white_203
            && !r.subs
            && srgb
            && r.cb1_coeff;
        let fused = r.overlay && r.sources_used && shell && !r.subs && !r.overlay_prepare;
        if cb1 {
            3
        } else if !r.overlay {
            0
        } else if fused {
            2
        } else {
            1
        }
    }

    fn variant(i: usize) -> (u32, u32, u32) {
        let i = i as u32;
        (i / (PACK_OVERLAYS * PACK_KINDS), i / PACK_KINDS % PACK_OVERLAYS, i % PACK_KINDS)
    }

    #[test]
    fn reachable_variants() {
        // every routing input: the variants select_pack picks are exactly
        // pack_reachable's, and all three Annex B ones (a prepared source's)
        let n = (PACK_SOURCES * PACK_OVERLAYS * PACK_KINDS) as usize;
        let (mut regular, mut annexb) = (vec![false; n], [false; ANNEXB_OVERLAYS.len()]);
        for r in routings() {
            let Some(route) = planned(&r) else { continue };
            match select_pack(&route, overlay_kind(&r)).1 {
                PackVariant::Regular(i) => regular[i] = true,
                PackVariant::Annexb(i) => annexb[i] = true,
            }
        }
        assert!(annexb.iter().all(|&a| a));
        let mut reached = Vec::new();
        for (i, &hit) in regular.iter().enumerate() {
            let (source, overlay, kind) = variant(i);
            assert_eq!(
                hit,
                pack_reachable(source, overlay, kind),
                "variant {i}: source {source} overlay {overlay} kind {kind}"
            );
            if hit {
                reached.push((source, overlay, kind));
            }
        }
        // (source, overlay, kind): 0 staged, 1 fused single layer, 2 fused FEL;
        // 0 none, 1 prepared, 2 fused shell, 3 native CB1; sited, 4:2:2, resized
        assert_eq!(
            reached,
            [
                (0, 0, 0),
                (0, 0, 1),
                (0, 0, 2),
                (0, 1, 0),
                (0, 1, 1),
                (0, 1, 2),
                (0, 2, 0),
                (0, 2, 1),
                (0, 2, 2),
                (0, 3, 0),
                (1, 0, 0),
                (1, 1, 0),
                (1, 2, 0),
                (2, 0, 0),
                (2, 0, 2),
                (2, 1, 0),
                (2, 1, 2),
                (2, 2, 0),
                (2, 2, 2),
            ]
        );
    }

    #[test]
    fn eager_variants_and_count() {
        use crate::options::EngineOptions;
        let n = |o: &EngineOptions| {
            (0..PACK_SOURCES * PACK_OVERLAYS * PACK_KINDS)
                .filter(|&i| {
                    let (s, v, k) = variant(i as usize);
                    pack_eager(o, s, v, k)
                })
                .count() as u32
        };
        let shipped = EngineOptions::default();
        assert_eq!(n(&shipped), 19);
        assert_eq!(pipeline_count(&shipped), 19 + 3 + OTHER_PIPELINES);
        let verify = EngineOptions { verify_every: 4, ..EngineOptions::default() };
        assert_eq!(n(&verify), 19);
        assert_eq!(pipeline_count(&verify), 19 + 3 + OTHER_PIPELINES + 1);
        let lazy = EngineOptions { lazy_resized_pack: true, ..EngineOptions::default() };
        assert_eq!(n(&lazy), 16);
        // dvvk-prepare: each of the 19 + 3 variants again for HDR10 and for HDR10+
        let prepare = EngineOptions { prepare_map: true, ..EngineOptions::default() };
        assert_eq!(n(&prepare), 19);
        assert_eq!(pipeline_count(&prepare), 19 + 3 + OTHER_PIPELINES + 2 * (19 + 3));
        // DVVK_VERIFY's reference packs (source 0, the frame's kind) are made
        for r in routings() {
            let Some(route) = planned(&r) else { continue };
            let o = overlay_kind(&r);
            for reference in [o.min(1), 2, 3].into_iter().filter(|&v| v != 3 || o == 3) {
                assert!(pack_eager(&verify, 0, reference, route.pack), "{r:?}");
            }
        }
    }

    #[test]
    fn planner_routes_are_modelled() {
        // plan.c itself, over the fixtures and the inputs the engine varies:
        // every plan's pack fields are ones `planned` gives for its route
        let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/yblod/fixtures");
        let modelled: Vec<_> = routings()
            .iter()
            .filter_map(planned)
            .map(|p| (p.route, p.equal, p.el_method, p.pack, p.chroma_filter))
            .collect();
        let mut plan = Plan::boxed();
        let mut seen = 0;
        for (name, has_el) in [("1917-fel.0", true), ("gemini-mel.0", false), ("28yl-p81.0", false)] {
            let md = std::fs::read(format!("{dir}/{name}.bin")).unwrap();
            for bits in 0u32..1 << 7 {
                let b = |i: u32| bits >> i & 1 != 0;
                let (resized, desktop) = (b(3), b(4));
                let mut input = plan::PlanIn {
                    width: 3840,
                    height: 2160,
                    x: 0,
                    y: 0,
                    dw: 0,
                    dh: 0,
                    chroma_top_left: 1,
                    has_el: has_el as u32,
                    nv12: b(0) as u32,
                    el_scaler: if b(1) { plan::EL_ANNEXB } else { plan::EL_BILINEAR },
                    fel: b(2) as u32,
                    packet_id: 0,
                    refresh: 0,
                    overlay: b(5) as u32,
                    overlay_visible_before: 0,
                    pts: 0,
                    rgb_to_lms: [0.0; 9],
                    white_nits: 203.0,
                    cb1_contract: (b(6) && !resized && !desktop) as u32,
                    dm_options: 0,
                };
                if resized {
                    (input.x, input.y, input.dw, input.dh) = (960, 540, 1920, 1080);
                }
                let d = desktop.then(|| plan::PlanDesktop::on(None));
                let mut st = plan::PlanState::new().unwrap();
                if plan.fill(&input, d.as_ref(), &mut st, &md) != 0 {
                    continue;
                }
                seen += 1;
                let r = PackRoute::of(&plan);
                assert!(
                    modelled.contains(&(r.route, r.equal, r.el_method, r.pack, r.chroma_filter)),
                    "{name} {input:?}: {r:?}"
                );
            }
        }
        assert!(seen > 0);
    }

    #[test]
    fn partitions() {
        assert_eq!(partition(None, 4), vec![([0, 0], [30, 540])]);
        assert_eq!(partition(None, 16), vec![([0, 0], [30, 135])]);
        assert_eq!(
            partition(Some(&[[128, 6, 384, 21], [0, 2156, 3840, 2160]]), 16),
            vec![([1, 0], [2, 2]), ([0, 134], [30, 1])]
        );
        assert!(partition(Some(&[]), 4).is_empty());
    }
}

/// Whether select_pack can pick the regular variant (source, overlay, kind)
/// for a plan yblod/plan.c makes and an overlay the engine picks
/// (pack_tests::reachable_variants proves it over the planner's routing
/// inputs). 19 of the 36: native CB1 (3) is CB1's contract, which is unscaled
/// (sited), Annex B (so never the fused FEL) and takes the Annex B variants
/// from source 1; the fused single layer (1) is unscaled single-route
/// pictures, sited (4:2:2 is the piecewise route's); the fused FEL (2) is the
/// dual route with the bilinear EL, never 4:2:2.
fn pack_reachable(source: u32, overlay: u32, kind: u32) -> bool {
    if overlay == 3 {
        // native CB1: staged CB1 frames (no Annex B variant)
        return source == 0 && kind == plan::PACK_SITED;
    }
    match source {
        0 => true,
        1 => kind == plan::PACK_SITED,
        _ => kind != plan::PACK_422,
    }
}

/// DVVK_LAZY_RESIZED_PACK: the fused-FEL resized variants are made on first use.
fn pack_lazy(o: &crate::options::EngineOptions, source: u32, kind: u32) -> bool {
    o.lazy_resized_pack && source == 2 && kind == plan::PACK_RESIZED
}

/// Whether Engine::new makes the regular variant: the reachable ones (they
/// include DVVK_VERIFY's reference for native CB1 frames: staged, sited,
/// overlay 3), but not the lazy ones. Any other is made on first use (ensure_pack).
fn pack_eager(o: &crate::options::EngineOptions, source: u32, overlay: u32, kind: u32) -> bool {
    pack_reachable(source, overlay, kind) && !pack_lazy(o, source, kind)
}

/// The pack variants a frame of HDR10 or HDR10+ output can take: the
/// reachable regular ones and the Annex B ones, as select_pack names them.
fn map_variants() -> Vec<PackVariant> {
    let mut v = Vec::new();
    for source in 0..PACK_SOURCES {
        for overlay in 0..PACK_OVERLAYS {
            for kind in 0..PACK_KINDS {
                if pack_reachable(source, overlay, kind) {
                    v.push(PackVariant::Regular(((source * PACK_OVERLAYS + overlay) * PACK_KINDS + kind) as usize));
                }
            }
        }
    }
    v.extend((0..ANNEXB_OVERLAYS.len()).map(PackVariant::Annexb));
    v
}

/// The pack's spec constants for a variant (as Engine::new makes them).
fn pack_spec(o: &crate::options::EngineOptions, variant: PackVariant) -> Vec<(u32, u32)> {
    let (fma, blend_fma) = (o.resize_fma, o.blend_fma);
    match variant {
        PackVariant::Regular(i) => {
            let i = i as u32;
            let (source, overlay, kind) =
                (i / (PACK_OVERLAYS * PACK_KINDS), (i / PACK_KINDS) % PACK_OVERLAYS, i % PACK_KINDS);
            vec![(0, kind), (1, fma), (2, overlay), (3, blend_fma), (4, source), (6, 2)]
        }
        PackVariant::Annexb(k) => vec![
            (0, 0),
            (1, fma),
            (2, ANNEXB_OVERLAYS[k]),
            (3, blend_fma),
            (4, 1),
            (5, 1),
            (6, 8),
            (7, o.cb1_pair_reuse as u32),
        ],
    }
}

/// The HDR10 pack's MAP (pack.comp): 1 LUT + map_fixup, or a diagnostic.
fn map_spec(o: &crate::options::EngineOptions) -> u32 {
    if o.map_direct {
        2
    } else if o.map_lut_only {
        3
    } else if o.map_inline {
        4
    } else {
        1
    }
}

/// A variant's constants with MAP (HDR10 output) and STATS (HDR10+). One
/// place for the prepare run and a frame's first use: the pipeline cache
/// only answers for the same constants in the same order.
fn pack_map_spec(o: &crate::options::EngineOptions, variant: PackVariant, stats: bool) -> Vec<(u32, u32)> {
    let mut spec = pack_spec(o, variant);
    spec.push((8, map_spec(o)));
    spec.push((9, stats as u32));
    spec
}

/// How many pipelines Engine::new creates (DVVK_PREPARE progress).
fn pipeline_count(o: &crate::options::EngineOptions) -> u32 {
    let mut packs = 0;
    for source in 0..PACK_SOURCES {
        for overlay in 0..PACK_OVERLAYS {
            for kind in 0..PACK_KINDS {
                packs += u32::from(pack_eager(o, source, overlay, kind));
            }
        }
    }
    // DVVK_PREPARE_MAP: each HDR10 variant without and with the statistics
    let mapped = if o.prepare_map { 2 * map_variants().len() as u32 } else { 0 };
    packs + ANNEXB_OVERLAYS.len() as u32 + OTHER_PIPELINES + u32::from(o.verify_every > 0) + mapped
}

// Offsets in the tables buffer (256-aligned).
const T_MAPPING: u64 = 0;
const T_RESIDUAL: u64 = 2048;
const T_PARAMS: u64 = 14336;
const T_CHROMA_MAPPING: u64 = 15360;
const T_LUT: u64 = 19456;
const T_SINGLE: u64 = 68608;
const T_LUMA: u64 = 74752;
const T_RESHAPE: u64 = 76800;
const T_END: u64 = 81408;

// FEL intermediates, as opencl_backend.c's V, VP, BP(+1), G, ES(+1).
const F_V: usize = 0;
const F_VP: usize = 1;
const F_BP: usize = 2;
const F_G: usize = 3;
const F_ES: usize = 4;

fn bytes_of<T>(v: &[T]) -> &[u8] {
    unsafe { std::slice::from_raw_parts(v.as_ptr() as *const u8, std::mem::size_of_val(v)) }
}

/// A frame's semaphore waits: the decoded BL and EL, the shell's overlay.
#[derive(Default)]
struct Waits {
    s: [vk::Semaphore; 3],
    n: usize,
}

impl Waits {
    fn push(&mut self, s: vk::Semaphore) {
        self.s[self.n] = s;
        self.n += 1;
    }
    fn len(&self) -> usize {
        self.n
    }
    fn as_slice(&self) -> &[vk::Semaphore] {
        &self.s[..self.n]
    }
}

/// Opt-in CPU/GPU deadline diagnostics for one submitted frame.
#[derive(Default)]
struct Deadline {
    begin_ns: u64,
    submit_ns: u64,
    return_ns: u64,
    ring_ms: f64,
    prepare_ms: f64,
    queue_call_ms: f64,
    export_ms: f64,
    import_ms: f64,
    decode_waits: usize,
    overlay_waits: usize,
    release_ready: bool,
    pts: i64,
    slot: u32,
    overlay: bool,
    empty: bool,
}
fn monotonic_ns() -> u64 {
    let mut t: libc::timespec = unsafe { std::mem::zeroed() };
    unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut t) };
    t.tv_sec as u64 * 1_000_000_000 + t.tv_nsec as u64
}
/// A frame's own buffers, as the record functions bind them.
#[derive(Clone, Copy)]
struct Slot {
    tables: vk::Buffer,
    packets: vk::Buffer,
    error: vk::Buffer,
    gui_coeff: vk::Buffer,
    gui_error: vk::Buffer,
    map_params: vk::Buffer,
    stats: vk::Buffer,
}

/// One frame in flight, including buffers that cannot be reused before completion.
struct Ctx {
    pool: vk::CommandPool,
    cmd: vk::CommandBuffer,
    tables: HostBuffer,
    packets: HostBuffer,
    error: HostBuffer,
    gui_coeff: HostBuffer,
    gui_error: HostBuffer,
    map_params: HostBuffer, // the output mapping's dvvk_map_gpu (HDR10 output)
    // HDR10+ output: the pack's statistics of this frame's film (pack.comp
    // STATS: hist[256], max[3], sum lo, hi, count), and what its metadata is
    // made from (the frame's AVDOVIMetadata, 8-aligned; the overlay flag).
    stats: HostBuffer,
    hdr10plus: Option<Hdr10PlusFrame>,
    bounds_result: HostBuffer,
    bounds_generation: Option<u64>,
    // The plan's tables_generation in `tables` (None: unknown): the same one
    // needs no upload.
    tables_generation: Option<u32>,
    decode: [vk::Semaphore; 3], // the decoder's write fences (BL, EL), the shell overlay's
    done: vk::Semaphore,        // exported as the output's implicit fence
    ticket: u64,                // the timeline value its submit signals; 0 = never used
    // DVVK_PROFILE=1: GPU timestamps (start, reconstruction, overlay prepare,
    // pack), read back when the context is reused.
    query: Option<vk::QueryPool>,
    deadline: Option<Deadline>,
    plan_ms: f64,
    prepared: bool,
    fel_stamped: bool, // the staged FEL chain wrote points 4-6
    // DVVK_VERIFY: the compare's result (differing pixels, the first) when this frame was checked.
    verify: Option<HostBuffer>,
    verified: bool,
}

/// An HDR10+ output frame's inputs to its dynamic metadata (dvvk_hdr10plus_packet).
struct Hdr10PlusFrame {
    metadata: Vec<u64>, // the AVDOVIMetadata bytes, 8-aligned
    size: usize,
    overlay: bool,
    area: [u32; 4], // the film's active area in the canvas (x0, y0, x1, y1), as STATS measures it
}

/// The statistics record's words (pack.comp STATS).
pub const STATS_WORDS: usize = 262;

/// DVVK_VERIFY=k: every k-th frame is rendered a second time by the
/// reference route (the staged reconstruction, overlay_prepare's colour cache
/// made afresh, in place: fresh entries are what any cache must hold) into
/// `out`, and the shown output compared with it word by word. For the fused routes (FEL, the shell's overlay): any difference is a bug.
struct Verify {
    every: u64,
    frames: u64,
    err: DeviceBuffer,
    out: Option<(DeviceBuffer, u32)>, // and its stride
    compare: Pipeline,
    checked: u64,
    differing: u64,
}

const PROFILE_POINTS: u32 = 4;
// More points for the staged FEL chain: after vertical_pair, luma_phase_guide
// and phase_vertical_uv (the chroma pass ends at point 1).
const PROFILE_FEL_POINTS: u32 = 11;
const PROFILE_TOTAL_POINTS: u32 = 11; // 7: reconstruction entry, 8: overlay entry, 9: bounds end, 10: FEL dispatch
const PROFILE_WINDOW: usize = 120;
// cb1_tiles.comp: CB1's overlay occupancy per 32x32 tile.
const CB1_TILE: u32 = 32;
const CB1_TILES: (u32, u32) = (CANVAS_W.div_ceil(CB1_TILE), CANVAS_H.div_ceil(CB1_TILE));

/// Per-stage GPU time over a window of frames (DVVK_PROFILE=1).
#[derive(Default)]
struct Profile {
    stages: Vec<[f64; 4]>, // reconstruction, prepare, pack (GPU ms), plan (CPU ms)
    prepared: u32,
    fel: Vec<[f64; 4]>, // staged FEL: vertical_pair, luma_phase_guide, phase_vertical_uv, chroma
}

impl Ctx {
    fn slot(&self) -> Slot {
        Slot {
            tables: self.tables.buffer,
            packets: self.packets.buffer,
            error: self.error.buffer,
            gui_coeff: self.gui_coeff.buffer,
            gui_error: self.gui_error.buffer,
            map_params: self.map_params.buffer,
            stats: self.stats.buffer,
        }
    }
}

impl Profile {
    fn add(&mut self, stages: [f64; 4], prepared: bool, fel: Option<[f64; 4]>) {
        self.stages.push(stages);
        self.prepared += prepared as u32;
        if let Some(f) = fel {
            self.fel.push(f);
        }
        if self.stages.len() < PROFILE_WINDOW {
            return;
        }
        if !self.fel.is_empty() {
            let n = self.fel.len() as f64;
            let mean = |i: usize| self.fel.iter().map(|s| s[i]).sum::<f64>() / n;
            eprintln!("dvvk profile: staged FEL ({} frames): vertical_pair {:.2} + luma_phase_guide {:.2} + phase_vertical_uv {:.2} + chroma {:.2} ms",
                      self.fel.len(), mean(0), mean(1), mean(2), mean(3));
            self.fel.clear();
        }
        let n = self.stages.len() as f64;
        let mean = |i: usize| self.stages.iter().map(|s| s[i]).sum::<f64>() / n;
        let mut total: Vec<f64> = self.stages.iter().map(|s| s[0] + s[1] + s[2]).collect();
        total.sort_by(|a, b| a.partial_cmp(b).unwrap());
        eprintln!(
            "dvvk profile: gpu {:.2} ms (p95 {:.2}, max {:.2}) = reconstruction {:.2} + overlay prepare {:.2} ({} of {} frames) + pack {:.2}; plan {:.2} ms CPU",
            mean(0) + mean(1) + mean(2), total[(total.len() * 95) / 100], total[total.len() - 1],
            mean(0), mean(1), self.prepared, self.stages.len(), mean(2), mean(3));
        self.stages.clear();
        self.prepared = 0;
    }
}

pub const RING: usize = 4;

/// DVVK_TRACE's per-frame record (the values traced, as recorded).
type Trace = (u32, u32, u32, [u32; 2], u32, u32, u32, u32);

pub struct Engine {
    /// AMD: the COMPUTE power profile while frames come (power.rs).
    boost: Option<crate::power::Boost>,
    pub d: Device,
    ring: Vec<Ctx>,
    next: usize,
    timeline: vk::Semaphore,
    release: Option<vk::Semaphore>, // the compositor's release timeline (explicit sync)
    ticket: u64,
    pub decode_fence_waits: u64,
    pub decode_vasync_waits: u64,
    va: va::VADisplay,
    push: PushDescriptor,
    sampler: vk::Sampler,
    single: Pipeline,
    fel: FelPipelines,
    fel_buffers: [DeviceBuffer; 5],
    pack: Vec<Option<Pipeline>>, // [(source * 4 + overlay) * 3 + PACK]
    pack_fma: (u32, u32),        // captured at creation, also used by deferred variants
    pack_annexb: Vec<Pipeline>,  // [source * 3 + overlay (none, native, prepared)]: 32x8 chroma tile
    fel_chroma: Pipeline,
    overlay: HostBuffer,
    gui_colours: DeviceBuffer,
    gui_retired: Vec<DeviceBuffer>,
    gui_tiles: DeviceBuffer,
    gui_keys: DeviceBuffer,
    keys_valid: bool,
    cb1_luts: [gpu::SampledImage; 2],
    cb1: Option<[f32; 32]>,
    cb1_tiles: DeviceBuffer, // occupied count (16 bytes), then a word per tile
    cb1_tiles_pipe: Pipeline,
    cb1_tiles_valid: bool, // every tile is of the shell scanned last
    // What of the shell changed since the last scan (pixel x0, y0, x1, y1;
    // None: everything), and the damage the next set_shell came with.
    cb1_dirty: Option<Vec<[u32; 4]>>,
    shell_damage: Option<Vec<[u32; 4]>>,
    shell_generation: u64,
    shell_empty: bool,
    overlay_prepare: [Pipeline; 2], // from the test RGBA buffer, from the sources
    linear: vk::Sampler,
    pub sources: Sources,
    sources_used: bool, // the overlay comes from `sources`, not set_overlay_rgba
    prev_overlay: bool,
    // The prepared overlay is current for this picture and these colour coefficients.
    overlay_dirty: bool,
    overlay_coeff: [f32; 32],
    resize_prepare: Pipeline,
    planes: [DeviceBuffer; 3],
    ymap: DeviceBuffer,
    surfaces: HashMap<u32, va::SurfaceImport>,
    outputs: Vec<Option<Output>>,
    shot: OneShot,
    resize_key: Option<[u32; 5]>,
    plan: Box<Plan>,
    // CB1's packet ids and the last tables per route (yblod/plan.c), reset
    // with the engine
    plan_state: plan::PlanState,
    pub last_error_flags: u32,
    /// The last planned frame's dvvk_plan.dm_status (CM4 / L2 options).
    pub dm_status: u32,
    last_plan_ms: f64,
    overlay_error_flag: u32,
    overlay_prepared_by: Option<usize>,
    // The overlay's colour cache was last kept by the pack (the shell alone),
    // not overlay_prepare: switching invalidates it.
    overlay_fused: bool,
    pub implicit_failed: bool,
    submission_failed: bool, // record/submit failure: recreate engine before retry
    trace: Option<Trace>,
    profile: Option<Profile>,
    deadline_trace: bool,
    verify: Option<Verify>,
    // The query pool record_fel stamps into (this frame's, not the reference's).
    fel_query: std::cell::Cell<Option<vk::QueryPool>>,
    // DVVK_VERIFY's reference pass is recording: the original staged kernels.
    reference_pass: std::cell::Cell<bool>,
    // what each output buffer has to be written again (damage.rs), and the
    // overlay buffer last given
    damage: crate::damage::Damage,
    last_shell: Option<u64>,
    // HDR10 output (docs/hdr10-output.md): the mode, the last frame's
    // mapping, the scene's 3D LUT (its nodes, then the image the pack samples)
    // and its exactly-computed cells, the key it was baked for, and the pack
    // variants with MAP (made on first use: (Annex B, index)).
    map_mode: crate::map::OutputMode,
    map: Option<Box<crate::map::Map>>,
    map_lut: gpu::Lut3d,
    map_nodes: DeviceBuffer,
    map_cells: DeviceBuffer,
    map_baked: Option<u64>,
    map_bake: [Pipeline; 3],
    map_fixup: Pipeline,
    /// map_cells' fix-up list (words: groups, 1, 1, count, the entries)
    map_list: u32,
    pack_map: HashMap<(bool, usize, bool), Pipeline>,
    pub map_bakes: u64,
    map_frames: u64,
}

impl Engine {
    pub fn new(drm_fd: i32, va_display: va::VADisplay) -> Result<Self> {
        if !plan::layout_matches() {
            return Err(Error::Unsupported("plan.h and plan.rs disagree".into()));
        }
        let options = crate::options::EngineOptions::from_env();
        let d = Device::new(drm_fd, options)?;
        let o = d.options.clone();
        gpu::prepare_begin(o.prepare_progress, pipeline_count(&o));
        let mut construction = crate::construction::Construction::new(&d);
        let storage = vk::DescriptorType::STORAGE_BUFFER;
        let sampled = vk::DescriptorType::COMBINED_IMAGE_SAMPLER;
        // source_tunnel.cl has no FP_CONTRACT pragma, so OpenCL's default (ON)
        // applies and IGC fuses the resize lerps: fused (1) matches it byte for
        // byte; DVVK_RESIZE_FMA=0 is the uncontracted variant, for comparison.
        let fma = o.resize_fma;
        let single = construction.keep(Pipeline::new(
            &d,
            "single_polynomial",
            &[sampled, sampled, storage, storage, storage, storage, storage],
            12,
            &[],
        )?);
        let blend_fma = o.blend_fma;
        let mut pack_bindings = vec![storage; 9];
        pack_bindings.extend([sampled, sampled, sampled, storage, storage, storage]);
        pack_bindings.extend([sampled, storage, storage]); // the fused overlay: shell, keys, coefficients
        pack_bindings.extend([sampled, sampled, storage]); // CB1 LUTs and GPU bounds
        pack_bindings.extend([sampled, storage, storage]); // HDR10 output: the 3D LUT, its parameters and exact cells
        pack_bindings.push(storage); // HDR10+ output: the frame's statistics
        let pack_push = std::mem::size_of::<PackPush>() as u32;
        // The variants a frame can use (pack_eager; the rest stay None).
        let mut pack = Vec::with_capacity((PACK_SOURCES * PACK_OVERLAYS * PACK_KINDS) as usize);
        for source in 0..PACK_SOURCES {
            for overlay in 0..PACK_OVERLAYS {
                for kind in 0..PACK_KINDS {
                    crate::fault::check("construct-pack")?;
                    pack.push(if !pack_eager(&o, source, overlay, kind) {
                        None
                    } else {
                        Some(construction.keep(Pipeline::new(
                            &d,
                            "pack",
                            &pack_bindings,
                            pack_push,
                            &[(0, kind), (1, fma), (2, overlay), (3, blend_fma), (4, source), (6, 2)],
                        )?))
                    });
                }
            }
        }
        // CB1 contract: the sited pack of a fused single-layer source (1),
        // with no overlay, native CB1, or prepared subtitle colours. Staged
        // sources (0) take the regular sited pack. The prepared path retains
        // its own blending and colour conversion.
        let pair_reuse = o.cb1_pair_reuse;
        let mut pack_annexb = Vec::new();
        for source in [1u32] {
            for overlay in ANNEXB_OVERLAYS {
                pack_annexb.push(construction.keep(Pipeline::new(
                    &d,
                    "pack",
                    &pack_bindings,
                    pack_push,
                    &[
                        (0, 0),
                        (1, fma),
                        (2, overlay),
                        (3, blend_fma),
                        (4, source),
                        (5, 1),
                        (6, 8),
                        (7, pair_reuse as u32),
                    ],
                )?));
            }
        }
        let fel_chroma = construction.keep(Pipeline::new(
            &d,
            "fel_chroma",
            &[sampled, sampled, sampled, storage, storage, storage, storage, storage, storage, storage, storage],
            32,
            &[],
        )?);
        let fel = FelPipelines {
            vertical_pair: construction.keep(Pipeline::new(
                &d,
                "fel_vertical_pair",
                &[sampled, storage, storage],
                20,
                &[],
            )?),
            vertical_pair_w32: construction.keep(Pipeline::new(
                &d,
                "fel_vertical_pair_w32",
                &[sampled, storage, storage],
                20,
                &[],
            )?),
            luma_phase_guide: construction.keep(Pipeline::new(
                &d,
                "fel_luma_phase_guide",
                &[sampled, sampled, storage, storage, storage, storage, storage, storage, storage],
                20,
                &[],
            )?),
            phase_vertical_uv: construction.keep(Pipeline::new(
                &d,
                "fel_phase_vertical_uv",
                &[sampled, storage, storage, storage],
                20,
                &[],
            )?),
            mmr_dual_horizontal: construction.keep(Pipeline::new(
                &d,
                "fel_mmr_dual_horizontal",
                &[storage; 12],
                16,
                &[],
            )?),
            scale_horizontal: construction.keep(Pipeline::new(&d, "fel_scale_horizontal", &[storage; 3], 16, &[])?),
            table_add: construction.keep(Pipeline::new(&d, "table_add", &[storage; 6], 12, &[])?),
            mmr_dual: construction.keep(Pipeline::new(&d, "fel_mmr_dual_horizontal", &[storage; 12], 16, &[(0, 0)])?),
            mmr_single: [
                construction.keep(Pipeline::new(&d, "fel_mmr_single", &[storage; 8], 12, &[(0, 0)])?),
                construction.keep(Pipeline::new(&d, "fel_mmr_single", &[storage; 8], 12, &[(0, 1)])?),
                construction.keep(Pipeline::new(&d, "fel_mmr_single", &[storage; 8], 12, &[(0, 2)])?),
            ],
            equal: [
                construction.keep(Pipeline::new(
                    &d,
                    "fel_equal",
                    &[sampled, sampled, storage, storage, storage, storage, storage, storage],
                    20,
                    &[(0, 0)],
                )?),
                construction.keep(Pipeline::new(
                    &d,
                    "fel_equal",
                    &[sampled, sampled, storage, storage, storage, storage, storage, storage],
                    20,
                    &[(0, 1)],
                )?),
                construction.keep(Pipeline::new(
                    &d,
                    "fel_equal",
                    &[sampled, sampled, storage, storage, storage, storage, storage, storage],
                    20,
                    &[(0, 2)],
                )?),
            ],
            piecewise: [
                construction.keep(Pipeline::new(
                    &d,
                    "piecewise",
                    &[sampled, sampled, storage, storage, storage, storage, storage, storage],
                    32,
                    &[(0, 1), (1, 10), (2, 0), (3, 1)],
                )?),
                construction.keep(Pipeline::new(
                    &d,
                    "piecewise",
                    &[sampled, sampled, storage, storage, storage, storage, storage, storage],
                    32,
                    &[(0, 1), (1, 10), (2, 1), (3, 1)],
                )?),
                construction.keep(Pipeline::new(
                    &d,
                    "piecewise",
                    &[sampled, sampled, storage, storage, storage, storage, storage, storage],
                    32,
                    &[(0, 0), (1, 8), (2, 0), (3, 1)],
                )?),
                construction.keep(Pipeline::new(
                    &d,
                    "piecewise",
                    &[sampled, sampled, storage, storage, storage, storage, storage, storage],
                    32,
                    &[(0, 0), (1, 10), (2, 0), (3, 1)],
                )?),
            ],
        };
        if crate::fault::hit("construct-pipelines") {
            return Err(Error::Vk(vk::Result::ERROR_UNKNOWN));
        }
        let quarter = (MAX_W / 2 * MAX_H / 2 * 2) as u64;
        let fel_buffers = [
            construction.keep(DeviceBuffer::new(&d, (MAX_W / 2 * MAX_H * 2) as u64)?),
            construction.keep(DeviceBuffer::new(&d, quarter / 2)?),
            construction.keep(DeviceBuffer::new(&d, 2 * quarter)?),
            construction.keep(DeviceBuffer::new(&d, quarter)?),
            construction.keep(DeviceBuffer::new(&d, 2 * quarter)?),
        ];
        let overlay = construction.keep(HostBuffer::new(
            &d,
            (CANVAS_W * CANVAS_H * 4) as u64,
            vk::BufferUsageFlags::STORAGE_BUFFER,
        )?);
        // Allocated in full on the first frame that needs them (submit).
        let gui_colours = construction.keep(DeviceBuffer::new(&d, 16)?);
        let gui_tiles =
            construction.keep(DeviceBuffer::new(&d, (CANVAS_W.div_ceil(16) * CANVAS_H.div_ceil(16) * 4) as u64)?);
        let prepare_bindings =
            [storage, storage, storage, storage, sampled, storage, storage, storage, storage, storage];
        let overlay_prepare = [
            construction.keep(Pipeline::new(&d, "overlay_prepare", &prepare_bindings, 40, &[(0, 0)])?),
            construction.keep(Pipeline::new(&d, "overlay_prepare", &prepare_bindings, 40, &[(0, 1)])?),
        ];
        let gui_keys = construction.keep(DeviceBuffer::new(&d, 16)?);
        let linear = {
            let info = vk::SamplerCreateInfo::default()
                .mag_filter(vk::Filter::LINEAR)
                .min_filter(vk::Filter::LINEAR)
                .address_mode_u(vk::SamplerAddressMode::CLAMP_TO_EDGE)
                .address_mode_v(vk::SamplerAddressMode::CLAMP_TO_EDGE);
            construction.keep(unsafe { d.device.create_sampler(&info, None) }?)
        };
        let sources = Sources::new(&d)?;
        for buffer in &sources.atlas {
            construction.watch(buffer);
        }
        let resize_prepare = construction.keep(Pipeline::new(
            &d,
            "resize_prepare",
            &[storage],
            std::mem::size_of::<ResizePush>() as u32,
            &[],
        )?);
        let luma_bytes = (MAX_W * MAX_H * 2) as u64;
        let planes = [
            construction.keep(DeviceBuffer::new(&d, luma_bytes)?),
            construction.keep(DeviceBuffer::new(&d, luma_bytes / 2)?),
            construction.keep(DeviceBuffer::new(&d, luma_bytes / 2)?),
        ];
        let ymap = construction.keep(DeviceBuffer::new(&d, 2 * 4096 * 16)?);
        let sampler = construction.keep(gpu::nearest_sampler(&d)?);
        let push = PushDescriptor::new(&d);
        let shot = construction.keep(OneShot::new(&d)?);
        let cb1_luts = [
            construction.keep(gpu::SampledImage::new(&d, vk::Format::R16_SFLOAT, 256, 1)?),
            construction.keep(gpu::SampledImage::new(&d, vk::Format::R16_SFLOAT, 256, 1)?),
        ];
        let mut cb1_tables = [[0f32; 256]; 2];
        unsafe { dvvk_cb1_luts(cb1_tables[0].as_mut_ptr(), cb1_tables[1].as_mut_ptr()) };
        construction.may_submit();
        for (lut, values) in cb1_luts.iter().zip(cb1_tables.iter()) {
            let halves: Vec<u8> = values.iter().flat_map(|&v| gpu::half_rne(v).to_le_bytes()).collect();
            lut.upload(&d, &shot, &halves, 256, 1)?;
        }
        if crate::fault::hit("construct-uploaded") {
            return Err(Error::Vk(vk::Result::ERROR_UNKNOWN));
        }
        let cb1_tiles = construction.keep(DeviceBuffer::new(&d, 16 + 4 * (CB1_TILES.0 * CB1_TILES.1) as u64)?);
        let cb1_tiles_pipe = construction.keep(Pipeline::new(&d, "cb1_tiles", &[sampled, storage], 32, &[])?);
        let deadline_trace = o.deadline_trace && d.timestamp_period > 0.0;
        let profile = o.profile && d.timestamp_period > 0.0;
        let verify_every = o.verify_every;
        let verify = if verify_every > 0 {
            Some(Verify {
                every: verify_every,
                frames: 0,
                err: construction.keep(DeviceBuffer::new(&d, 16)?),
                out: None,
                compare: construction.keep(Pipeline::new(&d, "verify_compare", &[storage, storage, storage], 12, &[])?),
                checked: 0,
                differing: 0,
            })
        } else {
            None
        };
        let map_bake = [
            construction.keep(Pipeline::new(&d, "map_bake", &[storage, storage, storage], 8, &[(0, 0)])?),
            construction.keep(Pipeline::new(&d, "map_bake", &[storage, storage, storage], 8, &[(0, 1)])?),
            construction.keep(Pipeline::new(&d, "map_bake", &[storage, storage, storage], 8, &[(0, 2)])?),
        ];
        let n = o.map_n;
        let map_lut = construction.keep(gpu::Lut3d::new(&d, n)?);
        let map_nodes = construction.keep(DeviceBuffer::new(&d, (n * n * n) as u64 * 8)?);
        let map_fixup = construction.keep(Pipeline::new(&d, "map_fixup", &[storage, storage, storage], 8, &[])?);
        // the marked cells' bits, then (256-aligned) map_fixup's list: its
        // header and an entry per pack invocation at most
        let map_list = ((n - 1).pow(3).div_ceil(32) * 4).next_multiple_of(256) / 4;
        let entries = (CANVAS_W / 4) * CANVAS_H.div_ceil(2);
        let map_cells = construction.keep(DeviceBuffer::new(&d, u64::from(map_list + 4 + entries) * 4)?);
        // dvvk-prepare (DVVK_PREPARE_MAP=1): the HDR10 and HDR10+ pack variants
        // as well, so the pipeline cache holds them and a frame's first use
        // (ensure_pack_map) is a lookup instead of a compile on the render
        // thread. A playing engine leaves them to first use: they would only
        // delay its start.
        let mut pack_map = HashMap::new();
        if o.prepare_map {
            // The Dolby Vision set is complete: kept if this run is cut short.
            d.save_pipeline_cache();
            for stats in [false, true] {
                for variant in map_variants() {
                    let spec = pack_map_spec(&o, variant, stats);
                    let pipe = construction.keep(Pipeline::new(&d, "pack", &pack_bindings, pack_push, &spec)?);
                    pack_map.insert(Self::pack_map_key(variant, stats), pipe);
                }
            }
        }
        gpu::prepare_end()?;
        d.save_pipeline_cache();
        let mut ring = Vec::new();
        for _ in 0..RING {
            let pool = unsafe {
                d.device.create_command_pool(
                    &vk::CommandPoolCreateInfo::default()
                        .queue_family_index(d.queue_family)
                        .flags(vk::CommandPoolCreateFlags::RESET_COMMAND_BUFFER),
                    None,
                )
            }?;
            construction.watch(&pool);
            crate::fault::check("construct-ring-pool")?;
            let cmd = unsafe {
                d.device.allocate_command_buffers(
                    &vk::CommandBufferAllocateInfo::default().command_pool(pool).command_buffer_count(1),
                )
            }?[0];
            let sem = |d: &Device| -> Result<vk::Semaphore> { crate::interop::sync::exportable_semaphore(d) };
            ring.push(Ctx {
                pool,
                cmd,
                tables: construction.keep(HostBuffer::new(
                    &d,
                    T_END.next_multiple_of(4096),
                    vk::BufferUsageFlags::STORAGE_BUFFER,
                )?),
                packets: construction.keep(HostBuffer::new(&d, 640, vk::BufferUsageFlags::STORAGE_BUFFER)?),
                error: construction.keep(HostBuffer::new(&d, 16, vk::BufferUsageFlags::STORAGE_BUFFER)?),
                gui_coeff: construction.keep(HostBuffer::new(&d, 128, vk::BufferUsageFlags::STORAGE_BUFFER)?),
                gui_error: construction.keep(HostBuffer::new(&d, 16, vk::BufferUsageFlags::STORAGE_BUFFER)?),
                map_params: construction.keep(HostBuffer::new(&d, 2048, vk::BufferUsageFlags::STORAGE_BUFFER)?),
                stats: construction.keep(HostBuffer::new(
                    &d,
                    (STATS_WORDS * 4).next_multiple_of(256) as u64,
                    vk::BufferUsageFlags::STORAGE_BUFFER,
                )?),
                hdr10plus: None,
                bounds_result: construction.keep(HostBuffer::new(
                    &d,
                    32,
                    vk::BufferUsageFlags::STORAGE_BUFFER | vk::BufferUsageFlags::TRANSFER_DST,
                )?),
                bounds_generation: None,
                tables_generation: None,
                decode: [construction.keep(sem(&d)?), construction.keep(sem(&d)?), construction.keep(sem(&d)?)],
                done: construction.keep(sem(&d)?),
                ticket: 0,
                deadline: None,
                query: if profile || deadline_trace {
                    let info = vk::QueryPoolCreateInfo::default()
                        .query_type(vk::QueryType::TIMESTAMP)
                        .query_count(PROFILE_TOTAL_POINTS);
                    Some(construction.keep(unsafe { d.device.create_query_pool(&info, None) }?))
                } else {
                    None
                },
                plan_ms: 0.0,
                prepared: false,
                fel_stamped: false,
                verify: if verify_every > 0 {
                    Some(construction.keep(HostBuffer::new(&d, 16, vk::BufferUsageFlags::STORAGE_BUFFER)?))
                } else {
                    None
                },
                verified: false,
            });
            crate::fault::check("construct-ring-ready")?;
        }
        let mut type_info =
            vk::SemaphoreTypeCreateInfo::default().semaphore_type(vk::SemaphoreType::TIMELINE).initial_value(0);
        let mut export =
            vk::ExportSemaphoreCreateInfo::default().handle_types(vk::ExternalSemaphoreHandleTypeFlags::OPAQUE_FD);
        let timeline = unsafe {
            d.device.create_semaphore(
                &vk::SemaphoreCreateInfo::default().push_next(&mut type_info).push_next(&mut export),
                None,
            )
        }?;
        construction.watch(&timeline);
        if crate::fault::hit("construct-final") {
            return Err(Error::Vk(vk::Result::ERROR_UNKNOWN));
        }
        // Before the commit: a failure after it would roll nothing back.
        let plan_state = plan::PlanState::new().ok_or(Error::Missing("memory for the plan state"))?;
        construction.commit();
        Ok(Engine {
            ring,
            next: 0,
            timeline,
            release: None,
            ticket: 0,
            decode_fence_waits: 0,
            decode_vasync_waits: 0,
            push,
            sampler,
            single,
            fel,
            fel_buffers,
            pack,
            pack_fma: (fma, blend_fma),
            pack_annexb,
            fel_chroma,
            overlay,
            gui_colours,
            gui_retired: Vec::new(),
            gui_tiles,
            gui_keys,
            keys_valid: false,
            cb1_luts,
            cb1: None,
            cb1_tiles,
            cb1_tiles_pipe,
            cb1_tiles_valid: false,
            cb1_dirty: None,
            shell_damage: None,
            shell_generation: 0,
            shell_empty: false,
            overlay_prepare,
            linear,
            sources,
            sources_used: false,
            prev_overlay: false,
            overlay_dirty: true,
            overlay_coeff: [0.0; 32],
            resize_prepare,
            planes,
            ymap,
            surfaces: HashMap::new(),
            outputs: Vec::new(),
            shot,
            resize_key: None,
            plan: Plan::boxed(),
            plan_state,
            last_error_flags: 0,
            dm_status: 0,
            last_plan_ms: 0.0,
            overlay_error_flag: 0,
            overlay_prepared_by: None,
            overlay_fused: false,
            implicit_failed: false,
            submission_failed: false,
            trace: None,
            profile: profile.then(Profile::default),
            deadline_trace,
            verify,
            fel_query: std::cell::Cell::new(None),
            reference_pass: std::cell::Cell::new(false),
            damage: crate::damage::Damage::new((CANVAS_W, CANVAS_H), o.damage),
            last_shell: None,
            map_mode: crate::map::OutputMode {
                mode: o.output_mode,
                ..Default::default()
            },
            map: None,
            map_lut,
            map_nodes,
            map_cells,
            map_baked: None,
            map_bake,
            map_fixup,
            map_list,
            pack_map,
            map_bakes: 0,
            map_frames: 0,
            va: va_display,
            boost: crate::power::Boost::new(drm_fd, o.gpu_boost),
            d,
        })
    }

    /// A linear XRGB8888 3840x2160 dmabuf as output `slot`.
    pub fn set_output(&mut self, slot: u32, fd: i32, stride: u32) -> Result<()> {
        if stride < CANVAS_W * 4 || !stride.is_multiple_of(16) {
            return Err(Error::Unsupported("output stride".into()));
        }
        // Acquire the retained fence fd before replacing a working output.
        // Failure must not silently install fd=-1 or discard the old buffer.
        let retained_fd = unsafe { libc::fcntl(fd, libc::F_DUPFD_CLOEXEC, 0) };
        if retained_fd < 0 {
            return Err(Error::Unsupported("dup of output dmabuf failed".into()));
        }
        let buffer = match dmabuf::import_buffer(&self.d, fd, stride as u64 * CANVAS_H as u64) {
            Ok(buffer) => buffer,
            Err(e) => {
                unsafe {
                    libc::close(retained_fd);
                }
                return Err(e);
            }
        };
        let slot = slot as usize;
        if self.outputs.len() <= slot {
            self.outputs.resize_with(slot + 1, || None);
        }
        if let Err(e) = self.idle_checked() {
            buffer.destroy(&self.d);
            unsafe {
                libc::close(retained_fd);
            }
            return Err(e);
        }
        if let Some(old) = self.outputs[slot].take() {
            old.buffer.destroy(&self.d);
            unsafe { libc::close(old.fd) };
        }
        self.outputs[slot] = Some(Output { buffer, stride, fd: retained_fd });
        self.damage.invalidate(slot);
        Ok(())
    }

    /// The overlay picture (RGBA8 premultiplied sRGB, 3840x2160, rows top
    /// first) used by frames with `overlay` set. Phase 1: copied in.
    pub fn set_overlay_rgba(&mut self, rgba: &[u8], stride: usize) {
        let dst = self.overlay.bytes_mut();
        let row = (CANVAS_W * 4) as usize;
        for y in 0..CANVAS_H as usize {
            dst[y * row..(y + 1) * row].copy_from_slice(&rgba[y * stride..y * stride + row]);
        }
        self.overlay_dirty = true;
        self.damage.changed(None);
    }

    /// mpv's subtitles / OSD bitmaps for the following frames (none: empty).
    pub fn set_subtitles(&mut self, parts: &[overlay::SubPart]) -> Result<()> {
        self.sources_used = true;
        let timeline = self.timeline;
        let d = &self.d;
        let wait = |t: u64| {
            if crate::fault::hit("atlas-wait") {
                return Err(Error::Vk(vk::Result::TIMEOUT));
            }
            if t > 0 {
                let sems = [timeline];
                let values = [t];
                unsafe {
                    d.device.wait_semaphores(
                        &vk::SemaphoreWaitInfo::default().semaphores(&sems).values(&values),
                        2_000_000_000,
                    )
                }?;
            }
            Ok(())
        };
        let old = self.sources.subs_bbox;
        let r = self.sources.set_subtitles(d, parts, (CANVAS_W, CANVAS_H), wait);
        let new = self.sources.subs_bbox;
        match (old, new) {
            (None, None) => {}
            (Some(a), None) | (None, Some(a)) => self.damage.changed(Some(a)),
            (Some(a), Some(b)) => {
                self.damage.changed(Some([a[0].min(b[0]), a[1].min(b[1]), a[2].max(b[2]), a[3].max(b[3])]))
            }
        }
        r
    }

    /// The next set_shell's buffer differs from the previous one only in these
    /// rectangles (x, y, w, h; none: the same picture). Without it a new buffer
    /// counts as changed everywhere.
    pub fn set_shell_damage(&mut self, rects: &[[u32; 4]]) {
        self.damage.set_pending(rects);
        self.shell_damage =
            Some(rects.iter().map(|r| [r[0], r[1], r[0].saturating_add(r[2]), r[1].saturating_add(r[3])]).collect());
    }

    /// The shell's OSD buffer (KWin's forwarded dmabuf, or Kodi's GUI
    /// framebuffer, rows bottom first with `flip`) for the following frames,
    /// or none. `id` names it for overlay_ticket. Each frame that reads it
    /// leaves its fence on the buffer as a read fence, so a writer that
    /// honours implicit sync can draw the next contents into the same buffer.
    pub fn set_shell(&mut self, buf: Option<&overlay::Dmabuf>, id: u64, flip: bool) -> Result<()> {
        let ticket = self.ticket;
        let timeline = self.timeline;
        let d = &self.d;
        let idle = || {
            #[cfg(feature = "test-faults")]
            eprintln!(
                "dvvk test eviction: ticket={ticket} pending={}",
                unsafe { d.device.get_semaphore_counter_value(timeline) }.map(|v| v < ticket).unwrap_or(false)
            );
            if crate::fault::hit("retire-wait") {
                return Err(Error::Vk(vk::Result::TIMEOUT));
            }
            if ticket > 0 {
                let sems = [timeline];
                let values = [ticket];
                unsafe {
                    d.device.wait_semaphores(
                        &vk::SemaphoreWaitInfo::default().semaphores(&sems).values(&values),
                        2_000_000_000,
                    )
                }?;
            }
            Ok(())
        };
        self.sources.set_shell(d, buf, id, flip, idle)?;
        // A flipped buffer's damage would be in its own rows (bottom first):
        // it counts as changed everywhere.
        if flip {
            self.shell_damage = None;
            self.damage.clear_pending();
        }
        // CB1's tiles to scan again: the damage given for this buffer, or all
        // (also once the tiles are stale anyway, or the list grows long).
        match (buf.is_some() && self.cb1_tiles_valid, self.shell_damage.take(), self.cb1_dirty.as_mut()) {
            (true, Some(rects), Some(dirty)) if dirty.len() + rects.len() <= 64 => dirty.extend(rects),
            _ => self.cb1_dirty = None,
        }
        // Even a reused allocation/id can contain a newly visible OSD.
        self.shell_generation = self.shell_generation.wrapping_add(1);
        self.shell_empty = false;
        self.sources_used = true;

        let new = buf.map(|_| id);
        if new != self.last_shell || flip {
            self.damage.changed(None);
        }
        self.last_shell = new;
        Ok(())
    }

    /// The ticket of the frame that read overlay `id` (0: not read yet; the
    /// caller may give the buffer back once that ticket is done).
    pub fn overlay_ticket(&mut self, id: u64) -> u64 {
        self.sources.consumed.remove(&id).unwrap_or(0)
    }

    /// After a panic inside a call: the engine's state may be half-updated, so
    /// it only drains and is destroyed from now on (as after a failed submit).
    pub fn poison(&mut self) {
        self.submission_failed = true;
    }

    /// Forget imported surfaces (new decoder pool: seek, new file).
    pub fn reset(&mut self) {
        let _ = self.reset_checked(2_000_000_000);
    }

    /// Includes the last successful queue submission even if export failed and
    /// the caller received no ticket. Failure is never a completion certificate.
    pub fn drain(&mut self, timeout_ns: u64) -> Result<bool> {
        let result = if crate::fault::hit("retire-wait") {
            Err(Error::Vk(vk::Result::TIMEOUT))
        } else if self.ticket == 0 {
            Ok(true)
        } else {
            self.wait(self.ticket, timeout_ns)
        };
        if !matches!(result, Ok(true)) {
            self.submission_failed = true;
        }
        result
    }

    pub fn reset_checked(&mut self, timeout_ns: u64) -> Result<bool> {
        // Reset is never recovery from a failed submit or retirement.
        if self.submission_failed {
            return Err(Error::Unsupported("recreate poisoned engine".into()));
        }
        if !self.drain(timeout_ns)? {
            return Ok(false);
        }
        self.cb1_tiles_valid = false;
        self.plan_state.reset();
        // Generations start again: no context's tables are known any more.
        for c in &mut self.ring {
            c.tables_generation = None;
        }
        for (_, s) in self.surfaces.drain() {
            s.destroy(&self.d);
        }
        self.resize_key = None;
        Ok(true)
    }

    /// The surface's planes, imported once and then trusted by id (no VA
    /// export per frame) until reset(): the caller resets when the decoder's
    /// surface pool changes, since a new pool can reuse ids for other
    /// allocations. A different size is a miss; so is a reused id whose
    /// export differs (the cached import stands only for the same dmabuf).
    fn surface(&mut self, id: u32, w: u32, h: u32) -> Result<()> {
        let replace = crate::fault::hit("decode-replace");
        // DVVK_SURFACE_CHECK=1: export it every frame and keep the import only
        // for the same dmabuf (for callers that don't reset on a new pool).
        if !replace && !self.d.options.surface_check && self.surfaces.get(&id).is_some_and(|s| s.key.size() == (w, h)) {
            return Ok(());
        }
        let exported = va::ExportedSurface::new(self.va, id, w, h)?;
        if !replace && self.surfaces.get(&id).is_some_and(|s| s.key == exported.key) {
            return Ok(());
        }
        let replacement = match exported.import(&self.d, w, h) {
            Ok(s) => s,
            Err(e) => {
                #[cfg(feature = "test-faults")]
                eprintln!("dvvk test decoded rollback: cached={}", self.surfaces.contains_key(&id));
                return Err(e);
            }
        };
        if self.surfaces.contains_key(&id) {
            if let Err(e) = self.idle_checked() {
                replacement.destroy(&self.d);
                return Err(e);
            }
        }
        if let Some(old) = self.surfaces.insert(id, replacement) {
            old.destroy(&self.d);
        }

        Ok(())
    }

    /// linux-drm-syncobj-v1: the frames' timeline (acquire points: the
    /// tickets) and a new release timeline the compositor signals, both as
    /// DRM syncobj fds for wp_linux_drm_syncobj_manager_v1.import_timeline.
    pub fn timelines(&mut self) -> Result<(i32, i32)> {
        let get = |s: vk::Semaphore| -> Result<i32> {
            let info = vk::SemaphoreGetFdInfoKHR::default()
                .semaphore(s)
                .handle_type(vk::ExternalSemaphoreHandleTypeFlags::OPAQUE_FD);
            Ok(unsafe { self.d.semaphore_fd.get_semaphore_fd(&info) }?)
        };
        if self.release.is_none() {
            let mut type_info =
                vk::SemaphoreTypeCreateInfo::default().semaphore_type(vk::SemaphoreType::TIMELINE).initial_value(0);
            let mut export =
                vk::ExportSemaphoreCreateInfo::default().handle_types(vk::ExternalSemaphoreHandleTypeFlags::OPAQUE_FD);
            let sem = unsafe {
                self.d.device.create_semaphore(
                    &vk::SemaphoreCreateInfo::default().push_next(&mut type_info).push_next(&mut export),
                    None,
                )
            }?;
            self.release = Some(sem);
        }
        let acquire = get(self.timeline)?;
        let release = match get(self.release.unwrap()) {
            Ok(fd) => fd,
            Err(e) => {
                unsafe { libc::close(acquire) };
                return Err(e);
            }
        };
        Ok((acquire, release))
    }

    /// Wait until the GPU has finished everything submitted.
    pub fn idle(&self) -> Result<()> {
        self.idle_checked()
    }

    fn idle_checked(&self) -> Result<()> {
        if crate::fault::hit("retire-wait") {
            return Err(Error::Vk(vk::Result::TIMEOUT));
        }
        if self.ticket > 0 && !self.wait(self.ticket, 2_000_000_000)? {
            return Err(Error::Unsupported("GPU retirement wait timed out".into()));
        }
        Ok(())
    }

    fn wait_complete(&self, ticket: u64) -> Result<()> {
        if !self.wait(ticket, 2_000_000_000)? {
            return Err(Error::Unsupported("GPU completion wait timed out".into()));
        }
        Ok(())
    }

    /// Blocks until frame `ticket` is done (or `timeout_ns`). Ok(true) if done.
    pub fn wait(&self, ticket: u64, timeout_ns: u64) -> Result<bool> {
        let sems = [self.timeline];
        let values = [ticket];
        match unsafe {
            self.d
                .device
                .wait_semaphores(&vk::SemaphoreWaitInfo::default().semaphores(&sems).values(&values), timeout_ns)
        } {
            Ok(()) => Ok(true),
            Err(vk::Result::TIMEOUT) => Ok(false),
            Err(e) => Err(e.into()),
        }
    }

    /// Whether frame `ticket` is done, and its error flags (range 1, overflow
    /// 2, overlay colour << 8) if its context hasn't been reused yet. Never blocks.
    pub fn poll(&self, ticket: u64) -> Result<(bool, u32)> {
        let done = unsafe { self.d.device.get_semaphore_counter_value(self.timeline) }? >= ticket;
        let ctx = &self.ring[((ticket.max(1) - 1) % RING as u64) as usize];
        let flags = if done && ctx.ticket == ticket {
            u32::from_le_bytes(ctx.error.bytes()[..4].try_into().unwrap())
                | (u32::from_le_bytes(ctx.gui_error.bytes()[..4].try_into().unwrap()) << 8)
        } else {
            0
        };
        Ok((done, flags))
    }

    /// The decoder's write fence on a surface, as a semaphore the frame waits
    /// for (no CPU wait); vaSyncSurface if the kernel can't export it.
    fn decode_wait(&mut self, ctx: usize, k: usize, id: u32) -> Result<Option<vk::Semaphore>> {
        let fd = self.surfaces[&id].fd;
        {
            if let Ok(sync_file) = crate::interop::sync::export_sync_file(fd, crate::interop::sync::DMA_BUF_SYNC_READ) {
                if crate::interop::sync::signalled(sync_file) {
                    unsafe { libc::close(sync_file) };
                    return Ok(None);
                }
                let sem = self.ring[ctx].decode[k];
                match crate::interop::sync::semaphore_from_sync_file(&self.d, sem, sync_file) {
                    Ok(()) => {
                        self.decode_fence_waits += 1;
                        return Ok(Some(sem));
                    }
                    Err(_) => unsafe {
                        libc::close(sync_file);
                    },
                }
            }
        }
        self.decode_vasync_waits += 1;
        if unsafe { va::vaSyncSurface(self.va, id) } != 0 {
            return Err(Error::Unsupported("decoder surface synchronization failed".into()));
        }
        Ok(None)
    }

    /// Plans, records and runs one frame synchronously (the comparison
    /// harness). Ok(0) or Ok(dv_status != 0: not this engine's frame).
    pub fn render(&mut self, f: &FrameIn) -> Result<i32> {
        let (status, ticket) = self.submit(f)?;
        if status != 0 {
            return Ok(status);
        }
        self.wait_complete(ticket)?;
        self.last_error_flags = self.poll(ticket)?.1;
        Ok(0)
    }

    /// Whether this frame's overlay is the shell's layer alone, read and kept
    /// by the pack itself (no overlay_prepare pass; DVVK_OVERLAY_PREPARE=1
    /// keeps the pass). Every such frame reads the shell.
    fn cb1_overlay(&self) -> bool {
        self.cb1.is_some()
    }

    fn fused_overlay(&self) -> bool {
        !self.cb1_overlay()
            && self.plan.overlay_visible != 0
            && self.sources_used
            && self.sources.shell().is_some()
            && self.sources.subs_parts == 0
            && !self.d.options.overlay_prepare
    }

    fn pack_source(&self) -> u32 {
        pack_source(&PackRoute::of(&self.plan))
    }

    fn pack_overlay(&self) -> u32 {
        if self.cb1_overlay() {
            3
        } else if self.plan.overlay_visible == 0 {
            0
        } else if self.fused_overlay() {
            2
        } else {
            1
        }
    }

    /// The frame's regular pack variant, made now if the engine didn't make it
    /// (DVVK_LAZY_RESIZED_PACK's, or one pack_reachable says can't be picked).
    /// No command recording, semaphore import, or frame-cache commit before this
    /// succeeds. A failed creation leaves the slot empty and may be retried.
    fn ensure_pack(&mut self) -> Result<()> {
        let overlay = self.pack_overlay();
        let (source, index) = match select_pack(&PackRoute::of(&self.plan), overlay) {
            (source, PackVariant::Regular(index)) => (source, index),
            _ => return Ok(()),
        };
        if self.pack[index].is_some() {
            return Ok(());
        }
        let kind = index as u32 % PACK_KINDS;
        let start = std::time::Instant::now();
        // All regular pack layouts are identical. Slot zero is always eager.
        let Some(first) = self.pack[0].as_ref() else { return Err(Error::Missing("the first pack variant")) };
        let bindings = &first.bindings;
        let result = Pipeline::new_deferred(
            &self.d,
            "pack",
            bindings,
            std::mem::size_of::<PackPush>() as u32,
            &[(0, kind), (1, self.pack_fma.0), (2, overlay), (3, self.pack_fma.1), (4, source), (6, 2)],
        );
        // Always expose the synchronous first-use cost, including failure.
        eprintln!(
            "dvvk deferred pack: index={index} success={} creation_ms={:.4}",
            result.is_ok(),
            start.elapsed().as_secs_f64() * 1000.0
        );
        self.pack[index] = Some(result?);
        self.d.save_pipeline_cache();
        Ok(())
    }

    fn pack_map_key(variant: PackVariant, stats: bool) -> (bool, usize, bool) {
        match variant {
            PackVariant::Annexb(k) => (true, k, stats),
            PackVariant::Regular(i) => (false, i, stats),
        }
    }

    /// HDR10+ output: the pack measures the film (pack.comp STATS).
    fn stats(&self) -> bool {
        self.map.as_ref().is_some_and(|m| m.signal.mode == crate::map::DVVK_OUTPUT_HDR10PLUS)
    }

    /// HDR10 output: the frame's pack variant with MAP, made on first use
    /// (from the pipeline cache when dvvk-prepare or an earlier engine made
    /// it; the cache keeps it for the next engine).
    fn ensure_pack_map(&mut self) -> Result<()> {
        if self.map.is_none() {
            return Ok(());
        }
        let variant = select_pack(&PackRoute::of(&self.plan), self.pack_overlay()).1;
        let key = Self::pack_map_key(variant, self.stats());
        if self.pack_map.contains_key(&key) {
            return Ok(());
        }
        let start = std::time::Instant::now();
        let Some(first) = self.pack[0].as_ref() else { return Err(Error::Missing("the first pack variant")) };
        let bindings = first.bindings.clone();
        let spec = pack_map_spec(&self.d.options, variant, key.2);
        let pipe = Pipeline::new_deferred(&self.d, "pack", &bindings, std::mem::size_of::<PackPush>() as u32, &spec)?;
        eprintln!("dvvk HDR10 pack: {variant:?} creation_ms={:.1}", start.elapsed().as_secs_f64() * 1000.0);
        self.pack_map.insert(key, pipe);
        self.d.save_pipeline_cache();
        Ok(())
    }

    /// dvvk_set_output_mode: from the next frame.
    pub fn set_output_mode(&mut self, mode: &crate::map::OutputMode) -> Result<()> {
        if mode.mode > crate::map::DVVK_OUTPUT_HDR10PLUS {
            return Err(Error::Unsupported(format!("output mode {}", mode.mode)));
        }
        if mode.flags != 0 || mode.peak_nits != 0.0 || mode.min_nits != 0.0 {
            return Err(Error::Unsupported("output mode options".into()));
        }
        if *mode != self.map_mode {
            self.map_mode = *mode;
            self.map = None;
            self.map_baked = None;
        }
        Ok(())
    }

    /// dvvk_output_signal: the last frame's.
    pub fn output_signal(&self) -> crate::map::HdrSignal {
        self.map.as_ref().map(|m| m.signal).unwrap_or_default()
    }

    /// dvvk_hdr10plus_packet: HDR10+ frame `ticket`'s dynamic metadata, from
    /// its own statistics when it is done, else the latest finished HDR10+
    /// frame's before it. Never blocks. Ok(status) as the C API returns it.
    pub fn hdr10plus_packet(&self, ticket: u64, flags: u32, out: &mut crate::hdr10plus::Packet) -> Result<i32> {
        if ticket == 0 || flags & !3 != 0 {
            return Ok(-1);
        }
        let ctx = &self.ring[((ticket - 1) % RING as u64) as usize];
        let Some(frame) = ctx.hdr10plus.as_ref().filter(|_| ctx.ticket == ticket) else { return Ok(-1) };
        let done = unsafe { self.d.device.get_semaphore_counter_value(self.timeline) }?;
        let Some(source) = self
            .ring
            .iter()
            .filter(|c| c.hdr10plus.is_some() && c.ticket != 0 && c.ticket <= ticket && c.ticket <= done)
            .max_by_key(|c| c.ticket)
        else {
            return Ok(1);
        };
        let mut words = [0u32; STATS_WORDS];
        for (i, w) in source.stats.bytes()[..STATS_WORDS * 4].as_chunks::<4>().0.iter().enumerate() {
            words[i] = u32::from_le_bytes(*w);
        }
        let bytes = unsafe { std::slice::from_raw_parts(frame.metadata.as_ptr() as *const u8, frame.size) };
        let status = crate::hdr10plus::packet(bytes, &words, flags, frame.overlay, out);
        out.statistics_ticket = source.ticket;
        if self.d.options.hdr10plus_trace {
            // the statistics record as measured (the CPU reference compares the histogram)
            let hist: Vec<String> = words[..256].iter().map(|w| w.to_string()).collect();
            eprintln!(
                "{{\"dvvk_hdr10plus_stats\":{},\"ticket\":{},\"area\":[{},{},{},{}],\"max_pq_bits\":[{},{},{}],\"sum64\":{},\"count\":{},\"histogram\":[{}]}}",
                source.ticket,
                ticket,
                source.hdr10plus.as_ref().unwrap().area[0],
                source.hdr10plus.as_ref().unwrap().area[1],
                source.hdr10plus.as_ref().unwrap().area[2],
                source.hdr10plus.as_ref().unwrap().area[3],
                words[256],
                words[257],
                words[258],
                (u64::from(words[260]) << 32) | u64::from(words[259]),
                words[261],
                hist.join(",")
            );
        }
        Ok(status)
    }

    /// The finished frame of context `ci`: its check and its timestamps.
    fn collect_frame(&mut self, ci: usize) {
        // This context already completed: read its snapshot of the occupied
        // tile count without adding a wait or racing a later frame's scan.
        if self.ring[ci].bounds_generation.take() == Some(self.shell_generation) {
            let b = self.ring[ci].bounds_result.bytes();
            self.shell_empty = u32::from_le_bytes([b[0], b[1], b[2], b[3]]) == 0;
            if self.shell_empty && self.d.options.trace {
                eprintln!("dvvk: transparent overlay generation {} bypassed", self.shell_generation);
            }
        }
        if let (Some(v), true) = (self.verify.as_mut(), self.ring[ci].verified) {
            let c = &self.ring[ci];
            let r = c.verify.as_ref().unwrap().bytes();
            let differing = u32::from_le_bytes(r[0..4].try_into().unwrap());
            let first = u32::from_le_bytes(r[4..8].try_into().unwrap());
            v.checked += 1;
            if differing > 0 {
                v.differing += 1;
                eprintln!(
                    "dvvk verify: frame {} differs from the reference in {} pixels (first at {},{})",
                    c.ticket,
                    differing,
                    first % CANVAS_W,
                    first / CANVAS_W
                );
            }
            if v.checked % 120 == 0 {
                eprintln!("dvvk verify: {} frames checked, {} differed", v.checked, v.differing);
            }
        }
        self.collect_deadline(ci);
        self.collect_profile(ci);
    }

    fn collect_deadline(&self, ci: usize) {
        let c = &self.ring[ci];
        let (Some(t), Some(q)) = (&c.deadline, c.query) else { return };
        let mut ts = [0u64; PROFILE_TOTAL_POINTS as usize];
        if unsafe { self.d.device.get_query_pool_results(q, 0, &mut ts[..4], vk::QueryResultFlags::TYPE_64) }.is_err() {
            return;
        }
        // MEL does not write FEL-only queries 4..7 or 10.
        if unsafe { self.d.device.get_query_pool_results(q, 7, &mut ts[7..10], vk::QueryResultFlags::TYPE_64) }.is_err()
        {
            return;
        }
        let period = self.d.timestamp_period as f64;
        let gpu_ms = (ts[3].wrapping_sub(ts[0])) as f64 * period / 1e6;
        let ms = |a: usize, b: usize| ts[b].wrapping_sub(ts[a]) as f64 * period / 1e6;
        eprintln!("dvvk gates: {{\"ticket\":{},\"pre_reconstruct_gate_ms\":{:.4},\"reconstruct_ms\":{:.4},\"overlay_gate_ms\":{:.4},\"overlay_work_ms\":{:.4},\"pack_ms\":{:.4}}}",
            c.ticket, ms(0,7), ms(7,1), ms(1,8), ms(8,2), ms(2,3));
        let bounds_end = [ts[9]];
        let mut fel_ms = String::from("null");
        let mut fel_pre_ms = String::from("null");
        if c.fel_stamped {
            let mut f = [0u64; 7];
            if unsafe { self.d.device.get_query_pool_results(q, 4, &mut f, vk::QueryResultFlags::TYPE_64) }.is_ok() {
                let ms = |a: u64, b: u64| b.wrapping_sub(a) as f64 * period / 1e6;
                fel_pre_ms = format!("{:.4}", ms(ts[0], f[6]));
                fel_ms = format!(
                    "[{:.4},{:.4},{:.4},{:.4}]",
                    ms(f[6], f[0]),
                    ms(f[0], f[1]),
                    ms(f[1], f[2]),
                    ms(f[2], ts[1])
                );
            }
        }
        let mut queue_ms = String::from("null");
        let mut deviation_ns = String::from("null");
        if let Some(cal) = &self.d.calibration {
            let domains = [
                vk::CalibratedTimestampInfoEXT::default().time_domain(vk::TimeDomainEXT::DEVICE),
                vk::CalibratedTimestampInfoEXT::default().time_domain(vk::TimeDomainEXT::CLOCK_MONOTONIC),
            ];
            if let Ok((v, dev)) = unsafe { cal.get_calibrated_timestamps(&domains) } {
                let start_ns = v[1] as f64 + (ts[0] as i128 - v[0] as i128) as f64 * period;
                queue_ms = format!("{:.4}", (start_ns - t.submit_ns as f64) / 1e6);
                deviation_ns = dev.to_string();
            }
        }
        eprintln!("dvvk deadline: {{\"ticket\":{},\"pts\":{},\"slot\":{},\"begin_ns\":{},\"submit_ns\":{},\"ring_ms\":{:.4},\"prepare_ms\":{:.4},\"cpu_ms\":{:.4},\"queue_ms\":{},\"gpu_ms\":{:.4},\"pack_ms\":{:.4},\"reconstruction_ms\":{:.4},\"bounds_ms\":{:.4},\"overlay_prepare_ms\":{:.4},\"fel_ms\":{},\"fel_pre_ms\":{},\"calibration_deviation_ns\":{},\"queue_call_ms\":{:.4},\"export_ms\":{:.4},\"import_ms\":{:.4},\"decode_waits\":{},\"overlay_waits\":{},\"release_ready\":{},\"overlay\":{},\"empty\":{}}}",
            c.ticket,t.pts,t.slot,t.begin_ns,t.submit_ns,t.ring_ms,t.prepare_ms,(t.return_ns-t.begin_ns) as f64/1e6,
            queue_ms,gpu_ms,ts[3].wrapping_sub(ts[2]) as f64*period/1e6,
            ts[1].wrapping_sub(ts[0]) as f64*period/1e6, bounds_end[0].wrapping_sub(ts[1]) as f64*period/1e6,
            ts[2].wrapping_sub(bounds_end[0]) as f64*period/1e6, fel_ms, fel_pre_ms, deviation_ns,
            t.queue_call_ms,t.export_ms,t.import_ms,t.decode_waits,t.overlay_waits,t.release_ready,t.overlay,t.empty);
    }

    /// The finished frame of context `ci`: its timestamps into the profile.
    fn collect_profile(&mut self, ci: usize) {
        let (Some(profile), Some(q)) = (self.profile.as_mut(), self.ring[ci].query) else { return };
        let c = &self.ring[ci];
        let mut ts = [0u64; PROFILE_FEL_POINTS as usize];
        let n = if c.fel_stamped { PROFILE_FEL_POINTS } else { PROFILE_POINTS } as usize;
        let ok =
            unsafe { self.d.device.get_query_pool_results(q, 0, &mut ts[..n], vk::QueryResultFlags::TYPE_64) }.is_ok();
        if !ok {
            return;
        }
        let period = self.d.timestamp_period as f64 / 1e6;
        let ms = |a: usize, b: usize| ts[b].wrapping_sub(ts[a]) as f64 * period;
        let fel = c.fel_stamped.then(|| [ms(10, 4), ms(4, 5), ms(5, 6), ms(6, 1)]);
        profile.add([ms(0, 1), ms(1, 2), ms(2, 3), c.plan_ms], c.prepared, fel);
    }

    /// Plans and submits one frame into output `f.output`; returns at once.
    /// (status, ticket): status 0 and the ticket `poll`/`wait` take, or a
    /// dv_status (not this engine's frame: show an ordinary picture). The
    /// output dmabuf carries the frame's fence as an implicit write fence, so
    /// it can be committed to the compositor right away.
    pub fn submit(&mut self, f: &FrameIn) -> Result<(i32, u64)> {
        if self.submission_failed {
            return Err(Error::Unsupported("recreate engine after failed GPU submission".into()));
        }
        let trace_begin = if self.deadline_trace { monotonic_ns() } else { 0 };
        let ci = self.next;
        let mut ring_ms = 0.0;
        if self.ring[ci].ticket > 0 {
            self.wait_complete(self.ring[ci].ticket)?; // back-pressure: RING frames in flight
            if self.deadline_trace {
                ring_ms = (monotonic_ns() - trace_begin) as f64 / 1e6;
            }
            self.collect_frame(ci);
        }
        self.ring[ci].deadline = self.deadline_trace.then(|| Deadline {
            begin_ns: trace_begin,
            ring_ms,
            pts: f.plan.pts,
            slot: f.output,
            ..Deadline::default()
        });
        let mut plan_in = f.plan;
        // A picture shown below 3/4 of its size (a preview box): the base layer
        // only (the FEL-off route; its residual can't be seen that small, and its
        // reconstruction is most of a FEL frame's cost).
        if plan_in.dw != 0
            && plan_in.dh != 0
            && 4 * plan_in.dw < 3 * plan_in.width
            && 4 * plan_in.dh < 3 * plan_in.height
        {
            plan_in.fel = 0;
        }
        // CB1's Master Reference contract covers unscaled pictures only (the
        // planner refuses a resized one): a film in a box, or the desktop's
        // frames, are rendered yblod's way.
        let resized =
            plan_in.dw != 0 && plan_in.dh != 0 && (plan_in.dw != plan_in.width || plan_in.dh != plan_in.height);
        if resized || f.desktop {
            plan_in.cb1_contract = 0;
        }
        if f.auto_overlay {
            plan_in.overlay =
                (self.sources.subs_parts > 0 || (self.sources.shell().is_some() && !self.shell_empty)) as u32;
            plan_in.overlay_visible_before = self.prev_overlay as u32;
        }
        let plan_start = std::time::Instant::now();
        let desktop = f.desktop.then(|| crate::plan::PlanDesktop::on(self.d.options.desktop_l1));
        let status = self.plan.fill(&plan_in, desktop.as_ref(), &mut self.plan_state, f.metadata);
        self.last_plan_ms = plan_start.elapsed().as_secs_f64() * 1e3;
        if status != 0 {
            return Ok((status, 0));
        }
        self.dm_status = self.plan.dm_status;
        // HDR10 output: the frame's mapping (a stream it can't map is refused,
        // as the tunnel refuses one: the caller shows an ordinary picture).
        // Desktop frames (the film in a box) stay the tunnel's business.
        self.map = None;
        if self.map_mode.mode != crate::map::DVVK_OUTPUT_DV {
            match crate::map::Map::plan(&self.map_mode, f.metadata) {
                Ok(mut m) => {
                    m.set_black([self.plan.black[0], self.plan.black[1], self.plan.black[2]]);
                    m.set_lut_n(self.map_lut.n);
                    m.set_list(self.map_list);
                    self.map = Some(m);
                }
                Err(status) => return Ok((status, 0)),
            }
            self.map_frames += 1;
            if self.d.options.map_stats && self.map_frames % 120 == 0 {
                eprintln!("dvvk map: {} LUT bakes in {} frames", self.map_bakes, self.map_frames);
            }
        }
        // Native CB1 GUI path: keep desktop/linear FP16, resized pictures and
        // combined subtitle sources on their existing paths. DVVK_OVERLAY_PREPARE
        // also retains the prepared blend.
        self.cb1 = None;
        let native = !self.d.options.overlay_prepare;
        if native
            && self.sources_used
            && plan_in.cb1_contract != 0
            && plan_in.overlay != 0
            && plan_in.white_nits == 203.0
            && self.sources.subs_parts == 0
            && self.sources.shell().map(|sh| !sh.linear && !sh.scaled).unwrap_or(false)
        {
            let mut coeff = [0f32; 32];
            if unsafe { dvvk_cb1_coeff(f.metadata.as_ptr(), plan_in.nv12, coeff.as_mut_ptr()) } == 0 {
                coeff[26] = if self.plan.black[0] == 0 { 0.0 } else { 0.0625 };
                self.cb1 = Some(coeff);
            }
        }
        self.ensure_pack()?;
        self.ensure_pack_map()?;
        if !self.cb1_overlay() {
            self.cb1_tiles_valid = false;
        }
        if !self.cb1_overlay() && self.plan.overlay_visible != 0 {
            // Retain the tiny placeholders until engine teardown: earlier native
            // commands may still reference their descriptors, even though unused.
            // No GPU drain on the first subtitle or legacy overlay.
            for (buffer, bytes) in [
                (&mut self.gui_colours, (CANVAS_W * CANVAS_H * 16) as u64),
                (&mut self.gui_keys, (CANVAS_W * CANVAS_H * 4) as u64),
            ] {
                if buffer.size < bytes {
                    let full = DeviceBuffer::new(&self.d, bytes)?;
                    self.gui_retired.push(std::mem::replace(buffer, full));
                }
            }
        }
        if let Some(b) = &self.boost {
            b.frame();
        }
        let p = &*self.plan;
        if self.d.options.trace {
            let key = (p.route, p.equal, p.dual, p.chroma_kind, p.layout, p.order2, p.depth, p.pack);
            if self.trace != Some(key) {
                eprintln!(
                    "dvvk: route {} equal {} dual {} chroma {:?} layout {} order2 {} depth {} pack {}",
                    key.0, key.1, key.2, key.3, key.4, key.5, key.6, key.7
                );
                self.trace = Some(key);
            }
        }
        let p = &*self.plan;
        if self.outputs.get(f.output as usize).and_then(|o| o.as_ref()).is_none() {
            return Err(Error::Missing("output"));
        }
        let route = p.route;
        let (w, h) = (p.width, p.height);
        let el_w = if p.el_scale == 2 { w / 2 } else { w };
        let el_h = if p.el_scale == 2 { h / 2 } else { h };
        let needs_el = route == plan::ROUTE_DUAL;
        if route == plan::ROUTE_PIECEWISE && (p.layout == 0) != (p.depth == 8) {
            return Ok((-2, 0)); // the 4:2:0 P010 kernel isn't built with the production settings either
        }
        self.surface(f.bl_surface, w, h)?;
        if needs_el {
            self.surface(f.el_surface, el_w, el_h)?;
        }
        let mut waits = Waits::default();
        if let Some(s) = self.decode_wait(ci, 0, f.bl_surface)? {
            waits.push(s);
        }
        if needs_el {
            if let Some(s) = self.decode_wait(ci, 1, f.el_surface)? {
                waits.push(s);
            }
        }
        let decode_waits = waits.len();
        // The shell's OSD buffer: Qt's rendering into it may still be running.
        let compose = self.sources_used && self.sources.dirty && self.plan.overlay_visible != 0;
        let fused = self.fused_overlay();
        if compose || fused || self.cb1_overlay() {
            if let Some(sh) = self.sources.shell() {
                // Export failure cannot authorize reading an unknown producer.
                let sync_file = crate::interop::sync::export_sync_file(sh.fd, crate::interop::sync::DMA_BUF_SYNC_READ)?;
                {
                    if crate::interop::sync::signalled(sync_file) {
                        unsafe { libc::close(sync_file) };
                    } else {
                        let sem = self.ring[ci].decode[2];
                        if !crate::fault::hit("producer-timeout")
                            && crate::interop::sync::semaphore_from_sync_file(&self.d, sem, sync_file).is_ok()
                        {
                            waits.push(sem);
                        } else {
                            let ready = crate::interop::sync::wait_sync_file(sync_file, 1000);
                            unsafe { libc::close(sync_file) };
                            #[cfg(feature = "test-faults")]
                            eprintln!("dvvk test fallback: ready={}", ready.is_ok());
                            ready?;
                        }
                    }
                }
            }
        }
        if let Some(t) = self.ring[ci].deadline.as_mut() {
            t.prepare_ms = (monotonic_ns() - t.begin_ns) as f64 / 1e6 - t.ring_ms;
            t.decode_waits = decode_waits;
            t.overlay_waits = waits.len() - decode_waits;
            t.overlay = self.plan.overlay_visible != 0;
            t.empty = self.shell_empty;
        }
        // DVVK_VERIFY: is this frame checked (its reference output allocated
        // as the output is laid out, its result zeroed)?
        let stride = self.outputs[f.output as usize].as_ref().map(|o| o.stride).unwrap_or(0);
        let (check, allocate) = match self.verify.as_mut() {
            Some(v) => {
                let due = v.frames % v.every == 0;
                v.frames += 1;
                (due, due && v.out.as_ref().map(|o| o.1) != Some(stride))
            }
            None => (false, false),
        };
        if allocate {
            self.idle_checked()?;
            let out = DeviceBuffer::new(&self.d, stride as u64 * CANVAS_H as u64)?;
            let v = self.verify.as_mut().unwrap();
            if let Some((old, _)) = v.out.replace((out, stride)) {
                old.destroy(&self.d);
            }
        }
        if let Some(r) = self.ring[ci].verify.as_mut() {
            r.bytes_mut()[..8].copy_from_slice(&[0u8, 0, 0, 0, 255, 255, 255, 255]);
        }
        self.ring[ci].verified = check;
        self.ring[ci].hdr10plus = self.stats().then(|| {
            let mut metadata = vec![0u64; f.metadata.len().div_ceil(8)];
            let bytes = unsafe { std::slice::from_raw_parts_mut(metadata.as_mut_ptr() as *mut u8, f.metadata.len()) };
            bytes.copy_from_slice(f.metadata);
            let (a, pl) = (self.plan.active, self.plan.placement);
            let area = [a[0].max(pl[0]), a[1].max(pl[1]), a[2].min(pl[0] + pl[2]), a[3].min(pl[1] + pl[3])];
            Hdr10PlusFrame { metadata, size: f.metadata.len(), overlay: self.plan.overlay_visible != 0, area }
        });
        let result = self.record_submit(f, ci, waits.as_slice(), check);
        let ticket = match result {
            Ok(ticket) => ticket,
            Err(e) => {
                // Recording updates cached bounds/colour/damage state. A failed
                // submission did not establish those GPU results; fail closed
                // rather than reusing speculative caches on a later frame.
                self.submission_failed = true;
                return Err(e);
            }
        };
        if let Some(t) = self.ring[ci].deadline.as_mut() {
            t.return_ns = monotonic_ns();
        }
        self.ring[ci].ticket = ticket;
        self.ring[ci].plan_ms = self.last_plan_ms;
        self.next = (ci + 1) % RING;
        if compose || fused || self.cb1_overlay() {
            self.sources.used(ticket);
            self.sources.dirty = false;
            self.sources.dirty_rect = Some([0, 0, 0, 0]);
        }
        self.prev_overlay = self.plan.overlay_visible != 0;
        Ok((0, ticket))
    }

    fn record_submit(&mut self, f: &FrameIn, ci: usize, waits: &[vk::Semaphore], check: bool) -> Result<u64> {
        let slot = self.ring[ci].slot();
        let p = &*self.plan;
        let out = self.outputs.get(f.output as usize).and_then(|o| o.as_ref()).ok_or(Error::Missing("output"))?;
        let (out_buffer, out_stride, out_fd) = (out.buffer.buffer, out.stride, out.fd);
        let mut shell_read = None;
        self.ring[ci].bounds_generation = None;
        let route = p.route;
        let (w, h) = (p.width, p.height);
        // The tables: only when this context's copy is of other ones (P1).
        if self.ring[ci].tables_generation != Some(p.tables_generation) {
            let tables = self.ring[ci].tables.bytes_mut();
            let mut put =
                |offset: u64, src: &[u8]| tables[offset as usize..offset as usize + src.len()].copy_from_slice(src);
            put(T_SINGLE, bytes_of(&p.single_table));
            put(T_MAPPING, bytes_of(&p.mapping));
            put(T_RESIDUAL, bytes_of(&p.residual));
            put(T_PARAMS, bytes_of(&p.mmr_params));
            put(T_CHROMA_MAPPING, bytes_of(&p.chroma_mapping));
            put(T_LUT, bytes_of(&p.mmr_lut));
            put(T_LUMA, bytes_of(&p.luma_table));
            put(T_RESHAPE, &p.reshape);
            self.ring[ci].tables_generation = Some(p.tables_generation);
        }
        self.ring[ci].packets.bytes_mut().copy_from_slice(&p.packets);
        self.ring[ci].error.bytes_mut()[..4].copy_from_slice(&0u32.to_le_bytes());
        // HDR10+ output: the pack adds this frame's statistics to a zeroed record
        let stats = self.stats();
        if stats {
            self.ring[ci].stats.bytes_mut()[..STATS_WORDS * 4].fill(0);
        }
        // The overlay's colour error belongs to the prepared overlay: every
        // frame that uses it reports it.
        self.ring[ci].gui_error.bytes_mut()[..4].copy_from_slice(&self.overlay_error_flag.to_le_bytes());
        let compose = self.sources_used && self.sources.dirty && p.overlay_visible != 0 && !self.cb1_overlay();
        let fused = self.fused_overlay();
        if p.overlay_visible != 0 && fused != self.overlay_fused {
            // The other path's cache: start over.
            self.keys_valid = false;
            self.overlay_fused = fused;
        }
        let coeff_changed = self.overlay_coeff != p.gui_coeff;
        let prepare_overlay =
            !fused && !self.cb1_overlay() && p.overlay_visible != 0 && (compose || self.overlay_dirty || coeff_changed);
        let fused_invalidate = fused && (coeff_changed || !self.keys_valid);
        if check {
            // The reference prepares the overlay afresh from this frame's coefficients.
            let coeff = bytes_of(&p.gui_coeff);
            self.ring[ci].gui_coeff.bytes_mut()[..coeff.len()].copy_from_slice(coeff);
        }
        if fused {
            // The pack reads this frame's coefficients and reports its own
            // errors and changed pixels.
            self.ring[ci].gui_error.bytes_mut()[..8].copy_from_slice(&[0u8; 8]);
            let coeff = bytes_of(&p.gui_coeff);
            self.ring[ci].gui_coeff.bytes_mut()[..coeff.len()].copy_from_slice(coeff);
            self.overlay_coeff = p.gui_coeff;
            self.overlay_dirty = false;
            self.keys_valid = true;
        }
        // Native frames do not refresh the general overlay cache. A later
        // subtitle/desktop frame must rebuild it even with unchanged metadata.
        if let Some(coeff) = self.cb1 {
            self.overlay_dirty = true;
            self.keys_valid = false;
            self.ring[ci].gui_coeff.bytes_mut()[..128].copy_from_slice(bytes_of(&coeff));
        }
        // The area to prepare again: only the subtitles' old and new area when
        // nothing else changed; the whole canvas otherwise.
        let full = [0u32, 0, CANVAS_W, CANVAS_H];
        let rect = if compose && !self.overlay_dirty && !coeff_changed && self.keys_valid {
            match self.sources.dirty_rect {
                Some(r) if r[2] > r[0] && r[3] > r[1] => {
                    [r[0] & !15, r[1] & !15, ((r[2] + 15) & !15).min(CANVAS_W), ((r[3] + 15) & !15).min(CANVAS_H)]
                }
                Some(_) => [0, 0, 0, 0],
                None => full,
            }
        } else {
            full
        };
        let invalidate = coeff_changed || !self.keys_valid;
        if prepare_overlay {
            self.keys_valid = true;
        }
        if prepare_overlay {
            self.ring[ci].gui_error.bytes_mut()[..4].copy_from_slice(&0u32.to_le_bytes());
            self.overlay_prepared_by = Some(ci);
            let coeff = bytes_of(&p.gui_coeff);
            self.ring[ci].gui_coeff.bytes_mut()[..coeff.len()].copy_from_slice(coeff);
            self.overlay_coeff = p.gui_coeff;
            self.overlay_dirty = false;
        }

        // What of the output buffer this frame writes (damage.rs): the packet
        // rows, the film's rectangle and what the overlay changed since that
        // buffer was last written; everything when anything else changed.
        let regions = {
            use std::hash::{Hash, Hasher};
            let mut hasher = std::collections::hash_map::DefaultHasher::new();
            (
                p.pack,
                p.route,
                p.overlay_visible,
                fused,
                p.active,
                p.black,
                p.top_left,
                p.source_w,
                p.source_h,
                p.el_method,
                out_stride,
            )
                .hash(&mut hasher);
            for c in p.gui_coeff {
                c.to_bits().hash(&mut hasher);
            }
            self.map.as_ref().map(|m| m.key).hash(&mut hasher);
            // outside the active area every pixel is p.black (in the key): letterbox bars are not film
            let film = (p.placement[2] > 0 && p.placement[3] > 0).then(|| {
                [p.placement[0].max(p.active[0]), p.placement[1].max(p.active[1]),
                 (p.placement[0] + p.placement[2]).min(p.active[2]), (p.placement[1] + p.placement[3]).min(p.active[3])]
            });
            let packet_rows = if self.map.is_some() { 0 } else { (p.packet_count * 3072).div_ceil(CANVAS_W) };
            // (HDR10+: the whole picture, so the pack measures every film pixel once)
            self.damage.plan(f.output as usize, hasher.finish(), film, packet_rows, check || fused_invalidate || stats)
        };
        if self.profile.is_some() && self.damage.stats.0 >= 120 {
            let (n, partial) = self.damage.stats;
            eprintln!(
                "dvvk damage: {} of {} pictures written in part, {:.1}% of the canvas on average",
                partial,
                n,
                100.0 * self.damage.area / n as f64
            );
            self.damage.stats = (0, 0);
            self.damage.area = 0.0;
        }
        let d = &self.d;
        let cmd = self.ring[ci].cmd;
        unsafe {
            d.device.reset_command_buffer(cmd, vk::CommandBufferResetFlags::empty())?;
            d.device.begin_command_buffer(
                cmd,
                &vk::CommandBufferBeginInfo::default().flags(vk::CommandBufferUsageFlags::ONE_TIME_SUBMIT),
            )?;
        }
        // After everything submitted before (shared intermediates, caches).
        gpu::compute_barrier(d, cmd);
        let query = self.ring[ci].query;
        self.ring[ci].prepared = prepare_overlay && rect[2] > rect[0] && rect[3] > rect[1];
        let stamp = |cmd: vk::CommandBuffer, point: u32| {
            if let Some(q) = query {
                unsafe { d.device.cmd_write_timestamp2(cmd, vk::PipelineStageFlags2::COMPUTE_SHADER, q, point) };
            }
        };
        if let Some(q) = query {
            unsafe {
                d.device.cmd_reset_query_pool(cmd, q, 0, PROFILE_TOTAL_POINTS);
                d.device.cmd_write_timestamp2(cmd, vk::PipelineStageFlags2::TOP_OF_PIPE, q, 0);
            }
        }
        let bl = &self.surfaces[&f.bl_surface];
        gpu::acquire_foreign_images(d, cmd, &[bl.luma.image, bl.chroma.image]);
        gpu::foreign_buffer(d, cmd, out_buffer, true);
        stamp(cmd, 7);

        let (first, last) = if p.row_last != 0 { (p.row_first, p.row_last) } else { (0, h) };
        // (the BL's surfaces were looked up before the uploads)
        // Fused: single layer in the pack itself; half-size-EL FEL as pass A
        // (chroma) + the pack (luma). Everything else staged.
        let source = self.pack_source();
        self.ring[ci].fel_stamped = query.is_some() && source == 0 && route == plan::ROUTE_DUAL && p.equal == 0;
        let el_view = if route == plan::ROUTE_DUAL { self.surfaces[&f.el_surface].luma.view } else { bl.luma.view };
        if source == 1 {
            // nothing before the pack
        } else if source == 2 {
            let el = &self.surfaces[&f.el_surface];
            gpu::acquire_foreign_images(d, cmd, &[el.luma.image, el.chroma.image]);
            let t = slot.tables;
            let s = self.sampler;
            let cw = w / 2;
            let push = [w, h, p.chroma_phase, p.el_method, p.dual, p.chroma_kind[0], p.chroma_kind[1], first / 2];
            self.dispatch(
                cmd,
                &self.fel_chroma,
                &[
                    Bind::Sampled(bl.luma.view, s),
                    Bind::Sampled(bl.chroma.view, s),
                    Bind::Sampled(el.chroma.view, s),
                    Bind::Range(t, T_PARAMS, 768),
                    Bind::Range(t, T_RESIDUAL, 12288),
                    Bind::Range(t, T_LUT, 49152),
                    Bind::Range(t, T_CHROMA_MAPPING, 4096),
                    Bind::Buffer(self.planes[1].buffer),
                    Bind::Buffer(self.planes[2].buffer),
                    Bind::Buffer(slot.error),
                    Bind::Buffer(slot.error),
                ],
                &push,
                (cw.div_ceil(64), (last - first) / 2),
            );
        } else {
            self.fel_query.set(query);
            self.record_staged(cmd, &slot, f, bl, first, last);
            self.fel_query.set(None);
        }
        gpu::compute_barrier(d, cmd);

        stamp(cmd, 1);
        stamp(cmd, 8);
        if self.cb1_overlay() && (self.sources.dirty || !self.cb1_tiles_valid) {
            // CB1's occupancy (P3): the tiles the shell's damage touched (all
            // after anything else), then their count, snapshotted for
            // collect_frame (zero: a transparent overlay is bypassed).
            let sh = self.sources.shell().unwrap();
            gpu::acquire_foreign_images(d, cmd, &[sh.image.image]);
            shell_read = Some(sh.fd);
            let full = [[0, 0, CANVAS_W, CANVAS_H]];
            let dirty = match (self.cb1_tiles_valid, self.cb1_dirty.take()) {
                (true, Some(rects)) => rects,
                _ => full.to_vec(),
            };
            let tiles = crate::damage::tile_rects(&dirty, CB1_TILE, CB1_TILES);
            let flip = self.sources.shell_flip as u32;
            let binds = [Bind::Sampled(sh.image.view, self.linear), Bind::Buffer(self.cb1_tiles.buffer)];
            gpu::compute_barrier(d, cmd);
            for (i, t) in tiles.iter().enumerate() {
                let push = [CANVAS_W, CANVAS_H, CB1_TILES.0, CB1_TILES.1, t[0], t[1], 0u32, flip];
                if i == 0 {
                    self.dispatch(cmd, &self.cb1_tiles_pipe, &binds, &push, (t[2] - t[0], t[3] - t[1]));
                } else {
                    gpu::push_constants(d, cmd, &self.cb1_tiles_pipe, &push);
                    unsafe { d.device.cmd_dispatch(cmd, t[2] - t[0], t[3] - t[1], 1) };
                }
            }
            gpu::compute_barrier(d, cmd);
            self.dispatch(
                cmd,
                &self.cb1_tiles_pipe,
                &binds,
                &[CANVAS_W, CANVAS_H, CB1_TILES.0, CB1_TILES.1, 0, 0, 1u32, flip],
                (1, 1),
            );
            gpu::compute_barrier(d, cmd);
            let region = [vk::BufferCopy { src_offset: 0, dst_offset: 0, size: 4 }];
            unsafe {
                d.device.cmd_copy_buffer(cmd, self.cb1_tiles.buffer, self.ring[ci].bounds_result.buffer, &region)
            };
            self.ring[ci].bounds_generation = Some(self.shell_generation);
            if !self.cb1_tiles_valid {
                eprintln!("dvvk: native CB1 OSD (GPU tile occupancy)");
            }
            self.cb1_tiles_valid = true;
            self.cb1_dirty = Some(Vec::new());
            self.ring[ci].prepared = true;
        }
        stamp(cmd, 9);
        // The overlay's tile map and colour cache, when the overlay or the
        // movie's colour metadata changed.
        if prepare_overlay && rect[2] > rect[0] && rect[3] > rect[1] {
            let s = &self.sources;
            let r = Sources::ranges();
            let from_sources = self.sources_used;
            let atlas = s.atlas[s.subs_slot].buffer;
            let shell_view = match s.shell() {
                Some(sh) if from_sources => {
                    gpu::acquire_foreign_images(d, cmd, &[sh.image.image]);
                    shell_read = Some(sh.fd);
                    sh.image.view
                }
                _ => self.surfaces[&f.bl_surface].luma.view, // unused: a valid view to bind
            };
            let (ew, eh) = (rect[2] - rect[0], rect[3] - rect[1]);
            let push = PreparePush {
                w: CANVAS_W,
                h: CANVAS_H,
                has_shell: (from_sources && s.shell().is_some()) as u32,
                has_subs: (from_sources && s.subs_parts > 0) as u32,
                tiles_x: s.tiles_x.max(1),
                tile: overlay::TILE,
                origin: [rect[0], rect[1]],
                invalidate: invalidate as u32,
                flip: s.shell_flip as u32,
            };
            self.dispatch(
                cmd,
                &self.overlay_prepare[from_sources as usize],
                &[
                    Bind::Buffer(self.overlay.buffer),
                    Bind::Range(atlas, r[0].0, r[0].1),
                    Bind::Range(atlas, r[1].0, r[1].1),
                    Bind::Range(atlas, r[2].0, r[2].1),
                    Bind::Sampled(shell_view, self.linear),
                    Bind::Buffer(self.gui_keys.buffer),
                    Bind::Buffer(self.gui_colours.buffer),
                    Bind::Buffer(self.gui_tiles.buffer),
                    Bind::Buffer(slot.gui_coeff),
                    Bind::Buffer(slot.gui_error),
                ],
                &push,
                (ew.div_ceil(16), eh.div_ceil(16)),
            );
            gpu::compute_barrier(d, cmd);
        }
        stamp(cmd, 2);
        // Resize maps, when the geometry changes (source_resize_prepare).
        let (dw, dh) = (p.placement[2], p.placement[3]);
        if p.pack == plan::PACK_RESIZED {
            let key = [w, h, dw, dh, p.top_left];
            if self.resize_key != Some(key) {
                unsafe {
                    d.device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, self.resize_prepare.pipeline)
                };
                self.push.bind(cmd, &self.resize_prepare, &[Bind::Buffer(self.ymap.buffer)]);
                gpu::push_constants(
                    d,
                    cmd,
                    &self.resize_prepare,
                    &ResizePush { source: [w, h], dest: [dw, dh], top_left: p.top_left },
                );
                unsafe { d.device.cmd_dispatch(cmd, dh.div_ceil(64), 1, 1) };
                gpu::compute_barrier(d, cmd);
                self.resize_key = Some(key);
            }
        }

        // Pack into the output.
        let overlay_kind = self.pack_overlay();
        let shell_view = match self.sources.shell() {
            Some(sh) if fused || self.cb1_overlay() => {
                if shell_read != Some(sh.fd) {
                    gpu::acquire_foreign_images(d, cmd, &[sh.image.image]);
                }
                shell_read = Some(sh.fd);
                sh.image.view
            }
            _ => bl.luma.view, // unused: a valid view to bind
        };
        let variant = select_pack(&PackRoute::of(p), overlay_kind).1;
        // HDR10 output: the frame's parameters, and the scene's 3D LUT baked
        // when they changed (map_bake.comp), before the pack reads them.
        let mapped = self.map.is_some();
        if let Some(m) = self.map.as_ref() {
            self.ring[ci].map_params.bytes_mut()[..m.gpu.bytes.len()].copy_from_slice(&m.gpu.bytes);
            if self.map_baked != Some(m.key) {
                let n = self.map_lut.n;
                // earlier frames' packs read the LUT and cells: done before these writes
                gpu::compute_barrier(d, cmd);
                unsafe { d.device.cmd_fill_buffer(cmd, self.map_cells.buffer, 0, vk::WHOLE_SIZE, 0) };
                gpu::compute_barrier(d, cmd);
                let push: [u32; 2] = [n, self.d.options.map_thresh.to_bits()];
                let binds =
                    [Bind::Buffer(slot.map_params), Bind::Buffer(self.map_nodes.buffer), Bind::Buffer(self.map_cells.buffer)];
                // nodes, the cells they interpolate badly, the marks in the nodes' alpha
                self.dispatch3(cmd, &self.map_bake[0], &binds, &push, n.div_ceil(4));
                gpu::compute_barrier(d, cmd);
                self.dispatch3(cmd, &self.map_bake[1], &binds, &push, (n - 1).div_ceil(4));
                gpu::compute_barrier(d, cmd);
                self.dispatch3(cmd, &self.map_bake[2], &binds, &push, n.div_ceil(4));
                self.map_lut.record_copy(d, cmd, self.map_nodes.buffer);
                gpu::compute_barrier(d, cmd);
                self.map_baked = Some(m.key);
                self.map_bakes += 1;
            }
        } else {
            self.map_lut.record_init(d, cmd);
        }
        let fixup = mapped && map_spec(&self.d.options) == 1;
        if fixup {
            // map_fixup's list emptied (the last frame's fix-up read it)
            gpu::indirect_barrier(d, cmd);
            let header: [u32; 4] = [0, 1, 1, 0];
            let bytes = unsafe { std::slice::from_raw_parts(header.as_ptr() as *const u8, 16) };
            unsafe { d.device.cmd_update_buffer(cmd, self.map_cells.buffer, u64::from(self.map_list) * 4, bytes) };
            gpu::indirect_barrier(d, cmd);
        }
        let pack = if mapped {
            match self.pack_map.get(&Self::pack_map_key(variant, self.stats())) {
                Some(pack) => pack,
                None => return Err(Error::Missing("an HDR10 pack variant")),
            }
        } else {
            match variant {
                PackVariant::Annexb(i) => &self.pack_annexb[i],
                PackVariant::Regular(i) => match self.pack[i].as_ref() {
                    Some(pack) => pack,
                    // ensure_pack made the variant this frame uses
                    None => return Err(Error::Missing("a pack variant")),
                },
            }
        };
        let fused_tables = if source == 1 {
            Bind::Range(slot.tables, T_SINGLE, 6144)
        } else {
            Bind::Range(slot.tables, T_MAPPING, 2048)
        };
        unsafe { d.device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, pack.pipeline) };
        self.push.bind(
            cmd,
            pack,
            &[
                Bind::Buffer(self.planes[0].buffer),
                Bind::Buffer(self.planes[1].buffer),
                Bind::Buffer(self.planes[2].buffer),
                Bind::Buffer(slot.packets),
                Bind::Buffer(out_buffer),
                Bind::Buffer(self.ymap.buffer),
                Bind::Buffer(self.gui_colours.buffer),
                Bind::Buffer(self.gui_tiles.buffer),
                Bind::Buffer(slot.gui_error),
                Bind::Sampled(bl.luma.view, self.sampler),
                Bind::Sampled(bl.chroma.view, self.sampler),
                Bind::Sampled(el_view, self.sampler),
                fused_tables,
                Bind::Range(slot.tables, T_RESIDUAL, 4096),
                Bind::Buffer(slot.error),
                Bind::Sampled(shell_view, self.linear),
                Bind::Buffer(self.gui_keys.buffer),
                Bind::Buffer(slot.gui_coeff),
                Bind::Sampled(self.cb1_luts[0].view, self.linear),
                Bind::Sampled(self.cb1_luts[1].view, self.linear),
                Bind::Buffer(self.cb1_tiles.buffer),
                Bind::Sampled(self.map_lut.view, self.linear),
                Bind::Buffer(slot.map_params),
                Bind::Buffer(self.map_cells.buffer),
                Bind::Buffer(slot.stats),
            ],
        );
        let push = PackPush {
            active: p.active,
            black: p.black,
            placement: p.placement,
            w: CANVAS_W,
            h: CANVAS_H,
            stride_words: out_stride / 4,
            // HDR10 output carries no Dolby Vision metadata in the picture
            packet_count: if mapped { 0 } else { p.packet_count },
            top_left: p.top_left,
            source_w: p.source_w,
            source_h: p.source_h,
            el_method: p.el_method,
            gui_flags: fused_invalidate as u32
                // the shell's rows bottom first (Kodi's GUI framebuffer)
                | (self.sources.shell_flip as u32) << 1
                // the shell's colours computed for every pixel instead of kept in the
                // per-pixel cache (the same values): on Vega 8 the cache's traffic
                // cost more than the arithmetic (a changed 4K desktop 25 -> 14.5 ms)
                | 1 << 3
                // a linear half-float shell (a desktop with HDR content in it)
                | (self.sources.shell().map(|s| s.linear).unwrap_or(false) as u32) << 5
                // HDR10+ output: this pass measures the film (not the reference pass)
                | (stats as u32) << 6,
            origin: [0, 0],
            chroma_filter: p.chroma_filter,
        };
        // Output rows a workgroup covers: 4, or 16 with the Annex B chroma tile
        // (damage rectangles rounded out to it; a pixel written twice gets the
        // same value).
        let wg_h = if matches!(variant, PackVariant::Annexb(_)) { 16 } else { 4 };
        self.dispatch_partitioned(cmd, pack, &push, regions.as_deref(), wg_h);
        if fixup {
            // the pairs the pack listed (a marked LUT cell), computed exactly
            gpu::indirect_barrier(d, cmd);
            unsafe { d.device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, self.map_fixup.pipeline) };
            self.push.bind(
                cmd,
                &self.map_fixup,
                &[Bind::Buffer(out_buffer), Bind::Buffer(slot.map_params), Bind::Buffer(self.map_cells.buffer)],
            );
            gpu::push_constants(d, cmd, &self.map_fixup, &[CANVAS_W, out_stride / 4]);
            unsafe { d.device.cmd_dispatch_indirect(cmd, self.map_cells.buffer, u64::from(self.map_list) * 4) };
        }
        stamp(cmd, 3);
        if check {
            gpu::compute_barrier(d, cmd);
            let read = self.record_reference(
                cmd,
                &slot,
                f,
                ci,
                bl,
                el_view,
                (first, last),
                (out_buffer, out_stride),
                &push,
                shell_read.is_some(),
            );
            shell_read = shell_read.or(read);
        }
        gpu::foreign_buffer(d, cmd, out_buffer, false);
        gpu::compute_to_host(d, cmd);
        unsafe { d.device.end_command_buffer(cmd)? };
        let ticket = self.ticket + 1;
        let mut wait_infos = [vk::SemaphoreSubmitInfo::default(); 4];
        let mut n_waits = 0;
        for &s in waits {
            wait_infos[n_waits] =
                vk::SemaphoreSubmitInfo::default().semaphore(s).stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER);
            n_waits += 1;
        }
        if let (Some(rel), true) = (self.release, f.release_wait > 0) {
            wait_infos[n_waits] = vk::SemaphoreSubmitInfo::default()
                .semaphore(rel)
                .value(f.release_wait)
                .stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER);
            n_waits += 1;
        }
        let wait_infos = &wait_infos[..n_waits];
        let signal_infos = [
            vk::SemaphoreSubmitInfo::default()
                .semaphore(self.timeline)
                .value(ticket)
                .stage_mask(vk::PipelineStageFlags2::ALL_COMMANDS),
            vk::SemaphoreSubmitInfo::default()
                .semaphore(self.ring[ci].done)
                .stage_mask(vk::PipelineStageFlags2::ALL_COMMANDS),
        ];
        let cmds = [vk::CommandBufferSubmitInfo::default().command_buffer(cmd)];
        let submit = [vk::SubmitInfo2::default()
            .wait_semaphore_infos(wait_infos)
            .command_buffer_infos(&cmds)
            .signal_semaphore_infos(&signal_infos)];
        if let Some(t) = self.ring[ci].deadline.as_mut() {
            t.release_ready = self
                .release
                .map(|s| {
                    unsafe { d.device.get_semaphore_counter_value(s) }.map(|v| v >= f.release_wait).unwrap_or(false)
                })
                .unwrap_or(true);
            t.submit_ns = monotonic_ns();
        }
        if crate::fault::hit("queue-submit") {
            return Err(Error::Vk(vk::Result::ERROR_UNKNOWN));
        }
        unsafe { d.device.queue_submit2(d.queue, &submit, vk::Fence::null())? };
        if let Some(t) = self.ring[ci].deadline.as_mut() {
            t.queue_call_ms = (monotonic_ns() - t.submit_ns) as f64 / 1e6;
        }
        self.ticket = ticket;
        // queue_submit2 succeeded: retain the context even if FD export fails.
        self.ring[ci].ticket = ticket;
        // The frame's fence on the output dmabuf: the compositor (KWin waits
        // for a committed buffer's implicit fences) and KMS see it as written
        // only when it is.
        let export_start = if self.deadline_trace { monotonic_ns() } else { 0 };
        let fence = match crate::interop::sync::sync_file_from_semaphore(d, self.ring[ci].done) {
            Ok(fd) => fd,
            Err(e) => {
                // The binary signal was not exported/reset. Do not reuse it,
                // and do not return an error while callers could free inputs
                // still being read by the submitted GPU work.
                self.submission_failed = true;
                self.wait_complete(ticket)?;
                return Err(e);
            }
        };
        if let Some(t) = self.ring[ci].deadline.as_mut() {
            t.export_ms = (monotonic_ns() - export_start) as f64 / 1e6;
        }
        let import_start = if self.deadline_trace { monotonic_ns() } else { 0 };
        let r = crate::interop::sync::import_sync_file(out_fd, fence, crate::interop::sync::DMA_BUF_SYNC_WRITE);
        // And on the overlay buffer it read: its next contents wait for this frame.
        let shell_fenced = shell_read.map(|fd| {
            crate::interop::sync::import_sync_file(fd, fence, crate::interop::sync::DMA_BUF_SYNC_READ).is_ok()
        });
        unsafe { libc::close(fence) };
        if let Some(t) = self.ring[ci].deadline.as_mut() {
            t.import_ms = (monotonic_ns() - import_start) as f64 / 1e6;
        }
        if shell_fenced == Some(false) {
            // The overlay's writer can't wait on the GPU: the caller waits for the ticket.
            self.implicit_failed = true;
        }
        if r.is_err() {
            // An older kernel: the caller has to wait for the ticket before committing.
            self.implicit_failed = true;
        }
        Ok(ticket)
    }
}

impl Engine {
    /// DVVK_VERIFY: this frame again by the reference route into the verify
    /// output, then the shown output compared with it. The overlay's shell
    /// fd if this acquired it (the caller fences it).
    #[allow(clippy::too_many_arguments)]
    fn record_reference(
        &self,
        cmd: vk::CommandBuffer,
        slot: &Slot,
        f: &FrameIn,
        ci: usize,
        bl: &va::SurfaceImport,
        el_view: vk::ImageView,
        rows: (u32, u32),
        out: (vk::Buffer, u32),
        push: &PackPush,
        shell_acquired: bool,
    ) -> Option<i32> {
        let (Some(v), Some(result)) = (self.verify.as_ref(), self.ring[ci].verify.as_ref()) else { return None };
        let (reference, _) = v.out.as_ref()?;
        let d = &self.d;
        let p = &*self.plan;
        let barrier = || gpu::compute_barrier(d, cmd);
        self.reference_pass.set(true);
        self.record_staged(cmd, slot, f, bl, rows.0, rows.1);
        self.reference_pass.set(false);
        barrier();
        let mut read = None;
        // The prepared-overlay oracle quantizes samples as sRGB BGRA8. A
        // fused linear FP16 shell must retain its direct linear conversion;
        // video reconstruction is still independently staged above.
        let linear_reference = self.fused_overlay() && push.gui_flags & 32 != 0;
        if p.overlay_visible != 0 && !self.cb1_overlay() && !linear_reference {
            let s = &self.sources;
            let r = Sources::ranges();
            let from_sources = self.sources_used;
            let atlas = s.atlas[s.subs_slot].buffer;
            let shell_view = match s.shell() {
                Some(sh) if from_sources => {
                    if !shell_acquired {
                        gpu::acquire_foreign_images(d, cmd, &[sh.image.image]);
                        read = Some(sh.fd);
                    }
                    sh.image.view
                }
                _ => bl.luma.view,
            };
            let prepare = PreparePush {
                w: CANVAS_W,
                h: CANVAS_H,
                has_shell: (from_sources && s.shell().is_some()) as u32,
                has_subs: (from_sources && s.subs_parts > 0) as u32,
                tiles_x: s.tiles_x.max(1),
                tile: overlay::TILE,
                origin: [0, 0],
                invalidate: 1,
                flip: s.shell_flip as u32,
            };
            self.dispatch(
                cmd,
                &self.overlay_prepare[from_sources as usize],
                &[
                    Bind::Buffer(self.overlay.buffer),
                    Bind::Range(atlas, r[0].0, r[0].1),
                    Bind::Range(atlas, r[1].0, r[1].1),
                    Bind::Range(atlas, r[2].0, r[2].1),
                    Bind::Sampled(shell_view, self.linear),
                    Bind::Buffer(self.gui_keys.buffer),
                    Bind::Buffer(self.gui_colours.buffer),
                    Bind::Buffer(self.gui_tiles.buffer),
                    Bind::Buffer(slot.gui_coeff),
                    Bind::Buffer(v.err.buffer),
                ],
                &prepare,
                (CANVAS_W.div_ceil(16), CANVAS_H.div_ceil(16)),
            );
            barrier();
        }
        let ref_overlay = if self.cb1_overlay() {
            3
        } else if linear_reference {
            2
        } else {
            p.overlay_visible.min(1)
        };
        // Source 0's variants are always made with the engine.
        let Some(pack) = self.pack[(ref_overlay * 3 + p.pack) as usize].as_ref() else {
            eprintln!("dvvk verify: no reference pack variant");
            return read;
        };
        let reference_push = PackPush {
            gui_flags: if self.cb1_overlay() {
                push.gui_flags & 2
            } else if linear_reference {
                push.gui_flags & (32 | 2)
            } else {
                0
            },
            ..*push
        };
        let native_view = self.sources.shell().map(|sh| sh.image.view).unwrap_or(bl.luma.view);
        self.dispatch(
            cmd,
            pack,
            &[
                Bind::Buffer(self.planes[0].buffer),
                Bind::Buffer(self.planes[1].buffer),
                Bind::Buffer(self.planes[2].buffer),
                Bind::Buffer(slot.packets),
                Bind::Buffer(reference.buffer),
                Bind::Buffer(self.ymap.buffer),
                Bind::Buffer(self.gui_colours.buffer),
                Bind::Buffer(self.gui_tiles.buffer),
                Bind::Buffer(v.err.buffer),
                Bind::Sampled(bl.luma.view, self.sampler),
                Bind::Sampled(bl.chroma.view, self.sampler),
                Bind::Sampled(el_view, self.sampler),
                Bind::Range(slot.tables, T_MAPPING, 2048),
                Bind::Range(slot.tables, T_RESIDUAL, 4096),
                Bind::Buffer(v.err.buffer),
                Bind::Sampled(native_view, self.linear),
                Bind::Buffer(self.gui_keys.buffer),
                Bind::Buffer(slot.gui_coeff),
                Bind::Sampled(self.cb1_luts[0].view, self.linear),
                Bind::Sampled(self.cb1_luts[1].view, self.linear),
                Bind::Buffer(self.cb1_tiles.buffer),
                Bind::Sampled(self.map_lut.view, self.linear),
                Bind::Buffer(slot.map_params),
                Bind::Buffer(self.map_cells.buffer),
                Bind::Buffer(slot.stats),
            ],
            &reference_push,
            ((CANVAS_W / 4).div_ceil(32), (CANVAS_H / 2).div_ceil(2)),
        );
        barrier();
        self.dispatch(
            cmd,
            &v.compare,
            &[Bind::Buffer(out.0), Bind::Buffer(reference.buffer), Bind::Buffer(result.buffer)],
            &[out.1 / 4, CANVAS_W, CANVAS_H],
            (CANVAS_W.div_ceil(64), CANVAS_H),
        );
        read
    }

    /// The staged reconstruction into the planes (the route's kernels 1:1
    /// with yblod's): every route but the fused ones, and DVVK_VERIFY's reference.
    fn record_staged(
        &self,
        cmd: vk::CommandBuffer,
        slot: &Slot,
        f: &FrameIn,
        bl: &va::SurfaceImport,
        first: u32,
        last: u32,
    ) {
        let p = &*self.plan;
        let d = &self.d;
        let route = p.route;
        let (w, h) = (p.width, p.height);
        if route == plan::ROUTE_SINGLE {
            // single_polynomial_p010, letterbox window as a row offset.
            unsafe { d.device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, self.single.pipeline) };
            self.push.bind(
                cmd,
                &self.single,
                &[
                    Bind::Sampled(bl.luma.view, self.sampler),
                    Bind::Sampled(bl.chroma.view, self.sampler),
                    Bind::Range(slot.tables, T_SINGLE, 6144),
                    Bind::Buffer(self.planes[0].buffer),
                    Bind::Buffer(self.planes[1].buffer),
                    Bind::Buffer(self.planes[2].buffer),
                    Bind::Buffer(slot.error),
                ],
            );
            gpu::push_constants(d, cmd, &self.single, &[w, h, first / 2]);
            unsafe { d.device.cmd_dispatch(cmd, (w / 2).div_ceil(16), ((last - first) / 2).div_ceil(8), 1) };
        } else if route == plan::ROUTE_PIECEWISE {
            let k = if p.depth == 8 {
                2
            } else if p.layout == 0 {
                3
            } else if p.order2 != 0 {
                1
            } else {
                0
            };
            let pipe = &self.fel.piecewise[k];
            let rows_per = if p.layout == 1 { 1 } else { 2 };
            #[repr(C)]
            #[derive(Clone, Copy)]
            struct PiecewisePush {
                mask: [u32; 4],
                w: u32,
                h: u32,
                policy: u32,
                row_offset: u32,
            }
            let push = PiecewisePush { mask: p.narrow_mask, w, h, policy: p.sampling, row_offset: first / rows_per };
            self.dispatch(
                cmd,
                pipe,
                &[
                    Bind::Sampled(bl.luma.view, self.sampler),
                    Bind::Sampled(bl.chroma.view, self.sampler),
                    Bind::Range(slot.tables, T_RESHAPE, 4544),
                    Bind::Buffer(self.planes[0].buffer),
                    Bind::Buffer(self.planes[1].buffer),
                    Bind::Buffer(self.planes[2].buffer),
                    Bind::Range(slot.tables, T_LUMA, 2048),
                    Bind::Buffer(slot.error),
                ],
                &push,
                ((w / 2).div_ceil(16), ((last - first) / rows_per).div_ceil(8)),
            );
        } else {
            let el = &self.surfaces[&f.el_surface];
            gpu::acquire_foreign_images(d, cmd, &[el.luma.image, el.chroma.image]);
            if p.equal != 0 {
                self.record_fel_equal(cmd, slot, p, bl, el, first, last);
            } else {
                self.record_fel(cmd, slot, p, bl, el, first, last);
            }
        }
    }

    /// The pack over the canvas, or over these damage rectangles only (each
    /// a dispatch from its own origin, rows rounded out to `wg_h`).
    fn dispatch_partitioned(
        &self,
        cmd: vk::CommandBuffer,
        pack: &Pipeline,
        push: &PackPush,
        regions: Option<&[crate::damage::Rect]>,
        wg_h: u32,
    ) {
        let d = &self.d;
        for (origin, groups) in partition(regions, wg_h) {
            gpu::push_constants(d, cmd, pack, &PackPush { origin, ..*push });
            unsafe { d.device.cmd_dispatch(cmd, groups[0], groups[1], 1) };
        }
    }

    fn dispatch<T: Copy>(&self, cmd: vk::CommandBuffer, pipe: &Pipeline, binds: &[Bind], push: &T, groups: (u32, u32)) {
        let d = &self.d;
        unsafe { d.device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, pipe.pipeline) };
        self.push.bind(cmd, pipe, binds);
        gpu::push_constants(d, cmd, pipe, push);
        unsafe { d.device.cmd_dispatch(cmd, groups.0.max(1), groups.1.max(1), 1) };
    }

    /// A cubic dispatch (map_bake: groups^3 workgroups).
    fn dispatch3<T: Copy>(&self, cmd: vk::CommandBuffer, pipe: &Pipeline, binds: &[Bind], push: &T, groups: u32) {
        let d = &self.d;
        unsafe { d.device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, pipe.pipeline) };
        self.push.bind(cmd, pipe, binds);
        gpu::push_constants(d, cmd, pipe, push);
        unsafe { d.device.cmd_dispatch(cmd, groups, groups, groups) };
    }

    /// reconstruct_impl's direct route for a half-size EL (opencl_backend.c),
    /// kernel for kernel: vertical_pair, luma_phase_guide, phase_vertical_uv,
    /// then mmr64_lut_dual_horizontal (dual MMR) or scale_horizontal +
    /// the table add (polynomial chroma). Luma rows [first, last).
    #[allow(clippy::too_many_arguments)] // one recording step's buffers and views, as recorded
    fn record_fel(
        &self,
        cmd: vk::CommandBuffer,
        slot: &Slot,
        p: &Plan,
        bl: &va::SurfaceImport,
        el: &va::SurfaceImport,
        first: u32,
        last: u32,
    ) {
        let (w, h) = (p.width, p.height);
        let (cw, ch) = (w / 2, h / 2);
        let t = slot.tables;
        let fb = |i: usize| Bind::Buffer(self.fel_buffers[i].buffer);
        let err = || Bind::Buffer(slot.error);
        let quarter = (cw * ch * 2) as u64;
        let f = &self.fel;
        let barrier = || gpu::compute_barrier(&self.d, cmd);
        let stamp = |point: u32| {
            if let Some(q) = self.fel_query.get() {
                unsafe { self.d.device.cmd_write_timestamp2(cmd, vk::PipelineStageFlags2::COMPUTE_SHADER, q, point) };
            }
        };
        // COMPUTE timestamp after acquire: separate pre-dispatch/decode waits
        // from the first kernel instead of folding them into vertical_pair.
        stamp(10);
        // c = 0: the EL luma upsampled vertically (EL rows [first/2, last/2)).
        // 32-bit stores; DVVK_VERIFY's reference keeps the original kernel.
        let w32 = !self.reference_pass.get();
        let (vertical, columns) = if w32 { (&f.vertical_pair_w32, cw / 2) } else { (&f.vertical_pair, cw) };
        self.dispatch(
            cmd,
            vertical,
            &[Bind::Sampled(el.luma.view, self.sampler), fb(F_V), err()],
            &[cw, ch, 0u32, p.el_method, first / 2],
            (columns.div_ceil(16), ((last - first) / 2).div_ceil(8)),
        );
        barrier();
        stamp(4);
        // luma, BL chroma phase and guide per 2x2 block.
        self.dispatch(
            cmd,
            &f.luma_phase_guide,
            &[
                Bind::Sampled(bl.luma.view, self.sampler),
                Bind::Sampled(bl.chroma.view, self.sampler),
                fb(F_V),
                Bind::Range(t, T_MAPPING, 2048),
                Bind::Range(t, T_RESIDUAL, 4096),
                Bind::Buffer(self.planes[0].buffer),
                fb(F_BP),
                fb(F_G),
                err(),
            ],
            &[w, h, p.chroma_phase, p.el_method, first / 2],
            ((w / 4).div_ceil(16), ((last - first) / 2).div_ceil(8)),
        );
        // c = 1: the EL chroma, phase + vertical (overwrites V: the luma pass is done).
        barrier();
        stamp(5);
        self.dispatch(
            cmd,
            &f.phase_vertical_uv,
            &[Bind::Sampled(el.chroma.view, self.sampler), fb(F_V), fb(F_VP), err()],
            &[cw / 2, ch / 2, p.chroma_phase, p.el_method, first / 4],
            ((cw / 2).div_ceil(16), ((last - first) / 4).div_ceil(8)),
        );
        barrier();
        stamp(6);
        let rows = (last - first) / 2;
        if p.dual != 0 {
            self.dispatch(
                cmd,
                &f.mmr_dual_horizontal,
                &[
                    fb(F_G),
                    fb(F_BP),
                    fb(F_V),
                    fb(F_VP),
                    Bind::Range(t, T_PARAMS, 768),
                    Bind::Range(t, T_RESIDUAL, 12288),
                    Bind::Buffer(self.planes[1].buffer),
                    Bind::Buffer(self.planes[2].buffer),
                    Bind::Range(t, T_LUT, 49152),
                    // unused bindings 9, 10 (kept for a stable layout), 11 error
                    fb(F_ES),
                    fb(F_ES),
                    err(),
                ],
                &[cw, ch, p.el_method, first / 2],
                ((cw / 4).div_ceil(64), rows),
            );
        } else {
            for c in 0..2u32 {
                let src = if c == 0 { fb(F_V) } else { fb(F_VP) };
                let es = Bind::Range(self.fel_buffers[F_ES].buffer, c as u64 * quarter, quarter);
                self.dispatch(
                    cmd,
                    &f.scale_horizontal,
                    &[src, es, err()],
                    &[cw, ch, p.el_method, first / 2],
                    (cw.div_ceil(64), rows),
                );
            }
            barrier();
            self.record_chroma(cmd, slot, p, first, last);
        }
    }

    /// The chroma of a non-dual frame, channel by channel, from the BL phase
    /// planes, the guide and the scaled EL planes (ES): the polynomial table
    /// add, or mmr64_lut / mmr96 / mmr (128), as reconstruct_impl picks them.
    fn record_chroma(&self, cmd: vk::CommandBuffer, slot: &Slot, p: &Plan, first: u32, last: u32) {
        let (cw, ch) = (p.width / 2, p.height / 2);
        let quarter = (cw * ch * 2) as u64;
        let t = slot.tables;
        let fb = |i: usize| Bind::Buffer(self.fel_buffers[i].buffer);
        let err = || Bind::Buffer(slot.error);
        let rows = (last - first) / 2;
        for c in 0..2u32 {
            let es = Bind::Range(self.fel_buffers[F_ES].buffer, c as u64 * quarter, quarter);
            let out = Bind::Buffer(self.planes[1 + c as usize].buffer);
            let kind = p.chroma_kind[c as usize];
            if kind == plan::CHROMA_POLY {
                self.dispatch(
                    cmd,
                    &self.fel.table_add,
                    &[
                        Bind::Range(self.fel_buffers[F_BP].buffer, c as u64 * quarter, quarter),
                        es,
                        Bind::Range(t, T_CHROMA_MAPPING + c as u64 * 2048, 2048),
                        Bind::Range(t, T_RESIDUAL + (c as u64 + 1) * 4096, 4096),
                        out,
                        err(),
                    ],
                    &[cw, ch, first / 2],
                    (cw.div_ceil(64), rows),
                );
            } else {
                let k = match kind {
                    plan::CHROMA_MMR64_LUT => 0,
                    plan::CHROMA_MMR96 => 1,
                    _ => 2,
                };
                self.dispatch(
                    cmd,
                    &self.fel.mmr_single[k],
                    &[
                        fb(F_G),
                        fb(F_BP),
                        es,
                        Bind::Range(t, T_PARAMS + c as u64 * 384, 384),
                        Bind::Range(t, T_RESIDUAL + (c as u64 + 1) * 4096, 4096),
                        out,
                        Bind::Range(t, T_LUT + c as u64 * 24576, 24576),
                        err(),
                    ],
                    &[cw, ch, first / 2],
                    (cw.div_ceil(64), rows),
                );
            }
        }
    }

    /// reconstruct_impl's direct route for a full-size EL: phase_guide,
    /// luma_equal, phase on each EL chroma channel, then the chroma.
    #[allow(clippy::too_many_arguments)] // as record_fel
    fn record_fel_equal(
        &self,
        cmd: vk::CommandBuffer,
        slot: &Slot,
        p: &Plan,
        bl: &va::SurfaceImport,
        el: &va::SurfaceImport,
        first: u32,
        last: u32,
    ) {
        let (w, h) = (p.width, p.height);
        let (cw, ch) = (w / 2, h / 2);
        let quarter = (cw * ch * 2) as u64;
        let t = slot.tables;
        let fb = |i: usize| Bind::Buffer(self.fel_buffers[i].buffer);
        let err = || Bind::Buffer(slot.error);
        let f = &self.fel;
        let s = self.sampler;
        let rows = (last - first) / 2;
        self.dispatch(
            cmd,
            &f.equal[2],
            &[
                Bind::Sampled(bl.luma.view, s),
                Bind::Sampled(bl.chroma.view, s),
                Bind::Range(t, T_MAPPING, 2048),
                Bind::Range(t, T_RESIDUAL, 4096),
                fb(F_BP),
                fb(F_G),
                err(),
                err(),
            ],
            &[w, h, p.chroma_phase, 0u32, first / 2],
            (cw.div_ceil(16), rows.div_ceil(8)),
        );
        self.dispatch(
            cmd,
            &f.equal[0],
            &[
                Bind::Sampled(bl.luma.view, s),
                Bind::Sampled(el.luma.view, s),
                Bind::Range(t, T_MAPPING, 2048),
                Bind::Range(t, T_RESIDUAL, 4096),
                Bind::Buffer(self.planes[0].buffer),
                fb(F_G),
                err(),
                err(),
            ],
            &[w, h, p.chroma_phase, 0u32, first],
            (w.div_ceil(16), (last - first).div_ceil(8)),
        );
        for c in 0..2u32 {
            self.dispatch(
                cmd,
                &f.equal[1],
                &[
                    Bind::Sampled(el.chroma.view, s),
                    Bind::Sampled(el.chroma.view, s),
                    Bind::Range(t, T_MAPPING, 2048),
                    Bind::Range(t, T_RESIDUAL, 4096),
                    Bind::Range(self.fel_buffers[F_ES].buffer, c as u64 * quarter, quarter),
                    fb(F_G),
                    err(),
                    err(),
                ],
                &[cw, ch, p.chroma_phase, c, first / 2],
                (cw.div_ceil(16), rows.div_ceil(8)),
            );
        }
        gpu::compute_barrier(&self.d, cmd);
        if p.dual != 0 {
            let es = |c: u64| Bind::Range(self.fel_buffers[F_ES].buffer, c * quarter, quarter);
            self.dispatch(
                cmd,
                &f.mmr_dual,
                &[
                    fb(F_G),
                    fb(F_BP),
                    es(0),
                    es(1),
                    Bind::Range(t, T_PARAMS, 768),
                    Bind::Range(t, T_RESIDUAL, 12288),
                    Bind::Buffer(self.planes[1].buffer),
                    Bind::Buffer(self.planes[2].buffer),
                    Bind::Range(t, T_LUT, 49152),
                    fb(F_ES),
                    fb(F_ES),
                    err(),
                ],
                &[cw, ch, 0u32, first / 2],
                ((cw / 4).div_ceil(64), rows),
            );
        } else {
            self.record_chroma(cmd, slot, p, first, last);
        }
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        self.d.require_idle();
        let d = &self.d;
        for (_, s) in self.surfaces.drain() {
            s.destroy(d);
        }
        // The fd dups pin the output dmabufs: close them with the imports.
        for o in self.outputs.drain(..).flatten() {
            o.buffer.destroy(d);
            unsafe { libc::close(o.fd) };
        }
        for c in &self.ring {
            unsafe {
                d.device.destroy_command_pool(c.pool, None);
                for s in c.decode {
                    d.device.destroy_semaphore(s, None);
                }
                d.device.destroy_semaphore(c.done, None);
            }
            c.tables.destroy(d);
            c.packets.destroy(d);
            c.error.destroy(d);
            c.gui_coeff.destroy(d);
            c.gui_error.destroy(d);
            c.map_params.destroy(d);
            c.stats.destroy(d);
            c.bounds_result.destroy(d);
        }
        unsafe { d.device.destroy_semaphore(self.timeline, None) };
        if let Some(r) = self.release {
            unsafe { d.device.destroy_semaphore(r, None) };
        }
        self.shot.destroy(d);
        for p in self.pack_map.values().chain(self.map_bake.iter()).chain(std::iter::once(&self.map_fixup)) {
            p.destroy(d);
        }
        self.map_lut.destroy(d);
        self.map_nodes.destroy(d);
        self.map_cells.destroy(d);
        self.cb1_tiles.destroy(d);
        self.cb1_tiles_pipe.destroy(d);
        for lut in &self.cb1_luts {
            lut.destroy(d);
        }
        self.overlay.destroy(d);
        self.gui_colours.destroy(d);
        for buffer in &self.gui_retired {
            buffer.destroy(d);
        }
        self.gui_tiles.destroy(d);
        self.gui_keys.destroy(d);
        for p in &self.overlay_prepare {
            p.destroy(d);
        }
        unsafe { d.device.destroy_sampler(self.linear, None) };
        self.sources.destroy(d);
        self.ymap.destroy(d);
        for p in &self.planes {
            p.destroy(d);
        }
        self.resize_prepare.destroy(d);
        for p in self.pack.iter().flatten().chain(self.pack_annexb.iter()) {
            p.destroy(d);
        }
        self.single.destroy(d);
        self.fel_chroma.destroy(d);
        for c in &self.ring {
            if let Some(q) = c.query {
                unsafe { d.device.destroy_query_pool(q, None) };
            }
            if let Some(b) = &c.verify {
                b.destroy(d);
            }
        }
        if let Some(v) = &self.verify {
            v.err.destroy(d);
            if let Some((b, _)) = &v.out {
                b.destroy(d);
            }
            v.compare.destroy(d);
        }
        for p in [
            &self.fel.vertical_pair,
            &self.fel.vertical_pair_w32,
            &self.fel.luma_phase_guide,
            &self.fel.phase_vertical_uv,
            &self.fel.mmr_dual_horizontal,
            &self.fel.scale_horizontal,
            &self.fel.table_add,
            &self.fel.mmr_dual,
        ] {
            p.destroy(d);
        }
        for p in self.fel.mmr_single.iter().chain(self.fel.equal.iter()).chain(self.fel.piecewise.iter()) {
            p.destroy(d);
        }
        for b in &self.fel_buffers {
            b.destroy(d);
        }
        unsafe { d.device.destroy_sampler(self.sampler, None) };
    }
}
