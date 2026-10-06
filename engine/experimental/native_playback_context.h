#ifndef YB_NATIVE_PLAYBACK_CONTEXT_H
#define YB_NATIVE_PLAYBACK_CONTEXT_H
#include "native_playback_metadata.h"
#include "native_vaapi_el_scaler.h"
#include "native_gpu_composer_fp32.h"
#include <stddef.h>
#include <stdint.h>
#include <libavutil/frame.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct yb_native_playback_context yb_native_playback_context;
enum { YB_NATIVE_PLAYBACK_FP32=1,YB_NATIVE_PLAYBACK_NLQ_LUT=2,
       YB_NATIVE_PLAYBACK_PLANAR_OUTPUT=4 };
typedef struct { uint32_t version,flags,reserved[2]; } yb_native_playback_options;
int yb_native_playback_options_validate(const yb_native_playback_options *);
/* CPU-only, same-owner-thread route diagnostics. Zero counters when disabled. */
int yb_native_playback_fp32_selected(const yb_native_playback_context *);
int yb_native_playback_fp32_get_stats(const yb_native_playback_context *,yb_gpu_fp32_stats *);
int yb_native_playback_nlq_lut_get_stats(const yb_native_playback_context *,yb_gpu_nlq_lut_stats *,size_t);
enum {
    YB_NATIVE_TIMING_SCALER_SUBMIT=0,YB_NATIVE_TIMING_VA_WAIT,
    YB_NATIVE_TIMING_IMPORT,YB_NATIVE_TIMING_PREPARATION_SUBMIT,
    YB_NATIVE_TIMING_PREPARATION_WAIT,YB_NATIVE_TIMING_COMPOSER_SUBMIT,
    YB_NATIVE_TIMING_COMPOSER_WAIT,YB_NATIVE_TIMING_YCC_SUBMIT,
    YB_NATIVE_TIMING_YCC_WAIT,YB_NATIVE_TIMING_BRIDGE,
    YB_NATIVE_TIMING_RELEASE,YB_NATIVE_TIMING_STAGE_COUNT
};
typedef struct {
    uint64_t calls,ok,pending,failed,total_wall_ns,max_wall_ns;
} yb_native_playback_stage_stats;
typedef struct {
    uint32_t version,enabled,valid;
    uint64_t completed_frames;
    yb_native_playback_stage_stats stages[YB_NATIVE_TIMING_STAGE_COUNT];
} yb_native_playback_diagnostics;
/* Optional host-wall instrumentation, disabled by default (no clock reads).
 * Same owner thread as context operations; NOT atomic or thread-safe reads.
 * Stage totals include OK/PENDING/failed API attempts; imports count BL and EL
 * separately in one bucket. Average API call=total_wall_ns/calls, NOT per-frame
 * or pure GPU/kernel time. The release bucket covers the complete release call
 * including consumer wait/cleanup/context restoration; other buckets cover the
 * named helper calls only. completed_frames counts successful consumer release.
 * Clock/counter failures invalidate stats ONLY, never playback behavior.
 * enable/reset require IDLE and a nonclosing/nonquarantined context. get copies
 * to output only on success; may inspect quarantined retained diagnostics.
 * No EGL/VA work or changes to create/frame ABI2 layouts. */
int yb_native_playback_diagnostics_enable(yb_native_playback_context *,int enabled);
int yb_native_playback_diagnostics_get(const yb_native_playback_context *,yb_native_playback_diagnostics *);
int yb_native_playback_diagnostics_reset(yb_native_playback_context *);
typedef struct { const char *bytes; size_t size; } yb_playback_shader;
/* Explicit nonowning property snapshot of Kodi's decoded BL. No decoder buffer
 * refs or fabricated HWFramesContext. The genuine render-picture token owns
 * storage; its callbacks validate an immutable pool generation under Gfx and
 * mark that pool quarantined before any uncertain work returns to its owner. */
typedef struct {
    uint32_t version,fourcc,allocation_width,allocation_height;
    VADisplay va_display;
    uint64_t generation;
    void *owner_identity;
    AVBufferRef *render_guard;
    int (*validate)(void *,VADisplay,VASurfaceID,uint64_t,uint32_t,uint32_t);
    void (*mark_quarantine)(void *);
} yb_native_kodi_base_surface;
enum { YB_NATIVE_BASE_HWFRAMES=0,YB_NATIVE_BASE_KODI_SURFACE=1 };
typedef struct {
    uint32_t version;
    uintptr_t egl_display; /* borrowed, same as current GLES renderer */
    VADisplay va_display;  /* borrowed, matching imported decoder surfaces */
    struct yb_vaapi_el_scale_config enhancement_scaler;
    yb_playback_shader preparation,composer,ycc_expansion;
    uint8_t guide_contract_id[32],enhancement_scale_contract_id[32];
    uint8_t phase_contract_id[32];
    uint32_t base_chroma_location,phase_filter;
} yb_native_playback_create_info;
typedef struct {
    yb_playback_frame_descriptor association;
    const AVFrame *base_frame,*enhancement_frame;
    int32_t base_packet_timebase_num,base_packet_timebase_den;
    int32_t enhancement_packet_timebase_num,enhancement_packet_timebase_den;
    /* Actual procPic IDs retained separately: base_frame->data[3] must match
     * base_surface, likewise EL, otherwise reject (postprocessed BL ambiguity).
     * Context clones accepted actual AVFrames, holding decoder storage refs. */
    VASurfaceID base_surface,enhancement_surface;
    uint32_t base_width,base_height,enhancement_width,enhancement_height;
    const void *expanded_dovi_side_data;
    size_t expanded_dovi_side_data_bytes;
    /* Zero-initialized default preserves strict FFmpeg HWFrames admission.
     * Custom route is BL only; EL still requires a genuine HWFramesContext. */
    uint32_t base_storage;
    yb_native_kodi_base_surface kodi_base;
} yb_native_playback_frame;
typedef struct {
    uint32_t texture,width,height;
    uint8_t frame_id[32];
    /* GLES TEXTURE_2D, RGBA32F: native reconstructed Y/Cb/Cr 12-bit
     * code values /4096 in RGB, alpha1; NOT RGB colour or native colour output.
     * Feed root colour-only renderer with original paired metadata. */
} yb_native_playback_output;
typedef struct {
    uint32_t version,textures[3],width,height,output_depth,sampling_contract;
    uint8_t frame_id[32];
    /* Borrowed GLES TEXTURE_2D R16UI Y/Cb/Cr, native 4:2:0 12-bit codes.
     * All three siblings belong to one completed, validated frame. Hold them
     * until release; sampling_contract1 preserves the existing YCC expansion. */
} yb_native_playback_planar_output;
/* Additive opt-in API; requires PLANAR_OUTPUT and output->version1. The
 * existing float-output API/layout is unchanged. No output mutation on error. */
