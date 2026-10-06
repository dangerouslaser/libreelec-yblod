#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include "native_playback_context.c"

struct yb_egl_output_bridge { unsigned slot; };
static struct yb_native_playback_context *current;
static struct yb_egl_output_bridge rgba_bridge={3};
static uintptr_t active_context=2;
static EGLenum active_api=EGL_OPENGL_ES_API;
static int timeout_slot=-1,release_error,submit_error,wait_pending,wait_error;
static int association_error,extent_error,bridge_error,zero_texture,restore_error;
static unsigned frees,unrefs,import_destroys,released[4],waits[4],quarantines;
static unsigned submissions,finishes,bridge_creates,checks;

EGLDisplay EGLAPIENTRY eglGetCurrentDisplay(void){return (EGLDisplay)(uintptr_t)1;}
EGLContext EGLAPIENTRY eglGetCurrentContext(void){return (EGLContext)active_context;}
EGLSurface EGLAPIENTRY eglGetCurrentSurface(EGLint which){(void)which;return EGL_NO_SURFACE;}
EGLenum EGLAPIENTRY eglQueryAPI(void){return active_api;}
EGLBoolean EGLAPIENTRY eglBindAPI(EGLenum api){active_api=api;return EGL_TRUE;}
EGLBoolean EGLAPIENTRY eglMakeCurrent(EGLDisplay display,EGLSurface draw,EGLSurface read,EGLContext context)
{
    (void)draw;(void)read;assert(display==(EGLDisplay)(uintptr_t)1);
    if(restore_error&&(uintptr_t)context==2)return EGL_FALSE;
    active_context=(uintptr_t)context;return EGL_TRUE;
}
void av_frame_free(AVFrame **frame){if(*frame){frees++;*frame=NULL;}}
void av_buffer_unref(AVBufferRef **buffer){if(*buffer){unrefs++;*buffer=NULL;}}
int yb_gpu_preparation_destroy(yb_gpu_preparation **handle){(void)handle;assert(0);return 1;}
int yb_gpu_fp32_destroy(yb_gpu_fp32 **handle){(void)handle;assert(0);return 1;}
int yb_gpu_backend_destroy(yb_gpu_composer_backend **handle){(void)handle;assert(0);return 1;}
int yb_gpu_ycc_destroy(yb_gpu_ycc_backend **handle){(void)handle;assert(0);return 1;}
int yb_vaapi_el_scaler_destroy(struct yb_vaapi_el_scaler **handle){(void)handle;assert(0);return 1;}
EGLBoolean EGLAPIENTRY eglDestroyContext(EGLDisplay display,EGLContext context)
{(void)display;(void)context;assert(0);return EGL_FALSE;}
int yb_vaapi_p010_import_destroy(yb_vaapi_p010_import **handle)
{import_destroys++;*handle=NULL;return 0;}
int yb_egl_output_bridge_release_timed(yb_egl_output_bridge **handle,uint64_t timeout)
{
    assert(timeout==1000);
    if(!*handle)return YB_EGL_BRIDGE_OK;
    unsigned slot=(*handle)->slot;assert(slot<4);waits[slot]++;
    if((int)slot==timeout_slot){timeout_slot=-1;return YB_EGL_BRIDGE_CONSUMER;}
    if(release_error)return YB_EGL_BRIDGE_CLEANUP;
    released[slot]++;*handle=NULL;return YB_EGL_BRIDGE_OK;
}
int yb_egl_output_bridge_release_planes_timed(yb_egl_output_bridge *handles[3],uint64_t timeout)
{
    assert(timeout==1000);
    if(timeout_slot>=0){timeout_slot=-1;return YB_EGL_BRIDGE_CONSUMER;}
    if(release_error)return YB_EGL_BRIDGE_CLEANUP;
    for(unsigned i=0;i<3;i++)if(handles[i]){released[i]++;handles[i]=NULL;}
    return YB_EGL_BRIDGE_OK;
}
int yb_gpu_ycc_submit(yb_gpu_ycc_backend *backend,const yb_gpu_ycc_plan *plan)
{
    assert(backend==(yb_gpu_ycc_backend *)(uintptr_t)6&&active_context==3);
    for(unsigned i=0;i<3;i++){assert(!current->plane_bridges[i]);assert(released[i]==1);}
    assert(current->base&&current->el&&current->base_render_guard);
    assert(!frees&&!unrefs&&!import_destroys);
    assert(plan->version==1&&plan->output_depth==12&&plan->sampling_contract==1);
    assert(plan->width==4&&plan->height==4);
    assert(!memcmp(plan->textures,current->reconstructed.textures,sizeof(plan->textures)));
    assert(!memcmp(plan->frame_id,current->reconstructed.frame_id,32));
    submissions++;
    return submit_error?YB_GPU_BACKEND_UNSUPPORTED:YB_GPU_BACKEND_OK;
}
int yb_gpu_ycc_finish(yb_gpu_ycc_backend *backend,uint64_t timeout,yb_gpu_ycc_output *out)
{
    assert(backend==(yb_gpu_ycc_backend *)(uintptr_t)6&&timeout==1000&&active_context==3);
    finishes++;
    if(wait_pending){wait_pending=0;return YB_GPU_BACKEND_PENDING;}
    if(wait_error)return YB_GPU_BACKEND_FRAME_REJECTED;
    memset(out,0,sizeof(*out));out->texture=111;out->width=4;out->height=extent_error?8u:4u;
    memcpy(out->frame_id,current->reconstructed.frame_id,32);
    if(association_error)out->frame_id[0]++;
    return YB_GPU_BACKEND_OK;
}
int yb_egl_output_bridge_create(uintptr_t producer,uint32_t texture,yb_egl_output_bridge **out)
{
    assert(producer==3&&texture==111&&!(*out)&&active_context==2&&active_api==EGL_OPENGL_ES_API);
    bridge_creates++;*out=&rgba_bridge;
    return bridge_error?YB_EGL_BRIDGE_IMPORT:YB_EGL_BRIDGE_OK;
}
uint32_t yb_egl_output_bridge_texture(const yb_egl_output_bridge *bridge)
{assert(bridge==&rgba_bridge);return zero_texture?0u:222u;}
static void marked(void *owner){assert(owner==(void *)(uintptr_t)7);quarantines++;}
static void setup(struct yb_native_playback_context *p,struct yb_egl_output_bridge bridges[3],AVFrame *base,AVFrame *el,AVBufferRef *guard)
{
    memset(p,0,sizeof(*p));p->state=OUTPUT_READY;p->planar_output=1;p->batched_planes=1;
    p->settings.egl_display=1;p->desktop=(EGLContext)(uintptr_t)3;
    p->consumer=(yb_egl_binding){1,2,0,0,EGL_OPENGL_ES_API};
    p->base=base;p->el=el;p->base_render_guard=guard;
    p->base_owner_identity=(void *)(uintptr_t)7;p->base_mark_quarantine=marked;
    p->base_import=(yb_vaapi_p010_import *)(uintptr_t)4;p->el_import=(yb_vaapi_p010_import *)(uintptr_t)5;
    p->ycc=(yb_gpu_ycc_backend *)(uintptr_t)6;
    p->reconstructed.version=1;p->reconstructed.width=p->reconstructed.height=4;
    p->reconstructed.output_depth=12;p->reconstructed.frame_id[0]=42;
    p->metadata.frame.width=p->metadata.frame.height=4;p->metadata.frame.frame_id[0]=42;
    for(unsigned i=0;i<3;i++){bridges[i].slot=i;p->plane_bridges[i]=&bridges[i];p->reconstructed.textures[i]=100+i;}
    current=p;active_context=2;active_api=EGL_OPENGL_ES_API;
    timeout_slot=-1;release_error=submit_error=wait_pending=wait_error=0;
    association_error=extent_error=bridge_error=zero_texture=restore_error=0;
    frees=unrefs=import_destroys=quarantines=submissions=finishes=bridge_creates=0;
    memset(released,0,sizeof(released));memset(waits,0,sizeof(waits));
}
static void retained(const struct yb_native_playback_context *p,const AVFrame *base,const AVFrame *el,const AVBufferRef *guard)
{
    assert(p->base==base&&p->el==el&&p->base_render_guard==guard);
    assert(p->base_import&&p->el_import&&!frees&&!unrefs&&!import_destroys);
    assert(p->reconstructed.textures[0]==100&&p->reconstructed.frame_id[0]==42);
}
static void transition_guards(struct yb_native_playback_context *p)
{
    assert(p->state==PLANAR_RGBA_RELEASING||p->state==PLANAR_RGBA_PENDING);
    int state=p->state;yb_native_playback_context *handle=p;
    assert(yb_native_playback_release(p,1000)==YB_NATIVE_PLAYBACK_ARGUMENT);
    assert(yb_native_playback_destroy(&handle)==YB_NATIVE_PLAYBACK_PENDING&&handle==p);
    assert(p->state==state&&!p->closing&&!p->quarantined&&!frees&&!unrefs&&!import_destroys);
}
int main(void)
{
    for(unsigned fault=0;fault<5;fault++) {
        struct yb_native_playback_context p;struct yb_egl_output_bridge bridges[3];
        AVFrame base={0},el={0};AVBufferRef guard={0};yb_native_playback_output out,sentinel;
        memset(&out,0xa5,sizeof(out));sentinel=out;setup(&p,bridges,&base,&el,&guard);
        uint64_t timeout=1000;
        switch(fault){case 0:p.planar_output=0;break;case 1:p.state=IDLE;break;
          case 2:p.closing=1;break;case 3:timeout=0;break;case 4:p.plane_bridges[2]=NULL;break;}
        assert(yb_native_playback_materialize_rgba(&p,timeout,&out)==YB_NATIVE_PLAYBACK_ARGUMENT);
        assert(!memcmp(&out,&sentinel,sizeof(out))&&!submissions&&!finishes&&!bridge_creates);
        retained(&p,&base,&el,&guard);assert(active_context==2&&active_api==EGL_OPENGL_ES_API);
        checks++;
    }
    for(int fault=-1;fault<3;fault++) {
        struct yb_native_playback_context p;struct yb_egl_output_bridge bridges[3];
        AVFrame base={0},el={0};AVBufferRef guard={0};yb_native_playback_output out,sentinel;
        memset(&out,0xa5,sizeof(out));sentinel=out;setup(&p,bridges,&base,&el,&guard);
        timeout_slot=fault;
        int status=yb_native_playback_materialize_rgba(&p,1000,&out);
        if(fault>=0) {
            assert(status==YB_NATIVE_PLAYBACK_PENDING&&p.state==PLANAR_RGBA_RELEASING&&!p.quarantined);
            assert(!memcmp(&out,&sentinel,sizeof(out))&&!submissions&&!finishes&&!bridge_creates);
            retained(&p,&base,&el,&guard);assert(active_context==2&&active_api==EGL_OPENGL_ES_API);
            transition_guards(&p);
            for(unsigned i=0;i<3;i++)assert(!released[i]&&p.plane_bridges[i]);
            status=yb_native_playback_materialize_rgba(&p,1000,&out);
        }
        assert(status==YB_NATIVE_PLAYBACK_OK&&p.state==OUTPUT_READY&&!p.quarantined&&p.planar_output==1);
        assert(out.texture==222&&out.width==4&&out.height==4&&out.frame_id[0]==42);
        assert(submissions==1&&finishes==1&&bridge_creates==1);
        retained(&p,&base,&el,&guard);assert(active_context==2&&active_api==EGL_OPENGL_ES_API);
        yb_native_playback_output rejected=sentinel;
        assert(yb_native_playback_materialize_rgba(&p,1000,&rejected)==YB_NATIVE_PLAYBACK_ARGUMENT);
        assert(!memcmp(&rejected,&sentinel,sizeof(rejected)));
        assert(playback_release_impl(&p,1000)==YB_NATIVE_PLAYBACK_OK&&p.state==IDLE);
        assert(frees==2&&unrefs==1&&import_destroys==2&&released[3]==1);
        checks++;
    }
    for(unsigned fault=0;fault<8;fault++) {
        struct yb_native_playback_context p;struct yb_egl_output_bridge bridges[3];
        AVFrame base={0},el={0};AVBufferRef guard={0};yb_native_playback_output out,sentinel;
        memset(&out,0xa5,sizeof(out));sentinel=out;setup(&p,bridges,&base,&el,&guard);
        switch(fault){case 0:release_error=1;break;case 1:submit_error=1;break;
          case 2:wait_error=1;break;case 3:association_error=1;break;case 4:extent_error=1;break;
          case 5:bridge_error=1;break;case 6:zero_texture=1;break;case 7:restore_error=1;break;}
        assert(yb_native_playback_materialize_rgba(&p,1000,&out)==YB_NATIVE_PLAYBACK_QUARANTINED);
        assert(p.quarantined&&quarantines&&!memcmp(&out,&sentinel,sizeof(out)));
        retained(&p,&base,&el,&guard);
        if(fault==5||fault==6)assert(p.bridge==&rgba_bridge);
        if(fault!=7)assert(active_context==2&&active_api==EGL_OPENGL_ES_API);
        checks++;
    }
    {
        struct yb_native_playback_context p;struct yb_egl_output_bridge bridges[3];
        AVFrame base={0},el={0};AVBufferRef guard={0};yb_native_playback_output out,sentinel;
        memset(&out,0xa5,sizeof(out));sentinel=out;setup(&p,bridges,&base,&el,&guard);wait_pending=1;
        assert(yb_native_playback_materialize_rgba(&p,1000,&out)==YB_NATIVE_PLAYBACK_PENDING);
        assert(p.state==PLANAR_RGBA_PENDING&&!p.quarantined&&submissions==1&&finishes==1);
        assert(!memcmp(&out,&sentinel,sizeof(out)));retained(&p,&base,&el,&guard);
        transition_guards(&p);
        assert(active_context==2&&active_api==EGL_OPENGL_ES_API);
        assert(yb_native_playback_materialize_rgba(&p,1000,&out)==YB_NATIVE_PLAYBACK_OK);
        assert(submissions==1&&finishes==2&&bridge_creates==1);
        checks++;
    }
    printf("{\"schema\":\"yblod.native-batched-materialize-host-test.v1\",\"complete\":true,\"actual_materialize_function\":true,\"cases\":%u,\"all_planes_retained_on_batch_timeout\":true,\"decoded_refs_retained\":true,\"failed_output_unchanged\":true,\"gpu_execution\":false}\n",checks);
    return 0;
}
