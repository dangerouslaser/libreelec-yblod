#include "native_playback_context.h"
#include "native_vaapi_gl_import.h"
#include "native_gpu_preparation.h"
#include "native_gpu_composer_backend.h"
#include "native_gpu_ycc_backend.h"
#include "native_egl_output_bridge.h"
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_vaapi.h>
#include <libavutil/pixfmt.h>
#include <stdlib.h>
#include <string.h>
enum { IDLE=0,VA_PENDING=1,PREP_PENDING=2,COMPOSER_PENDING=3,YCC_PENDING=4,OUTPUT_READY=5 };
struct yb_native_playback_context {
    yb_native_playback_create_info settings;
    EGLContext desktop;
    yb_egl_binding consumer;
    struct yb_vaapi_el_scaler *scaler;
    yb_gpu_preparation *preparation;
    yb_gpu_composer_backend *composer;
    yb_gpu_ycc_backend *ycc;
    yb_vaapi_p010_import *base_import,*el_import;
    yb_egl_output_bridge *bridge;
    AVFrame *base,*el;
    yb_playback_metadata metadata;
    yb_gpu_preparation_output prepared;
    yb_gpu_backend_output reconstructed;
    yb_gpu_ycc_output expanded;
    int state,quarantined,closing;
};
static yb_gpu_proc get_proc(const char *name,void *unused)
{ (void)unused; return (yb_gpu_proc)eglGetProcAddress(name); }
static uintptr_t current_context(void *unused)
{ (void)unused; return (uintptr_t)eglGetCurrentContext(); }
static int snapshot(yb_egl_binding *b)
{
    b->display=(uintptr_t)eglGetCurrentDisplay(); b->context=(uintptr_t)eglGetCurrentContext();
    b->read=(uintptr_t)eglGetCurrentSurface(EGL_READ); b->draw=(uintptr_t)eglGetCurrentSurface(EGL_DRAW);
    b->api=(uint32_t)eglQueryAPI(); return b->display && b->context;
}
static int restore(const yb_egl_binding *b)
{
    return eglBindAPI(b->api) && eglMakeCurrent((EGLDisplay)b->display,
        (EGLSurface)b->draw,(EGLSurface)b->read,(EGLContext)b->context);
}
static int bind_desktop(yb_native_playback_context *p)
{
    return eglBindAPI(EGL_OPENGL_API) && eglMakeCurrent((EGLDisplay)p->settings.egl_display,
        EGL_NO_SURFACE,EGL_NO_SURFACE,p->desktop);
}
static int correct_consumer(const yb_native_playback_context *p,const yb_egl_binding *b)
{
    return b->display==p->consumer.display && b->context==p->consumer.context &&
        b->api==p->consumer.api && b->api==EGL_OPENGL_ES_API;
}
static int finish_call(yb_native_playback_context *p,const yb_egl_binding *saved,int status)
{
    if (!restore(saved)) { p->quarantined=1; return YB_NATIVE_PLAYBACK_QUARANTINED; }
    return status;
}
static int nonzero(const uint8_t token[32])
{ unsigned value=0; for (unsigned i=0;i<32;i++) value |= token[i]; return value!=0; }
static int shader_valid(yb_playback_shader shader)
{ return shader.bytes && shader.size && shader.size<=65536U; }
static int clear_frame(yb_native_playback_context *p)
{
    if (yb_vaapi_p010_import_destroy(&p->base_import) ||
        yb_vaapi_p010_import_destroy(&p->el_import)) return 0;
    av_frame_free(&p->base); av_frame_free(&p->el);
    p->state=IDLE; return 1;
}
int yb_native_playback_create(const yb_native_playback_create_info *info,
    yb_native_playback_context **out)
{
    if (!info || !out || *out || info->version!=1 || !info->egl_display || !info->va_display ||
        yb_vaapi_el_scale_validate(&info->enhancement_scaler) ||
        !shader_valid(info->preparation) || !shader_valid(info->composer) || !shader_valid(info->ycc_expansion) ||
        !nonzero(info->guide_contract_id) || !nonzero(info->phase_contract_id) ||
        !nonzero(info->enhancement_scale_contract_id) || info->base_chroma_location>1 ||
        (info->phase_filter!=1 && info->phase_filter!=2)) return YB_NATIVE_PLAYBACK_ARGUMENT;
    yb_egl_binding saved;
    if (!snapshot(&saved) || saved.display!=info->egl_display || saved.api!=EGL_OPENGL_ES_API)
        return YB_NATIVE_PLAYBACK_ARGUMENT;
    yb_native_playback_context *p=calloc(1,sizeof(*p));
    if (!p) return YB_NATIVE_PLAYBACK_ERROR;
    p->settings=*info; p->consumer=saved;
    const EGLint attrs[]={EGL_SURFACE_TYPE,0,EGL_RENDERABLE_TYPE,EGL_OPENGL_BIT,EGL_NONE};
    const EGLint context[]={EGL_CONTEXT_MAJOR_VERSION_KHR,4,EGL_CONTEXT_MINOR_VERSION_KHR,3,
        EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR,EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR,EGL_NONE};
    EGLConfig config=NULL; EGLint count=0;
    int status=YB_NATIVE_PLAYBACK_FALLBACK;
    if (!eglBindAPI(EGL_OPENGL_API) ||
        !eglChooseConfig((EGLDisplay)info->egl_display,attrs,&config,1,&count) || count!=1) goto fail;
    p->desktop=eglCreateContext((EGLDisplay)info->egl_display,config,EGL_NO_CONTEXT,context);
    if (p->desktop==EGL_NO_CONTEXT || !bind_desktop(p)) goto fail;
    yb_gpu_backend_create_info gpu={1,get_proc,current_context,NULL,
        info->preparation.bytes,info->preparation.size};
    if (yb_gpu_preparation_create(&gpu,&p->preparation)) goto fail;
    gpu.shader_source=info->composer.bytes; gpu.shader_bytes=info->composer.size;
    if (yb_gpu_backend_create(&gpu,&p->composer)) goto fail;
    gpu.shader_source=info->ycc_expansion.bytes; gpu.shader_bytes=info->ycc_expansion.size;
    if (yb_gpu_ycc_create(&gpu,&p->ycc)) goto fail;
    if (yb_vaapi_el_scaler_create(info->va_display,&info->enhancement_scaler,&p->scaler)) goto fail;
    /* Compiled programs own their sources; do not retain caller string pointers. */
    p->settings.preparation=(yb_playback_shader){0};
    p->settings.composer=(yb_playback_shader){0};
    p->settings.ycc_expansion=(yb_playback_shader){0};
    if (!restore(&saved)) { p->quarantined=1; *out=p; return YB_NATIVE_PLAYBACK_QUARANTINED; }
    *out=p; return YB_NATIVE_PLAYBACK_OK;
fail:
    if (p->desktop!=EGL_NO_CONTEXT && !bind_desktop(p)) p->quarantined=1;
    if (!p->quarantined &&
        ((p->preparation && yb_gpu_preparation_destroy(&p->preparation)) ||
         (p->composer && yb_gpu_backend_destroy(&p->composer)) ||
         (p->ycc && yb_gpu_ycc_destroy(&p->ycc)) ||
         (p->scaler && yb_vaapi_el_scaler_destroy(&p->scaler)))) p->quarantined=1;
    if (!restore(&saved)) p->quarantined=1;
    if (!p->quarantined && p->desktop!=EGL_NO_CONTEXT &&
        !eglDestroyContext((EGLDisplay)info->egl_display,p->desktop)) p->quarantined=1;
    if (p->quarantined) { *out=p; return YB_NATIVE_PLAYBACK_QUARANTINED; }
    free(p); return status;
}
static int frame_contract(const yb_native_playback_context *p,const AVFrame *frame,
    VASurfaceID surface,uint32_t width,uint32_t height,uint32_t *allocated_w,uint32_t *allocated_h)
{
    if (!frame || !frame->buf[0] || frame->format!=AV_PIX_FMT_VAAPI || frame->width!=(int)width ||
        frame->height!=(int)height || !frame->hw_frames_ctx || !frame->hw_frames_ctx->data ||
        frame->hw_frames_ctx->size<sizeof(AVHWFramesContext) ||
        (uintptr_t)frame->hw_frames_ctx->data%_Alignof(AVHWFramesContext) ||
        (uintptr_t)frame->data[3]!=(uintptr_t)surface) return 0;
    const AVHWFramesContext *frames=(const AVHWFramesContext *)frame->hw_frames_ctx->data;
    if (frames->format!=AV_PIX_FMT_VAAPI || frames->sw_format!=AV_PIX_FMT_P010LE ||
        !frames->device_ref || !frames->device_ref->data ||
        frames->device_ref->size<sizeof(AVHWDeviceContext) ||
        (uintptr_t)frames->device_ref->data%_Alignof(AVHWDeviceContext) ||
        frames->width<(int)width || frames->height<(int)height || frames->width>8192 || frames->height>8192)
        return 0;
    const AVHWDeviceContext *device=(const AVHWDeviceContext *)frames->device_ref->data;
    if (device->type!=AV_HWDEVICE_TYPE_VAAPI || !device->hwctx ||
        (uintptr_t)device->hwctx%_Alignof(AVVAAPIDeviceContext) ||
        ((const AVVAAPIDeviceContext *)device->hwctx)->display!=p->settings.va_display) return 0;
    *allocated_w=(uint32_t)frames->width; *allocated_h=(uint32_t)frames->height; return 1;
}
static int timebase_matches(AVRational frame,int32_t n,int32_t d)
{
    if (n<=0 || d<=0) return 0;
    if (!frame.num && frame.den>=0) return 1;
    return frame.num>0 && frame.den>0 && (int64_t)frame.num*d==(int64_t)n*frame.den;
}
int yb_native_playback_submit(yb_native_playback_context *p,
    const yb_native_playback_frame *frame,uint64_t timeout)
{
    if (!p || !frame || !timeout || timeout>UINT64_C(5000000000)) return YB_NATIVE_PLAYBACK_ARGUMENT;
    if (p->quarantined) return YB_NATIVE_PLAYBACK_QUARANTINED;
    if (p->closing) return YB_NATIVE_PLAYBACK_ARGUMENT;
    if (p->state!=IDLE) return YB_NATIVE_PLAYBACK_PENDING;
    yb_egl_binding saved;
    if (!snapshot(&saved) || !correct_consumer(p,&saved)) return YB_NATIVE_PLAYBACK_ARGUMENT;
    const yb_playback_frame_descriptor *d=&frame->association;
    uint32_t bw=0,bh=0,ew=0,eh=0;
    if (!frame_contract(p,frame->base_frame,frame->base_surface,frame->base_width,frame->base_height,&bw,&bh) ||
        !frame_contract(p,frame->enhancement_frame,frame->enhancement_surface,frame->enhancement_width,frame->enhancement_height,&ew,&eh) ||
        frame->base_width!=p->settings.enhancement_scaler.output_width ||
        frame->base_height!=p->settings.enhancement_scaler.output_height ||
        frame->enhancement_width!=p->settings.enhancement_scaler.input_width ||
        frame->enhancement_height!=p->settings.enhancement_scaler.input_height ||
        d->width!=frame->base_width || d->height!=frame->base_height ||
        frame->base_frame->chroma_location!=(p->settings.base_chroma_location ? AVCHROMA_LOC_TOPLEFT : AVCHROMA_LOC_LEFT) ||
        frame->enhancement_frame->chroma_location!=AVCHROMA_LOC_TOPLEFT ||
        d->colour_route!=YB_PLAYBACK_COLOUR_INHERITED ||
        frame->base_frame->best_effort_timestamp==AV_NOPTS_VALUE || frame->enhancement_frame->pts==AV_NOPTS_VALUE ||
        d->bl_pts!=frame->base_frame->best_effort_timestamp || d->el_pts!=frame->enhancement_frame->pts ||
        d->bl_timebase_num!=frame->base_packet_timebase_num || d->bl_timebase_den!=frame->base_packet_timebase_den ||
        d->el_timebase_num!=frame->enhancement_packet_timebase_num || d->el_timebase_den!=frame->enhancement_packet_timebase_den ||
        !timebase_matches(frame->base_frame->time_base,d->bl_timebase_num,d->bl_timebase_den) ||
        !timebase_matches(frame->enhancement_frame->time_base,d->el_timebase_num,d->el_timebase_den) ||
        memcmp(d->preparation_id,p->settings.guide_contract_id,32) ||
        memcmp(d->enhancement_scale_id,p->settings.enhancement_scale_contract_id,32)) return YB_NATIVE_PLAYBACK_FALLBACK;
    AVFrameSideData *side=av_frame_get_side_data(frame->base_frame,AV_FRAME_DATA_DOVI_METADATA);
    if (!side || !side->data || !frame->expanded_dovi_side_data || !side->size ||
        side->size>1024U*1024U || side->size!=frame->expanded_dovi_side_data_bytes ||
        memcmp(side->data,frame->expanded_dovi_side_data,side->size)) return YB_NATIVE_PLAYBACK_FALLBACK;
    yb_playback_metadata metadata;
    if (yb_playback_metadata_init(d,side->data,side->size,NULL,&metadata)) return YB_NATIVE_PLAYBACK_FALLBACK;
    p->base=av_frame_clone(frame->base_frame); p->el=av_frame_clone(frame->enhancement_frame);
    if (!p->base || !p->el) { av_frame_free(&p->base); av_frame_free(&p->el); return YB_NATIVE_PLAYBACK_ERROR; }
    p->metadata=metadata;
    int status=yb_vaapi_el_scaler_submit(p->scaler,frame->enhancement_surface,timeout);
    if (status!=YB_VPP_OK) {
        if (status==YB_VPP_QUARANTINED) { p->quarantined=1; return YB_NATIVE_PLAYBACK_QUARANTINED; }
        av_frame_free(&p->base); av_frame_free(&p->el); return YB_NATIVE_PLAYBACK_FALLBACK;
    }
    p->state=VA_PENDING; return YB_NATIVE_PLAYBACK_OK;
}
static int gpu_status(yb_native_playback_context *p,int status,int before_dispatch)
{
    if (status==YB_GPU_BACKEND_PENDING) return YB_NATIVE_PLAYBACK_PENDING;
    if (!status) return YB_NATIVE_PLAYBACK_OK;
    if ((!before_dispatch && status==YB_GPU_BACKEND_FRAME_REJECTED) ||
        (before_dispatch && (status==YB_GPU_BACKEND_ARGUMENT ||
        status==YB_GPU_BACKEND_METADATA || status==YB_GPU_BACKEND_UNSUPPORTED))) {
        /* Rejected completed frame, or pre-dispatch CPU/capability guard.
         * Prior stage is finished; no borrower can still access imports. */
        if (clear_frame(p)) return YB_NATIVE_PLAYBACK_FALLBACK;
    }
    p->quarantined=1; return YB_NATIVE_PLAYBACK_QUARANTINED;
}
int yb_native_playback_finish(yb_native_playback_context *p,uint64_t timeout,yb_native_playback_output *out)
{
    if (!p || !out || !timeout || timeout>UINT64_C(5000000000)) return YB_NATIVE_PLAYBACK_ARGUMENT;
    if (p->quarantined) return YB_NATIVE_PLAYBACK_QUARANTINED;
    if (p->state==IDLE || p->state==OUTPUT_READY || p->closing) return YB_NATIVE_PLAYBACK_ARGUMENT;
    yb_egl_binding saved;
    if (!snapshot(&saved) || !correct_consumer(p,&saved)) return YB_NATIVE_PLAYBACK_ARGUMENT;
    int status=YB_NATIVE_PLAYBACK_OK;
    if (!bind_desktop(p)) { p->quarantined=1; return finish_call(p,&saved,YB_NATIVE_PLAYBACK_QUARANTINED); }
    if (p->state==VA_PENDING) {
        VASurfaceID scaled=VA_INVALID_ID;
        int va=yb_vaapi_el_scaler_finish(p->scaler,timeout,&scaled);
        if (va==YB_VPP_PENDING) return finish_call(p,&saved,YB_NATIVE_PLAYBACK_PENDING);
        if (va!=YB_VPP_OK) goto quarantine;
        uint32_t aw=0,ah=0;
        VASurfaceID base=(VASurfaceID)(uintptr_t)p->base->data[3];
        if (!frame_contract(p,p->base,base,p->metadata.frame.width,p->metadata.frame.height,&aw,&ah)) goto quarantine;
        yb_vaapi_p010_import_info info={p->settings.egl_display,(uintptr_t)p->desktop,
            p->settings.va_display,base,p->metadata.frame.width,p->metadata.frame.height,aw,ah,timeout};
        int imported=yb_vaapi_p010_import_create(&info,&p->base_import);
        if (imported==YB_VA_IMPORT_UNSUPPORTED && clear_frame(p))
            return finish_call(p,&saved,YB_NATIVE_PLAYBACK_FALLBACK);
        if (imported) goto quarantine;
        info.surface=scaled; info.allocation_width=info.width; info.allocation_height=info.height;
        imported=yb_vaapi_p010_import_create(&info,&p->el_import);
        if (imported==YB_VA_IMPORT_UNSUPPORTED && clear_frame(p))
            return finish_call(p,&saved,YB_NATIVE_PLAYBACK_FALLBACK);
        if (imported) goto quarantine;
        yb_gpu_preparation_plan prep={0}; prep.version=1;
        prep.width=info.width; prep.height=info.height;
        prep.bl_luma_texture=yb_vaapi_p010_import_texture(p->base_import,0);
        prep.bl_chroma_texture=yb_vaapi_p010_import_texture(p->base_import,1);
        prep.phase_filter=p->settings.phase_filter; prep.chroma_location=p->settings.base_chroma_location;
        memcpy(prep.frame_id,p->metadata.frame.frame_id,32);
        memcpy(prep.guide_contract_id,p->settings.guide_contract_id,32);
        memcpy(prep.phase_contract_id,p->settings.phase_contract_id,32);
        status=gpu_status(p,yb_gpu_preparation_submit(p->preparation,&prep),1);
        if (status) return finish_call(p,&saved,status);
        p->state=PREP_PENDING;
    }
    if (p->state==PREP_PENDING) {
        status=gpu_status(p,yb_gpu_preparation_finish(p->preparation,timeout,&p->prepared),0);
        if (status) return finish_call(p,&saved,status);
        if (memcmp(p->prepared.frame_id,p->metadata.frame.frame_id,32) ||
            memcmp(p->prepared.guide_contract_id,p->settings.guide_contract_id,32) ||
            memcmp(p->prepared.phase_contract_id,p->settings.phase_contract_id,32)) goto quarantine;
        yb_gpu_backend_plan plan={0}; plan.version=1;
        plan.width=p->metadata.frame.width; plan.height=p->metadata.frame.height;
        plan.input_format=YB_GPU_INPUT_NORMALIZED_P010_WHOLE_GUIDE10;
        plan.enhancement_enabled=1; plan.output_depth=12;
        plan.textures[0]=yb_vaapi_p010_import_texture(p->base_import,0);
        plan.textures[1]=p->prepared.phase_chroma_texture; plan.textures[2]=p->prepared.guide_texture;
        plan.textures[3]=yb_vaapi_p010_import_texture(p->el_import,0);
        plan.textures[4]=yb_vaapi_p010_import_texture(p->el_import,1);
        memcpy(plan.frame_id,p->metadata.frame.frame_id,32); memcpy(plan.guide_frame_id,p->prepared.frame_id,32);
        memcpy(plan.enhancement_frame_id,p->metadata.frame.el_frame_id,32);
        memcpy(plan.guide_contract_id,p->prepared.guide_contract_id,32);
        memcpy(plan.enhancement_scale_contract_id,p->settings.enhancement_scale_contract_id,32);
        plan.mapping=p->metadata.integer.mapping; memcpy(plan.nlq,p->metadata.integer.nlq,sizeof(plan.nlq));
        status=gpu_status(p,yb_gpu_backend_submit(p->composer,&plan),1);
        if (status) return finish_call(p,&saved,status);
        p->state=COMPOSER_PENDING;
    }
    if (p->state==COMPOSER_PENDING) {
        status=gpu_status(p,yb_gpu_backend_finish(p->composer,timeout,&p->reconstructed),0);
        if (status) return finish_call(p,&saved,status);
        if (memcmp(p->reconstructed.frame_id,p->metadata.frame.frame_id,32)) goto quarantine;
        yb_gpu_ycc_plan plan={0}; plan.version=1; plan.width=p->reconstructed.width;
        plan.height=p->reconstructed.height; plan.output_depth=12; plan.sampling_contract=1;
        memcpy(plan.textures,p->reconstructed.textures,sizeof(plan.textures));
        memcpy(plan.frame_id,p->reconstructed.frame_id,32);
        status=gpu_status(p,yb_gpu_ycc_submit(p->ycc,&plan),1);
        if (status) return finish_call(p,&saved,status);
        p->state=YCC_PENDING;
    }
    if (p->state==YCC_PENDING) {
        status=gpu_status(p,yb_gpu_ycc_finish(p->ycc,timeout,&p->expanded),0);
        if (status) return finish_call(p,&saved,status);
        if (memcmp(p->expanded.frame_id,p->metadata.frame.frame_id,32)) goto quarantine;
        /* Bridge create expects the saved GLES consumer current, switches to
         * this producer internally, fences, imports and restores consumer. */
        if (!restore(&saved)) goto quarantine;
        if (yb_egl_output_bridge_create((uintptr_t)p->desktop,p->expanded.texture,&p->bridge)) goto quarantine;
        yb_native_playback_output output={yb_egl_output_bridge_texture(p->bridge),
            p->expanded.width,p->expanded.height,{0}};
        if (!output.texture) goto quarantine;
        memcpy(output.frame_id,p->expanded.frame_id,32);
        status=finish_call(p,&saved,YB_NATIVE_PLAYBACK_OK);
        if (!status) { p->state=OUTPUT_READY; *out=output; }
        return status;
    }
quarantine:
    p->quarantined=1; return finish_call(p,&saved,YB_NATIVE_PLAYBACK_QUARANTINED);
}
int yb_native_playback_release(yb_native_playback_context *p,uint64_t timeout)
{
    if (!p || timeout>UINT64_C(5000000000)) return YB_NATIVE_PLAYBACK_ARGUMENT;
    if (p->quarantined) return YB_NATIVE_PLAYBACK_QUARANTINED;
    if (p->state!=OUTPUT_READY) return YB_NATIVE_PLAYBACK_ARGUMENT;
    yb_egl_binding saved;
    if (!snapshot(&saved) || !correct_consumer(p,&saved)) return YB_NATIVE_PLAYBACK_ARGUMENT;
    /* Kodi must pl_gpu_flush before this call, so queued renderer work is
     * actually submitted and belongs before this consumer fence. */
    int status=yb_egl_output_bridge_release_timed(&p->bridge,timeout);
    if (status==YB_EGL_BRIDGE_CONSUMER) return finish_call(p,&saved,YB_NATIVE_PLAYBACK_PENDING);
    if (status || !bind_desktop(p) || !clear_frame(p)) {
        p->quarantined=1; return finish_call(p,&saved,YB_NATIVE_PLAYBACK_QUARANTINED);
    }
    return finish_call(p,&saved,YB_NATIVE_PLAYBACK_OK);
}
int yb_native_playback_destroy(yb_native_playback_context **handle)
{
    if (!handle) return YB_NATIVE_PLAYBACK_ARGUMENT;
    yb_native_playback_context *p=*handle;
    if (!p) return 0;
    if (p->quarantined) return YB_NATIVE_PLAYBACK_QUARANTINED;
    if (p->state!=IDLE) return YB_NATIVE_PLAYBACK_PENDING;
    yb_egl_binding saved;
    if (!snapshot(&saved) || !correct_consumer(p,&saved)) return YB_NATIVE_PLAYBACK_ARGUMENT;
    p->closing=1;
    if (!bind_desktop(p) || !clear_frame(p) || yb_gpu_preparation_destroy(&p->preparation) ||
        yb_gpu_backend_destroy(&p->composer) || yb_gpu_ycc_destroy(&p->ycc) ||
        yb_vaapi_el_scaler_destroy(&p->scaler)) {
        p->quarantined=1; return finish_call(p,&saved,YB_NATIVE_PLAYBACK_QUARANTINED);
    }
    if (!restore(&saved) || !eglDestroyContext((EGLDisplay)p->settings.egl_display,p->desktop)) {
        p->quarantined=1; return YB_NATIVE_PLAYBACK_QUARANTINED;
    }
    free(p); *handle=NULL; return 0;
}
int yb_native_playback_abandon_after_display_teardown(yb_native_playback_context **handle,uint32_t dead)
{
    if (!handle || dead!=1) return YB_NATIVE_PLAYBACK_ARGUMENT;
    yb_native_playback_context *p=*handle;
    if (!p) return 0;
    /* Live AVFrames keep FFmpeg VA pools/device alive. Freeing those references
     * after forced vaTerminate could invoke callbacks on an invalid display.
     * Initially retain a quarantined decoded transaction until process exit;
     * host-only abandonment is safe solely when no decoded refs were acquired. */
    if (p->base || p->el) return YB_NATIVE_PLAYBACK_QUARANTINED;
    if (p->desktop!=EGL_NO_CONTEXT &&
        (uintptr_t)eglGetCurrentContext()==(uintptr_t)p->desktop) return YB_NATIVE_PLAYBACK_ARGUMENT;
    if ((p->preparation && yb_gpu_preparation_abandon_destroyed_context(&p->preparation,1)) ||
        (p->composer && yb_gpu_backend_abandon_destroyed_context(&p->composer,1)) ||
        (p->ycc && yb_gpu_ycc_abandon_destroyed_context(&p->ycc,1)) ||
        (p->base_import && yb_vaapi_p010_import_abandon_destroyed_display(&p->base_import,1)) ||
        (p->el_import && yb_vaapi_p010_import_abandon_destroyed_display(&p->el_import,1)) ||
        (p->scaler && yb_vaapi_el_scaler_abandon_after_display_teardown(&p->scaler,1))) return YB_NATIVE_PLAYBACK_ERROR;
    if (yb_egl_output_bridge_abandon_destroyed_display(&p->bridge,1)) return YB_NATIVE_PLAYBACK_ERROR;
    av_frame_free(&p->base); av_frame_free(&p->el); free(p); *handle=NULL; return 0;
}
