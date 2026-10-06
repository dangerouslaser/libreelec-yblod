#ifndef YB_NATIVE_GPU_YCC_BACKEND_H
#define YB_NATIVE_GPU_YCC_BACKEND_H
#include "native_gpu_composer_backend.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct yb_gpu_ycc_backend yb_gpu_ycc_backend;
typedef yb_gpu_backend_create_info yb_gpu_ycc_create_info;
/* Purely explicit reconstructed420 expansion. Dedicated current desktopGL
 * context, loader and lifecycle contract are identical to composer backend.
 * No colour conversion, policy negotiation, EGL switching or hidden copies.
 * Input must be completed depth12 R16UI Y/Cb/Cr, full/half/half dimensions.
 * sampling_contract1 is bilinear-left: x/2,(y-.5)/2 with edge extension.
 * Borrowed inputs remain stable until finish; owner synchronizes consumers
 * before next submit overwrites the one owned RGBA32F output texture. */
typedef struct {
    uint32_t version,width,height,output_depth,sampling_contract;
    uint32_t textures[3];
    uint8_t frame_id[32];
} yb_gpu_ycc_plan;
typedef struct {
    uint32_t version,width,height,output_depth,sampling_contract;
    uint32_t texture;
    uint8_t frame_id[32];
} yb_gpu_ycc_output;
int yb_gpu_ycc_validate_plan(const yb_gpu_ycc_plan *);
int yb_gpu_ycc_create(const yb_gpu_ycc_create_info *,yb_gpu_ycc_backend **);
int yb_gpu_ycc_submit(yb_gpu_ycc_backend *,const yb_gpu_ycc_plan *);
/* Read-only whole-plane 12-bit range validation; no output allocation/write.
 * Same input admission and completion/error fence contract as expansion.
 * Complete with validate_finish, never the texture-producing finish API. */
int yb_gpu_ycc_validate_submit(yb_gpu_ycc_backend *,const yb_gpu_ycc_plan *);
int yb_gpu_ycc_validate_finish(yb_gpu_ycc_backend *,uint64_t);
/* Finite <=5s wait; PENDING preserves input borrow. Reads four-byte error flag
 * after fence. Entire frame rejects on nonzero flag; output changes only OK.
 * RGBA32F contains unrotated Y,Cb,Cr code/4096 and alpha1, no rounded chroma. */
int yb_gpu_ycc_finish(yb_gpu_ycc_backend *,uint64_t,yb_gpu_ycc_output *);
/* Cleanup requires same context and no pending work. On failure handle and
 * undeleted names retained; closing handle only permits cleanup retry or
 * context-abandon. Do not allocate/reuse names between retries. */
int yb_gpu_ycc_destroy(yb_gpu_ycc_backend **);
int yb_gpu_ycc_abandon_destroyed_context(yb_gpu_ycc_backend **,uint32_t);
#ifdef __cplusplus
}
#endif
#endif
