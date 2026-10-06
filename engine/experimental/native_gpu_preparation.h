#ifndef YB_NATIVE_GPU_PREPARATION_H
#define YB_NATIVE_GPU_PREPARATION_H
#include "native_gpu_composer_backend.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct yb_gpu_preparation yb_gpu_preparation;
enum { YB_GPU_PREPARATION_ABI=1, YB_GPU_PHASE_LINEAR=1, YB_GPU_PHASE_CUBIC128=2 };
/* Same dedicated desktop-current-context and callback contract as composer.
 * No EGL ownership, file IO, scaling, metadata inference or CPU fallback.
 * Shader bytes must be the explicit guide/phase kernel selected by owner. */
typedef yb_gpu_backend_create_info yb_gpu_preparation_create_info;
typedef struct {
    uint32_t version,width,height;
    uint32_t bl_luma_texture,bl_chroma_texture;
    uint32_t phase_filter,chroma_location;
    uint8_t frame_id[32],guide_contract_id[32],phase_contract_id[32];
} yb_gpu_preparation_plan;
/* Borrowed inputs: normalized R16 BL-Y Q6 W×H and RG16 BL-UV Q6 W/2×H/2.
 * Chroma location 0=left,1=top-left; phase filter explicitly linear/cubic128.
 * IDs must be nonzero, supplied by caller; associations are assertions.
 * Retain inputs until successful finish or destroyed-context abandonment. */
typedef struct {
    uint32_t version,width,height;
    uint32_t guide_texture,phase_chroma_texture;
    uint32_t phase_below_zero,phase_above_native;
    uint8_t frame_id[32],guide_contract_id[32],phase_contract_id[32];
} yb_gpu_preparation_output;
/* Owned outputs: guide R16 native10 codes, phase RG16 P010 Q6 words.
 * Valid until next valid submit/destroy; consumers must finish before reuse.
 * Partial outputs from error must never feed composer or be displayed. */
int yb_gpu_preparation_validate_plan(const yb_gpu_preparation_plan *);
int yb_gpu_preparation_create(const yb_gpu_preparation_create_info *,yb_gpu_preparation **);
int yb_gpu_preparation_submit(yb_gpu_preparation *,const yb_gpu_preparation_plan *);
/* <=5s finite fence wait; pending retains input ownership. Output atomic.
 * Only 3 status words read back, never full planes. Uses backend status enum. */
int yb_gpu_preparation_finish(yb_gpu_preparation *,uint64_t timeout_ns,yb_gpu_preparation_output *);
int yb_gpu_preparation_destroy(yb_gpu_preparation **);
int yb_gpu_preparation_abandon_destroyed_context(yb_gpu_preparation **,uint32_t);
#ifdef __cplusplus
}
#endif
#endif
