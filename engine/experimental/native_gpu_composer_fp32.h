#ifndef YB_GPU_COMPOSER_FP32_H
#define YB_GPU_COMPOSER_FP32_H
#include "native_gpu_composer_backend.h"
#include "native_gpu_nlq_lut.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct yb_gpu_fp32 yb_gpu_fp32;
enum { YB_GPU_FP32_NLQ_LUT=1, YB_GPU_FP32_IMMUTABLE_INSTRUCTIONS=2 };
typedef struct { uint32_t version,flags,reserved[2]; } yb_gpu_fp32_options;
int yb_gpu_fp32_options_validate(const yb_gpu_fp32_options *);
typedef struct {
    uint64_t accepted_fp32,accepted_integer,cache_hits,cache_misses;
    uint64_t shader_compile_failed,generate_failed;
} yb_gpu_fp32_stats;
typedef struct {
    uint32_t version,enabled;
    uint64_t accepted_frames,metadata_uploads,range_bindings,dispatches;
} yb_gpu_fp32_instruction_stats;
/* Same dedicated-current-GL and borrowed-input contracts as canonical backend.
 * finish() completes only producer work. Before another submit or destroy,
 * caller MUST complete/release all consumers of previous output textures.
 * Two completed topology entries cached; replacement temporarily owns a third.
 * No cached shader compilation on numerical-only coefficient/pivot updates.
 * GL failures retain owned handles for context quarantine; never fallback after
 * a GL-side failure. Generator/unsupported topology may use integer reference.
 */
int yb_gpu_fp32_create(const yb_gpu_backend_create_info *,yb_gpu_fp32 **);
int yb_gpu_fp32_create_ex(const yb_gpu_backend_create_info *,const yb_gpu_fp32_options *,yb_gpu_fp32 **);
int yb_gpu_fp32_submit(yb_gpu_fp32 *,const yb_gpu_backend_plan *);
int yb_gpu_fp32_finish(yb_gpu_fp32 *,uint64_t,yb_gpu_backend_output *);
int yb_gpu_fp32_destroy(yb_gpu_fp32 **);
int yb_gpu_fp32_abandon_destroyed_context(yb_gpu_fp32 **,uint32_t);
/* 1 means latest accepted submit used FP32, 0 means integer fallback. */
int yb_gpu_fp32_selected(const yb_gpu_fp32 *);
int yb_gpu_fp32_get_stats(const yb_gpu_fp32 *,yb_gpu_fp32_stats *);
/* Same-owner-thread snapshot. Caller supplies version1 and exact structure size. */
int yb_gpu_fp32_get_nlq_lut_stats(const yb_gpu_fp32 *,yb_gpu_nlq_lut_stats *,size_t);
/* Same-owner-thread counters of actual accepted FP32 instruction submissions.
 * Caller supplies version1 and exact structure size; no GPU readback. */
int yb_gpu_fp32_get_instruction_stats(const yb_gpu_fp32 *,yb_gpu_fp32_instruction_stats *,size_t);
#ifdef __cplusplus
}
#endif
#endif
