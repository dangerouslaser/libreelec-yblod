#ifndef YB_NATIVE_PLAYBACK_CONTEXT_H
#define YB_NATIVE_PLAYBACK_CONTEXT_H
#include "native_playback_metadata.h"
#include "native_vaapi_el_scaler.h"
#include <stddef.h>
#include <stdint.h>
#include <libavutil/frame.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct yb_native_playback_context yb_native_playback_context;
typedef struct { const char *bytes; size_t size; } yb_playback_shader;
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
} yb_native_playback_frame;
typedef struct {
    uint32_t texture,width,height;
    uint8_t frame_id[32];
    /* GLES TEXTURE_2D, RGBA32F: native reconstructed Y/Cb/Cr 12-bit
     * code values /4096 in RGB, alpha1; NOT RGB colour or native colour output.
     * Feed root colour-only renderer with original paired metadata. */
} yb_native_playback_output;
enum { YB_NATIVE_PLAYBACK_OK=0,YB_NATIVE_PLAYBACK_ARGUMENT=1,
       YB_NATIVE_PLAYBACK_FALLBACK=2,YB_NATIVE_PLAYBACK_PENDING=3,
       YB_NATIVE_PLAYBACK_ERROR=4,YB_NATIVE_PLAYBACK_QUARANTINED=5 };
/* Proposed production orchestration ABI; implementation is in development.
 * All calls on same renderer thread with the same GLES consumer current.
 * Owns a dedicated desktop GL context, never terminates either borrowed display.
 * Saves/restores exact client API/context/draw/read binding on EVERY operation.
 * *output initialized NULL; create compiles supplied public shaders, owns copies
 * of settings, and rejects capability failures before accepting decoder work. */
int yb_native_playback_create(const yb_native_playback_create_info *,
    yb_native_playback_context **output);
/* Clones both actual AVFrames and holds decoded storage through release.
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
