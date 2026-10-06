#ifndef YB_NATIVE_DOVI_COLOUR_ADAPTER_H
#define YB_NATIVE_DOVI_COLOUR_ADAPTER_H
#include <stddef.h>
#include <stdint.h>
#include "native_colour.h"
#ifdef __cplusplus
extern "C" {
#endif
enum yb_dovi_colour_adapter_status {
    YB_DOVI_COLOUR_OK=0, YB_DOVI_COLOUR_ARGUMENT=1,
    YB_DOVI_COLOUR_LAYOUT=2, YB_DOVI_COLOUR_UNSUPPORTED=3,
    YB_DOVI_COLOUR_SOURCE_SCALE=4, YB_DOVI_COLOUR_TARGET=5,
    YB_DOVI_COLOUR_ALIAS=6
};
/* No target defaults. Matrices row-major; offset uses normalized source units.
 * code_scale must explicitly be4096; PQ policy must be explicitly supported. */
struct yb_dovi_colour_target {
    double ycc[9],offset[3],lms[9];
    int32_t pq_policy,code_scale;
};
uint32_t yb_dovi_colour_adapter_abi_version(void);
/* Matching actual FFmpeg dovi_meta.h required when compiling implementation.
 * Input is decoder-expanded AV_FRAME_DATA_DOVI_METADATA, not raw RPU.
 * Caller must declare known uncompressed source DM (1); side-data itself
 * does not expose compression history. No frame pairing/provenance or TV
 * calibration is inferred. No display-management extension processing.
 * Input allocation<=1MiB, coherent/aligned/stable for this call; caller owns
 * allocation bounds. Output must not overlap either input allocation. On all
 * failures output is byte-for-byte unchanged; success owns copied config. */
int yb_dovi_to_colour_config(const void *side_data,size_t bytes,
                             int32_t source_dm_uncompressed,
                             const struct yb_dovi_colour_target *target,
                             struct yb_colour_config *output);
#ifdef __cplusplus
}
#endif
#endif
