#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include "native_playback_context.c"

struct yb_egl_output_bridge { unsigned slot; };
static uintptr_t active_context=2;
static EGLenum active_api=EGL_OPENGL_ES_API;
static int timeout_slot=-1;
static unsigned frees,unrefs,import_destroys,released[3],waits[3],quarantines;

EGLDisplay EGLAPIENTRY eglGetCurrentDisplay(void){return (EGLDisplay)(uintptr_t)1;}
EGLContext EGLAPIENTRY eglGetCurrentContext(void){return (EGLContext)active_context;}
EGLSurface EGLAPIENTRY eglGetCurrentSurface(EGLint which){(void)which;return EGL_NO_SURFACE;}
EGLenum EGLAPIENTRY eglQueryAPI(void){return active_api;}
EGLBoolean EGLAPIENTRY eglBindAPI(EGLenum api){active_api=api;return EGL_TRUE;}
EGLBoolean EGLAPIENTRY eglMakeCurrent(EGLDisplay display,EGLSurface draw,EGLSurface read,EGLContext context)
{(void)draw;(void)read;assert(display==(EGLDisplay)(uintptr_t)1);active_context=(uintptr_t)context;return EGL_TRUE;}
void av_frame_free(AVFrame **frame){if(*frame){frees++;*frame=NULL;}}
void av_buffer_unref(AVBufferRef **buffer){if(*buffer){unrefs++;*buffer=NULL;}}
int yb_vaapi_p010_import_destroy(yb_vaapi_p010_import **handle)
{import_destroys++;*handle=NULL;return 0;}
int yb_egl_output_bridge_release_timed(yb_egl_output_bridge **handle,uint64_t timeout)
{
    assert(timeout==1000);
    if(!*handle)return YB_EGL_BRIDGE_OK;
    unsigned slot=(*handle)->slot;assert(slot<3);waits[slot]++;
    if((int)slot==timeout_slot){timeout_slot=-1;return YB_EGL_BRIDGE_CONSUMER;}
    released[slot]++;*handle=NULL;return YB_EGL_BRIDGE_OK;
}
static void marked(void *owner){assert(owner==(void *)(uintptr_t)7);quarantines++;}
int main(void)
{
    for(int failing=0;failing<3;failing++){
        struct yb_native_playback_context p={0};
        struct yb_egl_output_bridge bridges[3]={{0},{1},{2}};
        AVFrame base={0},el={0};AVBufferRef guard={0};
        p.state=OUTPUT_READY;p.planar_output=1;
        p.settings.egl_display=1;p.desktop=(EGLContext)(uintptr_t)3;
        p.consumer=(yb_egl_binding){1,2,0,0,EGL_OPENGL_ES_API};
        p.base=&base;p.el=&el;p.base_render_guard=&guard;
        p.base_owner_identity=(void *)(uintptr_t)7;p.base_mark_quarantine=marked;
        p.base_import=(yb_vaapi_p010_import *)(uintptr_t)4;
        p.el_import=(yb_vaapi_p010_import *)(uintptr_t)5;
        for(unsigned i=0;i<3;i++)p.plane_bridges[i]=&bridges[i];
        frees=unrefs=import_destroys=quarantines=0;
        memset(released,0,sizeof(released));memset(waits,0,sizeof(waits));
        timeout_slot=failing;
        assert(playback_release_impl(&p,1000)==YB_NATIVE_PLAYBACK_PENDING);
        assert(p.state==OUTPUT_READY&&!p.quarantined);
        assert(p.base==&base&&p.el==&el&&p.base_render_guard==&guard);
        assert(p.base_import&&p.el_import&&frees==0&&unrefs==0&&import_destroys==0);
        assert(active_context==2&&active_api==EGL_OPENGL_ES_API);
        for(unsigned i=0;i<3;i++){
            assert(released[i]==((int)i<failing?1U:0U));
            assert((p.plane_bridges[i]==NULL)==((int)i<failing));
        }
        assert(playback_release_impl(&p,1000)==YB_NATIVE_PLAYBACK_OK);
        assert(p.state==IDLE&&!p.quarantined&&!p.base&&!p.el&&!p.base_render_guard);
        assert(!p.base_import&&!p.el_import&&frees==2&&unrefs==1&&import_destroys==2);
        assert(active_context==2&&active_api==EGL_OPENGL_ES_API&&quarantines==0);
        for(unsigned i=0;i<3;i++){
            assert(!p.plane_bridges[i]&&released[i]==1);
            assert(waits[i]==((int)i==failing?2U:1U));
        }
    }
    puts("{\"schema\":\"yblod.native-planar-release-host-test.v1\",\"complete\":true,\"actual_release_function\":true,\"timeout_positions_checked\":3,\"decoded_refs_retained_until_all_consumers_complete\":true,\"atomic_planar_publication_tested\":false}");
    return 0;
}
