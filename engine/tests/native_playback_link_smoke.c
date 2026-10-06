/* Real link closure and argument guards only: no EGL/VA/decoder work. */
#include "native_playback_context.h"
#include "native_vaapi_gl_import.h"
#include "native_gpu_preparation.h"
#include "native_gpu_ycc_backend.h"
int main(void)
{
    yb_native_playback_context *context=0;
    yb_vaapi_p010_import *import=0;
    yb_gpu_preparation *preparation=0;
    yb_gpu_ycc_backend *ycc=0;
    if(yb_native_playback_create(0,&context)!=YB_NATIVE_PLAYBACK_ARGUMENT || context)
        return 1;
    if(yb_vaapi_p010_import_create(0,&import)!=YB_VA_IMPORT_ARGUMENT || import)
        return 2;
    if(yb_gpu_preparation_create(0,&preparation)!=YB_GPU_BACKEND_ARGUMENT || preparation)
        return 3;
    if(yb_gpu_ycc_create(0,&ycc)!=YB_GPU_BACKEND_ARGUMENT || ycc)
        return 4;
    return 0;
}
