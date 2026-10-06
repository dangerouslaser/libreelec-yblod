#ifndef YB_NATIVE_GPU_NLQ_LUT_H
#define YB_NATIVE_GPU_NLQ_LUT_H
#include "native_composer.h"
#include <stddef.h>
enum { YB_GPU_NLQ_LUT_CODES=1024, YB_GPU_NLQ_LUT_ENTRIES=3072 };
#define YB_GPU_NLQ_LUT_SHADER_MARKER "#define YB_GPU_NLQ_LUT 1\n"
typedef struct {
    uint32_t version,enabled;
    uint64_t shader_compiles,builds,cache_hits,uploads,accepted_frames;
} yb_gpu_nlq_lut_stats;
#ifdef __cplusplus
extern "C" {
#endif
int yb_gpu_nlq_lut_build(const struct yb_nlq_config configs[3],int32_t out[YB_GPU_NLQ_LUT_ENTRIES]);
int yb_gpu_nlq_lut_configs_equal(const struct yb_nlq_config a[3],const struct yb_nlq_config b[3]);
/* No trailing NUL is required; only the pinned NLQ block is replaced. */
int yb_gpu_nlq_lut_shader_patch(const char *source,size_t bytes,char **out,size_t *out_bytes);
int yb_gpu_nlq_lut_shader_has_marker(const char *source,size_t bytes);
#ifdef __cplusplus
}
#endif
#endif
