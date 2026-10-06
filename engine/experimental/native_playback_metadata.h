#ifndef YB_NATIVE_PLAYBACK_METADATA_H
#define YB_NATIVE_PLAYBACK_METADATA_H
#include "native_dovi_adapter.h"
#include "native_dovi_colour_adapter.h"
#include "native_gpu_guard.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Live adapter for borrowed decoder-expanded metadata. No blob serialization,
 * hardware allocation, colour processing, frame authentication or GPU dispatch.
 * Backend gets owned copied configurations; metadata may be released after init.
 * Frame/token/preparation declarations must come from actual producer records,
 * not fabricated from dimensions or media filename. This adapter checks equality
 * and syntax, not truth of caller assertions. */
enum { YB_PLAYBACK_COLOUR_INHERITED=1,YB_PLAYBACK_COLOUR_NATIVE=2 };
typedef struct {
    uint32_t version,width,height;
    uint32_t el_scaled_width,el_scaled_height,guide_width,guide_height;
    int64_t bl_pts,el_pts;
    int32_t bl_timebase_num,bl_timebase_den,el_timebase_num,el_timebase_den;
    uint8_t frame_id[32],metadata_frame_id[32],el_frame_id[32];
    uint8_t guide_frame_id[32];
    uint8_t preparation_id[32],guide_preparation_id[32];
    uint8_t enhancement_scale_id[32];
    /* Explicit producer route declarations, not inferred GPU capabilities. */
    uint32_t input_native_depth,input_fractional_bits;
    uint32_t spatial_filter_flag,el_spatial_filter_flag;
    int32_t source_dm_uncompressed;
    uint32_t colour_route;
} yb_playback_frame_descriptor;
typedef struct {
    yb_playback_frame_descriptor frame;
    yb_dovi_integer_instructions integer;
    struct yb_colour_config colour;
    struct yb_gpu_width_report width;
    uint32_t has_native_colour;
} yb_playback_metadata;
enum { YB_PLAYBACK_METADATA_OK=0,YB_PLAYBACK_METADATA_ARGUMENT=1,
       YB_PLAYBACK_METADATA_ASSOCIATION=2,YB_PLAYBACK_METADATA_INTEGER=3,
       YB_PLAYBACK_METADATA_COLOUR=4,YB_PLAYBACK_METADATA_UNSUPPORTED=5,
       YB_PLAYBACK_METADATA_WIDTH=6,YB_PLAYBACK_METADATA_ALIAS=7 };
/* First opt-in subset: even full-raster <=3840x2160, BL/EL native10 whole codes,
 * full-size prepared EL, quarter-size explicit guide, residual-enabled output12.
 * No Q6/fractional quantizer is chosen. Syntax adapters and width validator are
 * real existing C calls. All failures leave output byte-for-byte unchanged.
 * Require matching actual patched FFmpeg headers when compiling dependencies.
 * Colour route is mandatory: INHERITED requires target=NULL and unknown source
 * DM declaration0, leaves colour zero/has_native_colour0 and relies on the
 * existing colour-only renderer. NATIVE requires target and known source DM1,
 * invokes the real colour converter and owns colour/has_native_colour1.
 * No implicit route default or cross-route fallback. Status INTEGER/COLOUR
 * denotes converter rejection; caller retains detailed
 * diagnostics by invoking those converters separately if needed. */
int yb_playback_metadata_init(const yb_playback_frame_descriptor *,
    const void *side_data,size_t bytes,const struct yb_dovi_colour_target *,
    yb_playback_metadata *output);
#ifdef __cplusplus
}
#endif
#endif
