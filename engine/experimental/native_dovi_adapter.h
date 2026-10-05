#ifndef YB_NATIVE_DOVI_ADAPTER_H
#define YB_NATIVE_DOVI_ADAPTER_H
#include <stddef.h>
#include <stdint.h>
#include "native_composer.h"
#ifdef __cplusplus
extern "C" {
#endif

/* Optional FFmpeg boundary, not a dependency of the arithmetic core.
 * Implementation must compile against the actual matching patched dovi_meta.h.
 * Input is decoder-expanded AV_FRAME_DATA_DOVI_METADATA, never raw RPU bytes.
 */
enum yb_dovi_adapter_status {
    YB_DOVI_ADAPTER_OK = 0,
    YB_DOVI_ADAPTER_ARGUMENT = 1,
    YB_DOVI_ADAPTER_LAYOUT = 2,
    YB_DOVI_ADAPTER_UNSUPPORTED_HEADER = 3,
    YB_DOVI_ADAPTER_UNSUPPORTED_MAPPING = 4,
    YB_DOVI_ADAPTER_UNSUPPORTED_NLQ = 5,
    YB_DOVI_ADAPTER_ALIAS = 6,
    YB_DOVI_ADAPTER_UNSUPPORTED_PREPARATION = 7
};

typedef struct {
    uint32_t version;
    int32_t residual_enabled, output_depth;
    /* Declarations only: no filter, phase registration or preparation is run. */
    uint32_t spatial_resampling_filter_flag, el_spatial_resampling_filter_flag;
    uint32_t chroma_resampling_explicit_filter_flag, bl_video_full_range_flag;
    /* These RPU syntax labels are NOT a Dolby stream profile/FEL assertion. */
    uint32_t source_rpu_profile, source_rpu_level;
    struct yb_mapping_config mapping;
    struct yb_nlq_config nlq[3]; /* all zero when residual_enabled == 0 */
} yb_dovi_integer_instructions;

uint32_t yb_dovi_adapter_abi_version(void);
uint64_t yb_dovi_adapter_sizeof_instructions(void);

/* Copy into owned canonical configuration; outputs untouched on every failure.
 * Source must be accessible/coherent/stable for `bytes`, <=1MiB, for this call.
 * No ownership transfer; destination may not alias any source allocation byte.
 * Layout checks precede FFmpeg accessors. We do NOT parse RPU/CRC, recover reuse
 * state, authenticate metadata, infer profile/FEL, pair frames, or prove input
 * sample/geometry/transfer preparation. Caller retains those responsibilities.
 * Initial subset: fixed coefficients, single-region mapping, native8/10,
 * output10/12. Explicit chroma filters are unsupported because their actual
 * tap contract is not represented here. Spatial flags are exported, not ignored.
 * Colour/DM extension semantics are outside this arithmetic translation.
 */
int yb_dovi_to_integer_configs(const void *side_data, size_t bytes,
                               yb_dovi_integer_instructions *output);
#ifdef __cplusplus
}
#endif
#endif
