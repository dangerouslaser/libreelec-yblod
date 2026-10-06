#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
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
#include <time.h>
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
    AVBufferRef *base_render_guard;
    uint32_t base_allocation_width,base_allocation_height;
    void *base_owner_identity;
    void (*base_mark_quarantine)(void *);
    yb_playback_metadata metadata;
    yb_gpu_preparation_output prepared;
    yb_gpu_backend_output reconstructed;
    yb_gpu_ycc_output expanded;
    int state,quarantined,closing;
    yb_native_playback_diagnostics diagnostics;
};
typedef struct { uint64_t ns; int active; } yb_timing_mark;
static int timing_now(uint64_t *out)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC,&ts) || ts.tv_sec<0 || ts.tv_nsec<0 ||
        ts.tv_nsec>=1000000000L || (uint64_t)ts.tv_sec>UINT64_MAX/UINT64_C(1000000000)) return 0;
    uint64_t seconds=(uint64_t)ts.tv_sec*UINT64_C(1000000000);
    if (UINT64_MAX-seconds<(uint64_t)ts.tv_nsec) return 0;
    *out=seconds+(uint64_t)ts.tv_nsec; return 1;
}
static yb_timing_mark timing_begin(yb_native_playback_context *p)
{
    yb_timing_mark mark={0};
    if (!p->diagnostics.enabled || !p->diagnostics.valid) return mark;
    if (!timing_now(&mark.ns)) { p->diagnostics.valid=0; return mark; }
    mark.active=1; return mark;
}
/* outcome0 OK,1 PENDING,2 failed; caller maps each helper's OWN enums. */
static int timing_accumulate(yb_native_playback_stage_stats *entry,uint64_t elapsed,unsigned outcome)
{
    if (!entry || outcome>2 || entry->calls==UINT64_MAX ||
        entry->total_wall_ns>UINT64_MAX-elapsed) return 0;
    uint64_t *counter=outcome==0 ? &entry->ok : outcome==1 ? &entry->pending : &entry->failed;
    if (*counter==UINT64_MAX) return 0;
    entry->calls++; (*counter)++; entry->total_wall_ns+=elapsed;
    if (elapsed>entry->max_wall_ns) entry->max_wall_ns=elapsed;
    return 1;
}
static void timing_end(yb_native_playback_context *p,unsigned stage,yb_timing_mark mark,unsigned outcome)
{
    if (!mark.active) return;
    uint64_t now=0;
    if (!p->diagnostics.valid || stage>=YB_NATIVE_TIMING_STAGE_COUNT ||
        !timing_now(&now) || now<mark.ns ||
        !timing_accumulate(&p->diagnostics.stages[stage],now-mark.ns,outcome)) p->diagnostics.valid=0;
}
static void timing_initialize(yb_native_playback_context *p)
{ if (!p->diagnostics.version) { p->diagnostics.version=1; p->diagnostics.valid=1; } }
static void timing_completed(yb_native_playback_context *p)
{
    if (!p->diagnostics.enabled || !p->diagnostics.valid) return;
    if (p->diagnostics.completed_frames==UINT64_MAX) p->diagnostics.valid=0;
    else p->diagnostics.completed_frames++;
}
int yb_native_playback_diagnostics_enable(yb_native_playback_context *p,int enabled)
{
    if (!p || (enabled!=0 && enabled!=1) || p->state!=IDLE || p->quarantined || p->closing)
        return YB_NATIVE_PLAYBACK_ARGUMENT;
    timing_initialize(p); p->diagnostics.enabled=(uint32_t)enabled; return YB_NATIVE_PLAYBACK_OK;
}
int yb_native_playback_diagnostics_get(const yb_native_playback_context *p,yb_native_playback_diagnostics *out)
{
    if (!p || !out) return YB_NATIVE_PLAYBACK_ARGUMENT;
    yb_native_playback_diagnostics copy=p->diagnostics;
    if (!copy.version) { copy.version=1; copy.valid=1; }
    *out=copy; return YB_NATIVE_PLAYBACK_OK;
}
int yb_native_playback_diagnostics_reset(yb_native_playback_context *p)
{
    if (!p || p->state!=IDLE || p->quarantined || p->closing) return YB_NATIVE_PLAYBACK_ARGUMENT;
    uint32_t enabled=p->diagnostics.enabled;
    memset(&p->diagnostics,0,sizeof(p->diagnostics));
    p->diagnostics.version=1; p->diagnostics.valid=1; p->diagnostics.enabled=enabled;
    return YB_NATIVE_PLAYBACK_OK;
}
#define YB_TIMED_CALL(p,stage,result,call,ok_code,pending_code) do { \
    yb_timing_mark yb_mark=timing_begin(p); \
    (result)=(call); \
    timing_end((p),(stage),yb_mark,(result)==(ok_code)?0U:(result)==(pending_code)?1U:2U); \
} while (0)
#define YB_TIMED_NO_PENDING(p,stage,result,call,ok_code) do { \
    yb_timing_mark yb_mark=timing_begin(p); \
    (result)=(call); \
    timing_end((p),(stage),yb_mark,(result)==(ok_code)?0U:2U); \
} while (0)
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
static void quarantine(yb_native_playback_context *p)
{
    if (p->base_render_guard && p->base_mark_quarantine)
        p->base_mark_quarantine(p->base_owner_identity);
    p->quarantined=1;
}
int yb_native_playback_quarantine_retained(yb_native_playback_context *p)
{
    if (!p) return YB_NATIVE_PLAYBACK_ARGUMENT;
    quarantine(p); return YB_NATIVE_PLAYBACK_QUARANTINED;
}
static int finish_call(yb_native_playback_context *p,const yb_egl_binding *saved,int status)
{
    if (!restore(saved)) { quarantine(p); return YB_NATIVE_PLAYBACK_QUARANTINED; }
    return status;
}
static int nonzero(const uint8_t token[32])
{ unsigned value=0; for (unsigned i=0;i<32;i++) value |= token[i]; return value!=0; }
static int shader_valid(yb_playback_shader shader)
{ return shader.bytes && shader.size && shader.size<=65536U; }
static void release_decoded_refs(yb_native_playback_context *p)
{
    /* Custom BL property snapshot owns no decoded buffers. Free snapshots and
     * strict decoded frames before dropping the actual render-picture lease. */
    av_frame_free(&p->base); av_frame_free(&p->el);
    av_buffer_unref(&p->base_render_guard);
    p->base_owner_identity=NULL; p->base_mark_quarantine=NULL;
    p->base_allocation_width=0; p->base_allocation_height=0;
}
static int clear_frame(yb_native_playback_context *p)
{
    if (yb_vaapi_p010_import_destroy(&p->base_import) ||
        yb_vaapi_p010_import_destroy(&p->el_import)) return 0;
    release_decoded_refs(p);
    p->state=IDLE; return 1;
}
int yb_native_playback_create(const yb_native_playback_create_info *info,
    yb_native_playback_context **out)
{
    if (!info || !out || *out || info->version!=2 || !info->egl_display || !info->va_display ||
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
static int base_contract(const yb_native_playback_context *p,const yb_native_playback_frame *f,
    uint32_t *allocated_w,uint32_t *allocated_h)
{
    const yb_native_kodi_base_surface *k=&f->kodi_base;
    if (f->base_storage==YB_NATIVE_BASE_HWFRAMES) {
        if (k->version || k->fourcc || k->allocation_width || k->allocation_height ||
            k->va_display || k->generation || k->owner_identity || k->render_guard ||
            k->validate || k->mark_quarantine) return 0;
        return frame_contract(p,f->base_frame,f->base_surface,f->base_width,f->base_height,
            allocated_w,allocated_h);
    }
    const AVFrame *frame=f->base_frame;
    if (f->base_storage!=YB_NATIVE_BASE_KODI_SURFACE || k->version!=1 ||
        k->fourcc!=VA_FOURCC_P010 || k->va_display!=p->settings.va_display ||
        !k->generation || !k->owner_identity || !k->render_guard || !k->validate || !k->mark_quarantine ||
        av_buffer_get_opaque(k->render_guard)!=k->owner_identity ||
        !frame || frame->hw_frames_ctx || frame->opaque_ref || frame->opaque ||
        frame->nb_extended_buf || frame->extended_buf ||
        frame->format!=AV_PIX_FMT_VAAPI || !f->base_width || !f->base_height ||
        f->base_width>8192 || f->base_height>8192 ||
        frame->width!=(int)f->base_width || frame->height!=(int)f->base_height ||
        f->base_surface==VA_INVALID_ID ||
        (uintptr_t)frame->data[3]!=(uintptr_t)f->base_surface ||
        k->allocation_width<f->base_width || k->allocation_height<f->base_height ||
        k->allocation_width>8192 || k->allocation_height>8192) return 0;
    for (unsigned i=0;i<AV_NUM_DATA_POINTERS;i++) if (frame->buf[i]) return 0;
    if (k->validate(k->owner_identity,k->va_display,f->base_surface,k->generation,
        k->allocation_width,k->allocation_height)!=1) return 0;
    *allocated_w=k->allocation_width; *allocated_h=k->allocation_height; return 1;
}
static int timebase_matches(AVRational frame,int32_t n,int32_t d)
{
    if (n<=0 || d<=0) return 0;
    if (!frame.num && frame.den>=0) return 1;
    return frame.num>0 && frame.den>0 && (int64_t)frame.num*d==(int64_t)n*frame.den;
}
static AVFrame *copy_kodi_properties(const AVFrame *source)
{
    AVFrameSideData *side=av_frame_get_side_data(source,AV_FRAME_DATA_DOVI_METADATA);
    if (!side || !side->data || !side->size || side->size>1024U*1024U) return NULL;
    AVFrame *copy=av_frame_alloc(); if (!copy) return NULL;
    copy->format=source->format; copy->width=source->width; copy->height=source->height;
    copy->data[3]=source->data[3]; copy->pts=source->pts;
    copy->best_effort_timestamp=source->best_effort_timestamp; copy->time_base=source->time_base;
    copy->chroma_location=source->chroma_location; copy->flags=source->flags;
    copy->color_range=source->color_range; copy->color_primaries=source->color_primaries;
    copy->color_trc=source->color_trc; copy->colorspace=source->colorspace;
    AVFrameSideData *out=av_frame_new_side_data(copy,AV_FRAME_DATA_DOVI_METADATA,side->size);
    if (!out) { av_frame_free(&copy); return NULL; }
    memcpy(out->data,side->data,side->size); return copy;
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
    if (!base_contract(p,frame,&bw,&bh) ||
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
    if (frame->base_storage==YB_NATIVE_BASE_KODI_SURFACE) {
        p->base=copy_kodi_properties(frame->base_frame);
        p->base_render_guard=av_buffer_ref(frame->kodi_base.render_guard);
        p->base_owner_identity=frame->kodi_base.owner_identity;
        p->base_mark_quarantine=frame->kodi_base.mark_quarantine;
    } else p->base=av_frame_clone(frame->base_frame);
    p->el=av_frame_clone(frame->enhancement_frame);
    if (!p->base || !p->el || (frame->base_storage==YB_NATIVE_BASE_KODI_SURFACE && !p->base_render_guard)) {
        release_decoded_refs(p); return YB_NATIVE_PLAYBACK_ERROR;
    }
    p->base_allocation_width=bw; p->base_allocation_height=bh;
    p->metadata=metadata;
    int status;
    YB_TIMED_CALL(p,YB_NATIVE_TIMING_SCALER_SUBMIT,status,
        yb_vaapi_el_scaler_submit(p->scaler,frame->enhancement_surface,timeout),YB_VPP_OK,YB_VPP_PENDING);
    if (status!=YB_VPP_OK) {
        if (status==YB_VPP_QUARANTINED) { quarantine(p); return YB_NATIVE_PLAYBACK_QUARANTINED; }
        release_decoded_refs(p); return YB_NATIVE_PLAYBACK_FALLBACK;
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
    quarantine(p); return YB_NATIVE_PLAYBACK_QUARANTINED;
}
int yb_native_playback_finish(yb_native_playback_context *p,uint64_t timeout,yb_native_playback_output *out)
{
    if (!p || !out || !timeout || timeout>UINT64_C(5000000000)) return YB_NATIVE_PLAYBACK_ARGUMENT;
    if (p->quarantined) return YB_NATIVE_PLAYBACK_QUARANTINED;
    if (p->state==IDLE || p->state==OUTPUT_READY || p->closing) return YB_NATIVE_PLAYBACK_ARGUMENT;
    yb_egl_binding saved;
    if (!snapshot(&saved) || !correct_consumer(p,&saved)) return YB_NATIVE_PLAYBACK_ARGUMENT;
    int status=YB_NATIVE_PLAYBACK_OK;
    if (!bind_desktop(p)) { quarantine(p); return finish_call(p,&saved,YB_NATIVE_PLAYBACK_QUARANTINED); }
    if (p->state==VA_PENDING) {
        VASurfaceID scaled=VA_INVALID_ID;
        int va;
        YB_TIMED_CALL(p,YB_NATIVE_TIMING_VA_WAIT,va,
            yb_vaapi_el_scaler_finish(p->scaler,timeout,&scaled),YB_VPP_OK,YB_VPP_PENDING);
        if (va==YB_VPP_PENDING) return finish_call(p,&saved,YB_NATIVE_PLAYBACK_PENDING);
        if (va!=YB_VPP_OK) goto quarantine;
        uint32_t aw=p->base_allocation_width,ah=p->base_allocation_height;
        VASurfaceID base=(VASurfaceID)(uintptr_t)p->base->data[3];
        if (!aw || !ah) goto quarantine;
        yb_vaapi_p010_import_info info={p->settings.egl_display,(uintptr_t)p->desktop,
            p->settings.va_display,base,p->metadata.frame.width,p->metadata.frame.height,aw,ah,timeout};
        int imported;
        YB_TIMED_NO_PENDING(p,YB_NATIVE_TIMING_IMPORT,imported,
            yb_vaapi_p010_import_create(&info,&p->base_import),YB_VA_IMPORT_OK);
        if (imported==YB_VA_IMPORT_UNSUPPORTED && clear_frame(p))
            return finish_call(p,&saved,YB_NATIVE_PLAYBACK_FALLBACK);
        if (imported) goto quarantine;
        info.surface=scaled; info.allocation_width=info.width; info.allocation_height=info.height;
        YB_TIMED_NO_PENDING(p,YB_NATIVE_TIMING_IMPORT,imported,
            yb_vaapi_p010_import_create(&info,&p->el_import),YB_VA_IMPORT_OK);
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
        YB_TIMED_CALL(p,YB_NATIVE_TIMING_PREPARATION_SUBMIT,status,
            yb_gpu_preparation_submit(p->preparation,&prep),YB_GPU_BACKEND_OK,YB_GPU_BACKEND_PENDING);
        status=gpu_status(p,status,1);
        if (status) return finish_call(p,&saved,status);
        p->state=PREP_PENDING;
    }
    if (p->state==PREP_PENDING) {
        YB_TIMED_CALL(p,YB_NATIVE_TIMING_PREPARATION_WAIT,status,
            yb_gpu_preparation_finish(p->preparation,timeout,&p->prepared),YB_GPU_BACKEND_OK,YB_GPU_BACKEND_PENDING);
        status=gpu_status(p,status,0);
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
        YB_TIMED_CALL(p,YB_NATIVE_TIMING_COMPOSER_SUBMIT,status,
            yb_gpu_backend_submit(p->composer,&plan),YB_GPU_BACKEND_OK,YB_GPU_BACKEND_PENDING);
        status=gpu_status(p,status,1);
        if (status) return finish_call(p,&saved,status);
        p->state=COMPOSER_PENDING;
    }
    if (p->state==COMPOSER_PENDING) {
        YB_TIMED_CALL(p,YB_NATIVE_TIMING_COMPOSER_WAIT,status,
            yb_gpu_backend_finish(p->composer,timeout,&p->reconstructed),YB_GPU_BACKEND_OK,YB_GPU_BACKEND_PENDING);
        status=gpu_status(p,status,0);
        if (status) return finish_call(p,&saved,status);
        if (memcmp(p->reconstructed.frame_id,p->metadata.frame.frame_id,32)) goto quarantine;
        yb_gpu_ycc_plan plan={0}; plan.version=1; plan.width=p->reconstructed.width;
        plan.height=p->reconstructed.height; plan.output_depth=12; plan.sampling_contract=1;
        memcpy(plan.textures,p->reconstructed.textures,sizeof(plan.textures));
        memcpy(plan.frame_id,p->reconstructed.frame_id,32);
        YB_TIMED_CALL(p,YB_NATIVE_TIMING_YCC_SUBMIT,status,
            yb_gpu_ycc_submit(p->ycc,&plan),YB_GPU_BACKEND_OK,YB_GPU_BACKEND_PENDING);
        status=gpu_status(p,status,1);
        if (status) return finish_call(p,&saved,status);
        p->state=YCC_PENDING;
    }
    if (p->state==YCC_PENDING) {
        YB_TIMED_CALL(p,YB_NATIVE_TIMING_YCC_WAIT,status,
            yb_gpu_ycc_finish(p->ycc,timeout,&p->expanded),YB_GPU_BACKEND_OK,YB_GPU_BACKEND_PENDING);
        status=gpu_status(p,status,0);
        if (status) return finish_call(p,&saved,status);
        if (memcmp(p->expanded.frame_id,p->metadata.frame.frame_id,32)) goto quarantine;
        /* Bridge create expects the saved GLES consumer current, switches to
         * this producer internally, fences, imports and restores consumer. */
        if (!restore(&saved)) goto quarantine;
        YB_TIMED_NO_PENDING(p,YB_NATIVE_TIMING_BRIDGE,status,
            yb_egl_output_bridge_create((uintptr_t)p->desktop,p->expanded.texture,&p->bridge),YB_EGL_BRIDGE_OK);
        if (status) goto quarantine;
        yb_native_playback_output output={yb_egl_output_bridge_texture(p->bridge),
            p->expanded.width,p->expanded.height,{0}};
        if (!output.texture) goto quarantine;
        memcpy(output.frame_id,p->expanded.frame_id,32);
        status=finish_call(p,&saved,YB_NATIVE_PLAYBACK_OK);
        if (!status) { p->state=OUTPUT_READY; *out=output; }
        return status;
    }
quarantine:
    quarantine(p); return finish_call(p,&saved,YB_NATIVE_PLAYBACK_QUARANTINED);
}
static int playback_release_impl(yb_native_playback_context *p,uint64_t timeout)
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
        quarantine(p); return finish_call(p,&saved,YB_NATIVE_PLAYBACK_QUARANTINED);
    }
    return finish_call(p,&saved,YB_NATIVE_PLAYBACK_OK);
}
int yb_native_playback_release(yb_native_playback_context *p,uint64_t timeout)
{
    if (!p) return playback_release_impl(p,timeout);
    int status;
    YB_TIMED_CALL(p,YB_NATIVE_TIMING_RELEASE,status,playback_release_impl(p,timeout),
        YB_NATIVE_PLAYBACK_OK,YB_NATIVE_PLAYBACK_PENDING);
    if (status==YB_NATIVE_PLAYBACK_OK) timing_completed(p);
    return status;
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
        quarantine(p); return finish_call(p,&saved,YB_NATIVE_PLAYBACK_QUARANTINED);
    }
    if (!restore(&saved) || !eglDestroyContext((EGLDisplay)p->settings.egl_display,p->desktop)) {
        quarantine(p); return YB_NATIVE_PLAYBACK_QUARANTINED;
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
    if (p->base || p->el || p->base_render_guard) return YB_NATIVE_PLAYBACK_QUARANTINED;
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