int yb_native_playback_finish_planar(yb_native_playback_context *,uint64_t,
    yb_native_playback_planar_output *);
enum { YB_NATIVE_PLAYBACK_OK=0,YB_NATIVE_PLAYBACK_ARGUMENT=1,
       YB_NATIVE_PLAYBACK_FALLBACK=2,YB_NATIVE_PLAYBACK_PENDING=3,
       YB_NATIVE_PLAYBACK_ERROR=4,YB_NATIVE_PLAYBACK_QUARANTINED=5 };
/* Production orchestration ABI version2; create rejects version1 callers.
 * All calls on same renderer thread with the same GLES consumer current.
 * Owns a dedicated desktop GL context, never terminates either borrowed display.
 * Saves/restores exact client API/context/draw/read binding on EVERY operation.
 * *output initialized NULL; create compiles supplied public shaders, owns copies
 * of settings, and rejects capability failures before accepting decoder work. */
int yb_native_playback_create(const yb_native_playback_create_info *,
    yb_native_playback_context **output);
/* Explicit options; LUT requires FP32. Legacy create retains its existing flag. */
int yb_native_playback_create_ex(const yb_native_playback_create_info *,
    const yb_native_playback_options *,yb_native_playback_context **output);
/* Strict route clones actual HWFrames. Custom Kodi BL copies only declared
 * public properties and DOVI bytes; a genuine render-picture lease owns storage.
 * BL best_effort_timestamp and EL pts must match descriptor and each other
 * using the explicit actual decoder packet time bases; no double Kodi doviPts.
 * A present AVFrame.time_base must be consistent; an absent redundant frame
 * time base does not override valid explicitly supplied producer information.
 * Metadata/configurations copied on
 * acceptance; descriptor uses actual matching
 * BL/EL PTS, metadata/frame IDs and explicit preparation contract IDs.
 * Initially P010 native10 whole enhancement-enabled / INHERITED colour only.
 * Reject fractional/Y416, MEL/disabled, invalid or wide64 metadata: no quantizer.
 * FALLBACK guarantees no outstanding helper work or claimed output for frame;
 * caller may use existing path. QUARANTINED forbids recycling borrowed refs. */
int yb_native_playback_submit(yb_native_playback_context *,
    const yb_native_playback_frame *,uint64_t producer_timeout_ns);
/* Runs finite VA-output/preparation/composer/producer fences (each<=5seconds),
 * imports a sibling EGLImage into saved GLES consumer only after full-frame
 * error flags clear. Atomic output: unchanged on failure, no partial frames.
 * Texture remains owned and valid until successful release. No new submission
 * while an output is outstanding. Not an asynchronous deadline guarantee. */
int yb_native_playback_finish(yb_native_playback_context *,
    uint64_t stage_timeout_ns,yb_native_playback_output *output);
/* Finite GLES consumer fence before deleting sibling/imports or allowing source
 * reuse. Failure retains resources for retry; success releases frame references.
 * Caller has to retain decoded refs until this returns OK (conservative lifetime). */
int yb_native_playback_release(yb_native_playback_context *,uint64_t consumer_timeout_ns);
int yb_native_playback_destroy(yb_native_playback_context **);
/* Owner permanently abandons normal retries (including PENDING destroy).
 * Host-only: no EGL/VA calls; marks the actual pool lease quarantined and
 * retains EVERY resource. Must be called before owner teardown/reuse decisions.
 * This is not recovery or permission to destroy the borrowed displays. */
int yb_native_playback_quarantine_retained(yb_native_playback_context *);
/* Quarantine: only after owner completes BOTH borrowed VA/EGL displays/device
 * teardown and invalidates all storage/contexts; host-only abandonment.
 * This initially REJECTS if decoded AVFrame clones remain: their pool/device
 * callbacks cannot safely run after forced display teardown. Retain that
 * quarantined transaction until process exit, not in-process VA reuse. */
int yb_native_playback_abandon_after_display_teardown(
    yb_native_playback_context **,uint32_t teardown_complete);
#ifdef __cplusplus
}
#endif
#endif
