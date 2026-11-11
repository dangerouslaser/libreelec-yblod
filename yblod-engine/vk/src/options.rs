//! The engine's environment settings, read once when an engine is created
//! (never per frame). What ships is the defaults: every variable below is a
//! diagnostic or a comparison switch, none is needed for playback.
//!
//! Diagnostics:
//! - `DVVK_PROFILE=1`: GPU time per pass over 120 frames (and damage stats).
//! - `DVVK_DEADLINE_TRACE=1`: per-frame CPU/GPU deadline JSON (calibrated
//!   timestamps when the device has them).
//! - `DVVK_TRACE=1`: route changes and overlay bypass on stderr.
//! - `DVVK_VERIFY=k`: every k-th frame rendered again by the staged reference
//!   route and compared word by word.
//! - `DVVK_PIPELINE_PROFILE=1`: each pipeline's creation time.
//! - `DVVK_PREPARE_PROGRESS=1`: `DVVK_PREPARE done total` lines on stdout
//!   while pipelines are created (tools/dvvk-prepare, prepare-video).
//! - `DVVK_PREPARE_MAP=1`: the engine also creates every HDR10 and HDR10+
//!   pack variant (tools/dvvk-prepare: they land in the pipeline cache). A
//!   player never sets it: its engine makes the one a frame needs on first
//!   use, from that cache.
//!
//! Behaviour:
//! - `DVVK_GPU_BOOST=0`: never switch AMD to the COMPUTE power profile (power.rs).
//! - `DVVK_DAMAGE=0`: rewrite every output pixel every frame (damage.rs).
//! - `DVVK_SURFACE_CHECK=1`: export each decoded surface from VA every frame
//!   and keep its import only while the dmabuf is the same one, as before
//!   0.1.0-16 (for a caller that can't reset the engine when the decoder's
//!   surface pool changes: Kodi's adapter, LibreELEC's runtime.env).
//! - `DVVK_OVERLAY_PREPARE=1`: the shell's overlay through overlay_prepare's
//!   colour cache instead of fused into the pack (and no native CB1 overlay).
//! - `DVVK_CB1_PAIR_REUSE=0`: CB1's overlay converts each layer per sample
//!   instead of once per pixel pair (the same values).
//! - `DVVK_RESIZE_FMA=0`, `DVVK_BLEND_FMA=0`: uncontracted resize lerps and
//!   overlay blends (yblod's OpenCL build contracts them; for comparisons).
//! - `DVVK_LAZY_RESIZED_PACK=1`: the fused-FEL resized pack variants (three reachable) are
//!   created on first use instead of with the engine.
//! - `DVVK_SUBGROUP=N`, `DVVK_SUBGROUP_OVERRIDES=shader=N,...`: required
//!   compute subgroup sizes, where the device supports them.
//! - `DVVK_DESKTOP_L1=MIN,MAX,AVG`: desktop mode's L1 (12-bit PQ codes, 0 for a
//!   default).
//! - `DVVK_MAP_DIRECT=1`: HDR10 output (dvvk_set_output_mode) computes every
//!   pixel's mapping exactly instead of through the scene's 3D LUT (a check);
//!   `DVVK_MAP_LUT_ONLY=1` the LUT everywhere, no exact cells (timing);
//!   `DVVK_MAP_N=N` the LUT's points per axis (default 65).
//! - `DVVK_MAP_THRESH=C`: the 3D LUT's cells interpolating worse than C output
//!   codes (default 0.5 of a 12-bit code; SDR output 0.35 of an 8-bit one) are
//!   computed exactly; `DVVK_MAP_STATS=1` traces bakes.
//! - `DVVK_MAP_INLINE=1`: HDR10 output's marked LUT cells computed in the
//!   pack instead of map_fixup's pass (a comparison).
//! - `DVVK_HDR10PLUS_TRACE=1`: each dvvk_hdr10plus_packet call prints the
//!   statistics record it used (stderr, JSON; the CPU reference compares it).
//! - `DVVK_OUTPUT=hdr10` / `hdr10plus` / `sdr`: the engine starts in that
//!   output mode (tools without the API, e.g. golden runs of the existing
//!   dvvk-bench); sdr with the default display (203 cd/m2, BT.1886, full range).
//! - `DVVK_PREPARE_SDR=1`: with DVVK_PREPARE_MAP, the SDR pack variants and
//!   SDR's bake and fix-up pipelines as well (tools/dvvk-prepare).
//! - `DVVK_TEST_FAIL` (builds with the `test-faults` feature only): fault.rs.

fn var(name: &str) -> Option<String> {
    std::env::var(name).ok()
}

fn flag(name: &str) -> bool {
    var(name).as_deref() == Some("1")
}

fn not_zero(name: &str) -> bool {
    var(name).as_deref() != Some("0")
}

fn number<T: std::str::FromStr>(name: &str, default: T) -> T {
    var(name).and_then(|v| v.parse().ok()).unwrap_or(default)
}

