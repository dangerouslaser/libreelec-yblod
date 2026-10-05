#ifndef YB_NATIVE_GPU_GUARD_H
#define YB_NATIVE_GPU_GUARD_H
#include "native_composer.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Width suitability only: not a GPU capability check or dispatch promise. */
struct yb_gpu_width_report {
    uint32_t supported;
    uint32_t mmr_segment_count;
    uint64_t worst_l1_bound;
    int32_t first_unsupported_component;
    int32_t first_unsupported_segment;
};
uint64_t yb_sizeof_gpu_width_report(void);
/* Fully validates mapping first. Invalid metadata leaves output unchanged.
 * Reports all used MMR segments, including those after the first rejection.
 * Caller-owned config/output must be valid, aligned, separate and stable.
 * No automatic fallback or change to the native CPU metadata envelope.
 */
int yb_gpu_check_mapping_width(const struct yb_mapping_config *,
                               struct yb_gpu_width_report *);
#ifdef __cplusplus
}
#endif
#endif
