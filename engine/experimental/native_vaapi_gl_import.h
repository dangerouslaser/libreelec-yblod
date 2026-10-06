#ifndef YB_NATIVE_VAAPI_P010_IMPORT_H
#define YB_NATIVE_VAAPI_P010_IMPORT_H
#include <stdint.h>
#include <va/va.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct yb_vaapi_p010_import yb_vaapi_p010_import;
typedef struct {
    uintptr_t egl_display,desktop_context;
    VADisplay va_display;
    VASurfaceID surface;
    uint32_t width,height;
    uint32_t allocation_width,allocation_height;
    uint64_t producer_timeout_ns;
} yb_vaapi_p010_import_info;
enum { YB_VA_IMPORT_OK=0,YB_VA_IMPORT_ARGUMENT=1,
       YB_VA_IMPORT_UNSUPPORTED=2,YB_VA_IMPORT_DRIVER=3 };
/* Borrowed displays/surface, same dedicated desktop context must be current.
 * Validates actual PRIME_2 P010 two raw layers and their exact advertised
 * modifiers with externalOnly=false; owns two EGLImages/GL_TEXTURE_2D siblings.
 * No VA/EGL display creation/termination, CPU mapping or conversion. Exported
 * FDs closed exactly once after image creation or failure, never unused fields.
 * Export allocation dimensions must match explicit allocation_width/height;
 * normalized textures expose the top-left width/height logical raster (decoder
 * hardware allocations may have aligned padding). No active-area guessing.
 * VA/EGL device association is caller-established; successful import does not
 * authenticate that assertion or prove zero-copy/whole-code contents.
 * *output initially NULL. Non-NULL on error retains partially owned resources.
 * Dedicated bindings may be clobbered; caller handles GLES switch/restoration.
 */
int yb_vaapi_p010_import_create(const yb_vaapi_p010_import_info *,yb_vaapi_p010_import **output);
uint32_t yb_vaapi_p010_import_texture(const yb_vaapi_p010_import *,uint32_t plane);
/* Caller must prove all GL consumers complete before destroy or VA reuse.
 * Same original desktop context current; failed delete retains names for retry.
 * No allocation/name reuse between failed cleanup and retry. */
int yb_vaapi_p010_import_destroy(yb_vaapi_p010_import **);
/* Requires complete original EGL DISPLAY teardown (images are display-owned),
 * not merely context destruction. No EGL/VA calls in abandonment. */
int yb_vaapi_p010_import_abandon_destroyed_display(yb_vaapi_p010_import **,uint32_t);
#ifdef __cplusplus
}
#endif
#endif