#[derive(Clone, Debug)]
pub struct EngineOptions {
    pub profile: bool,
    pub deadline_trace: bool,
    pub trace: bool,
    pub verify_every: u64,
    pub pipeline_profile: bool,
    pub prepare_progress: bool,
    pub prepare_map: bool,
    pub gpu_boost: bool,
    pub damage: bool,
    pub surface_check: bool,
    pub overlay_prepare: bool,
    pub cb1_pair_reuse: bool,
    pub resize_fma: u32,
    pub blend_fma: u32,
    pub lazy_resized_pack: bool,
    pub subgroup: u32,
    pub subgroup_overrides: String,
    pub desktop_l1: Option<[u32; 3]>,
    pub map_direct: bool,
    pub map_lut_only: bool,
    /// DVVK_MAP_INLINE=1: the marked cells computed in the pack (no fix-up pass).
    pub map_inline: bool,
    pub map_n: u32,
    /// DVVK_MAP_THRESH (None: the output's default, map::BAKE_THRESH*).
    pub map_thresh: Option<f32>,
    /// DVVK_PREPARE_SDR=1: dvvk-prepare's run also makes SDR's pipelines.
    pub prepare_sdr: bool,
    pub map_stats: bool,
    /// The output mode the engine starts in (crate::map::DVVK_OUTPUT_*).
    pub output_mode: u32,
    /// DVVK_HDR10PLUS_TRACE=1: each dvvk_hdr10plus_packet's statistics record on stderr.
    pub hdr10plus_trace: bool,
}

impl Default for EngineOptions {
    /// What ships: no environment at all.
    fn default() -> Self {
        EngineOptions {
            profile: false,
            deadline_trace: false,
            trace: false,
            verify_every: 0,
            pipeline_profile: false,
            prepare_progress: false,
            prepare_map: false,
            gpu_boost: true,
            damage: true,
            surface_check: false,
            overlay_prepare: false,
            cb1_pair_reuse: true,
            resize_fma: 1,
            blend_fma: 1,
            lazy_resized_pack: false,
            subgroup: 0,
            subgroup_overrides: String::new(),
            desktop_l1: None,
            map_direct: false,
            map_lut_only: false,
            map_inline: false,
            map_n: crate::map::LUT_N,
            map_thresh: None,
            prepare_sdr: false,
            map_stats: false,
            output_mode: crate::map::DVVK_OUTPUT_DV,
            hdr10plus_trace: false,
        }
    }
}

impl EngineOptions {
    pub fn from_env() -> Self {
        let desktop_l1 = var("DVVK_DESKTOP_L1").and_then(|v| {
            let f: Vec<u32> = v.split(',').filter_map(|x| x.trim().parse().ok()).collect();
            (f.len() == 3).then(|| [f[0], f[1], f[2]])
        });
        EngineOptions {
            profile: flag("DVVK_PROFILE"),
            deadline_trace: flag("DVVK_DEADLINE_TRACE"),
            trace: var("DVVK_TRACE").is_some(),
            verify_every: number("DVVK_VERIFY", 0),
            pipeline_profile: flag("DVVK_PIPELINE_PROFILE"),
            prepare_progress: flag("DVVK_PREPARE_PROGRESS"),
            prepare_map: flag("DVVK_PREPARE_MAP"),
            gpu_boost: not_zero("DVVK_GPU_BOOST"),
            damage: not_zero("DVVK_DAMAGE"),
            surface_check: flag("DVVK_SURFACE_CHECK"),
            overlay_prepare: flag("DVVK_OVERLAY_PREPARE"),
            cb1_pair_reuse: not_zero("DVVK_CB1_PAIR_REUSE"),
            resize_fma: number("DVVK_RESIZE_FMA", 1),
            blend_fma: number("DVVK_BLEND_FMA", 1),
            lazy_resized_pack: flag("DVVK_LAZY_RESIZED_PACK"),
            subgroup: number("DVVK_SUBGROUP", 0),
            subgroup_overrides: var("DVVK_SUBGROUP_OVERRIDES").unwrap_or_default(),
            desktop_l1,
            map_direct: flag("DVVK_MAP_DIRECT"),
            map_lut_only: flag("DVVK_MAP_LUT_ONLY"),
            map_inline: flag("DVVK_MAP_INLINE"),
            map_n: number("DVVK_MAP_N", crate::map::LUT_N).clamp(9, 129),
            map_thresh: var("DVVK_MAP_THRESH").and_then(|v| v.parse().ok()),
            prepare_sdr: flag("DVVK_PREPARE_SDR"),
            map_stats: flag("DVVK_MAP_STATS"),
            output_mode: match var("DVVK_OUTPUT").as_deref() {
                Some("hdr10") => crate::map::DVVK_OUTPUT_HDR10,
                Some("hdr10plus") => crate::map::DVVK_OUTPUT_HDR10PLUS,
                Some("sdr") => crate::map::DVVK_OUTPUT_SDR,
                _ => crate::map::DVVK_OUTPUT_DV,
            },
            hdr10plus_trace: var("DVVK_HDR10PLUS_TRACE").as_deref() == Some("1"),
        }
    }
}
