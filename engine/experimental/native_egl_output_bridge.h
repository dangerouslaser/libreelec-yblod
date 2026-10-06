#ifndef YB_NATIVE_EGL_OUTPUT_BRIDGE_H
#define YB_NATIVE_EGL_OUTPUT_BRIDGE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Experimental synchronous EGLImage sibling bridge. Handles are borrowed EGL
 * pointers encoded in uintptr_t. Producer texture/context/display must remain
 * alive until release. Caller must invoke on the current GLES consumer thread,
 * with no concurrent producer use; no display termination or context ownership.
 * This copies no pixels and proves neither preservation nor zero-copy. */
typedef struct { uintptr_t display, context, draw, read; uint32_t api; } yb_egl_binding;
typedef struct {
    void *user;
    int (*snapshot)(void *, yb_egl_binding *);
    int (*validate)(void *, const yb_egl_binding *, uintptr_t producer);
    int (*bind)(void *, const yb_egl_binding *);
    int (*wait_current)(void *); /* finite completion wait; never glFinish */
    int (*image_create)(void *, uintptr_t display, uintptr_t producer,
                        uint32_t texture, uintptr_t *image);
    int (*texture_create)(void *, uintptr_t image, uint32_t *texture);
    int (*texture_delete)(void *, uint32_t texture);
    int (*image_delete)(void *, uintptr_t display, uintptr_t image);
} yb_egl_bridge_ops;
typedef struct yb_egl_output_bridge yb_egl_output_bridge;
enum { YB_EGL_BRIDGE_OK=0, YB_EGL_BRIDGE_ARGUMENT=1,
       YB_EGL_BRIDGE_UNSUPPORTED=2, YB_EGL_BRIDGE_PRODUCER=3,
       YB_EGL_BRIDGE_IMPORT=4, YB_EGL_BRIDGE_RESTORE=5,
       YB_EGL_BRIDGE_CONSUMER=6, YB_EGL_BRIDGE_CLEANUP=7 };
/* Native implementation validates desktop GL producer/GLES consumer on the
 * same display, requires surfaceless/image capabilities, fences producer before
 * import and restores original binding. Caller initializes *output=NULL; an
 * already-owned handle is rejected unchanged. A non-NULL
 * handle on error owns resources and must be released (notably restore errors).
 * Never use the returned texture unless status==OK. Width/format semantics and
 * output/frame association require separate caller verification. */
int yb_egl_output_bridge_create(uintptr_t producer_context, uint32_t texture,
                                yb_egl_output_bridge **output);
/* Injected lifecycle adapter for host tests; ops copied, user remains borrowed. */
int yb_egl_output_bridge_create_with_ops(const yb_egl_bridge_ops *,
    uintptr_t producer_context,uint32_t texture,yb_egl_output_bridge **output);
int yb_egl_output_bridge_create_with_timed_ops(const yb_egl_bridge_ops *,
    int (*wait_timed)(void *,uint64_t),uintptr_t producer_context,uint32_t texture,
    yb_egl_output_bridge **output);
uint32_t yb_egl_output_bridge_texture(const yb_egl_output_bridge *);
/* Fence all consumer work before deleting its texture/image. Timeout/failure
 * retains ownership for retry; successful release sets handle NULL. Caller
 * must retain producer storage and must not overwrite it before release. */
int yb_egl_output_bridge_release(yb_egl_output_bridge **);
/* Native bridge: one finite wait <=5s, zero is a poll. Failed wait retains
 * texture/image/handle. Injected bridges require create_with_timed_ops.
 * Caller must flush queued libplacebo work BEFORE fencing the GL consumer. */
int yb_egl_output_bridge_release_timed(yb_egl_output_bridge **,uint64_t timeout_ns);
/* Three siblings share one producer/consumer completion wait. Partial errors
 * retain every allocated handle; none may be sampled unless creation succeeds. */
int yb_egl_output_bridge_create_planes_with_ops(const yb_egl_bridge_ops *,
    int (*wait_timed)(void *,uint64_t),uintptr_t producer,const uint32_t textures[3],
    yb_egl_output_bridge *output[3]);
int yb_egl_output_bridge_create_planes(uintptr_t producer,const uint32_t textures[3],
    yb_egl_output_bridge *output[3]);
int yb_egl_output_bridge_release_planes_timed(yb_egl_output_bridge *handles[3],uint64_t timeout_ns);
/* Fatal recovery only: caller asserts whole original EGLdisplay teardown has
 * invalidated image/contexts/textures, not merely producer-context destruction.
 * Frees host handle without GL/EGL calls. Never use while display remains live. */
int yb_egl_output_bridge_abandon_destroyed_display(yb_egl_output_bridge **,uint32_t);
#ifdef __cplusplus
}
#endif
#endif
