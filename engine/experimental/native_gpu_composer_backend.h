#ifndef YB_NATIVE_GPU_COMPOSER_BACKEND_H
#define YB_NATIVE_GPU_COMPOSER_BACKEND_H
#include <stddef.h>
#include <stdint.h>
#include "native_composer.h"
#ifdef __cplusplus
extern "C" {
#endif

enum yb_gpu_backend_status {
    YB_GPU_BACKEND_OK=0, YB_GPU_BACKEND_ARGUMENT=1,
    YB_GPU_BACKEND_METADATA=2, YB_GPU_BACKEND_UNSUPPORTED=3,
    YB_GPU_BACKEND_GL_FAILURE=4, YB_GPU_BACKEND_BUSY=5,
    YB_GPU_BACKEND_PENDING=6, YB_GPU_BACKEND_FRAME_REJECTED=7
};
enum { YB_GPU_INPUT_NORMALIZED_P010_WHOLE_GUIDE10=1 };
typedef struct yb_gpu_composer_backend yb_gpu_composer_backend;
typedef void (*yb_gpu_proc)(void);
typedef yb_gpu_proc (*yb_gpu_get_proc)(const char *name,void *opaque);
typedef uintptr_t (*yb_gpu_current_context)(void *opaque);

/* Caller creates/owns a DEDICATED desktop-GL compute context and loader.
 * It must be current for every call. This API clobbers its bindings; it must
 * never run directly in Kodi's borrowed GLES context. Caller owns any EGL
 * switch/restore, imported inputs, synchronization and future output bridge.
 * No display/context creation, file I/O, decoder or hidden CPU fallback.
 */
typedef struct {
    uint32_t version;
    yb_gpu_get_proc get_proc;
    yb_gpu_current_context current_context;
    void *opaque;
    const char *shader_source;
    size_t shader_bytes;
} yb_gpu_backend_create_info;

/* All input objects are borrowed GL_TEXTURE_2D normalized R16/RG16 views.
 * Slots: BL-Y Q6, BL-UV Q6, explicit guide native10 codes, EL-Y Q6, EL-UV Q6.
 * Y dimensions W,H; UV/guide W/2,H/2. No sampling/scaling policy is invented.
 * Frame/preparation tokens are caller assertions, not authentication. The
 * owner supplies explicit nonzero guide/scale contract IDs and matching frame
 * associations, and keeps all inputs/metadata stable through finish().
 * Initial route: enhancement enabled, BL/EL 10-bit whole codes, output10/12.
 */
typedef struct {
    uint32_t version,width,height,input_format;
    int32_t enhancement_enabled,output_depth;
    uint32_t textures[5];
    uint8_t frame_id[32],guide_frame_id[32],enhancement_frame_id[32];
    uint8_t guide_contract_id[32],enhancement_scale_contract_id[32];
    struct yb_mapping_config mapping;
    struct yb_nlq_config nlq[3];
} yb_gpu_backend_plan;

/* Owned output textures remain valid until the next metadata-valid submit
 * attempt/destroy. CPU malformed/width rejection leaves them untouched.
 * R16UI integer reconstructed codes: Y full-size, Cb/Cr half-size; no color
 * conversion, chroma expansion, HDMI or Dolby-conformance claim. Consumers
 * may use them ONLY after finish() returns OK and frame_id matches request.
 * Single output set: caller must also finish/synchronize any previous consumer
 * before another submit can overwrite these images. No hidden frame pool.
 */
typedef struct {
    uint32_t version,width,height,output_depth;
    uint32_t textures[3];
    uint8_t frame_id[32];
} yb_gpu_backend_output;

uint32_t yb_gpu_backend_abi_version(void);
/* Pure CPU guard: malformed metadata wins over valid unsupported width;
 * does not inspect driver objects, touch GL or mutate caller memory. */
int yb_gpu_backend_validate_plan(const yb_gpu_backend_plan *plan);
/* Explicit canonical SSBO wire layout, 419 int64 words. Guarded/atomic: output
 * must be aligned and must not overlap plan. No loader/diagnostic dependency. */
int yb_gpu_backend_pack_metadata(const yb_gpu_backend_plan *,uint32_t component,int64_t words[419]);
int yb_gpu_backend_create(const yb_gpu_backend_create_info *,yb_gpu_composer_backend **);
/* Async: three full-plane dispatches, one frame fence, no readbacks/waits. */
int yb_gpu_backend_submit(yb_gpu_composer_backend *,const yb_gpu_backend_plan *);
/* Finite timeout <=5 seconds; zero polls. PENDING retains all borrowed inputs
 * and prevents reuse/destruction. Reads only frame error flag after completion.
 * Error rejects the entire frame; partial images must never be displayed.
 * Output is unchanged except on OK. */
int yb_gpu_backend_finish(yb_gpu_composer_backend *,uint64_t timeout_ns,yb_gpu_backend_output *);
/* Requires same current context and no pending work; frees only owned GL objects.
 * Pointer retained on failure, with names cleared only after confirmed deletion;
 * a partially closed handle rejects submit and can only retry cleanup or be
 * abandoned after its owner destroys the context. Do not allocate/reuse GL
 * names between failed cleanup and retry. Set NULL only on successful cleanup. */
int yb_gpu_backend_destroy(yb_gpu_composer_backend **);
/* Fatal context-loss/fence-allocation recovery only: caller asserts its old
 * dedicated context was destroyed, and it must no longer be current. No GL
 * calls; driver resource cleanup belongs to context owner. Frees CPU handle. */
int yb_gpu_backend_abandon_destroyed_context(yb_gpu_composer_backend **,uint32_t context_destroyed);

#ifdef __cplusplus
}
#endif
#endif
