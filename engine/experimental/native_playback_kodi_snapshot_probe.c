/* Synthetic host replay of actual admission/copy/lifetime helpers; no GPU. */
#include "native_playback_context.c"
#include <stdio.h>
static int owner;
static unsigned marks,releases;
static yb_native_playback_context *active;
static int valid(void *o,VADisplay d,VASurfaceID s,uint64_t g,uint32_t w,uint32_t h)
{ return o==&owner && d==(VADisplay)(uintptr_t)1 && s==7 && g==9 && w==80 && h==80; }
static void mark(void *o) { if(o==&owner) marks++; }
static void drop(void *o,uint8_t *data)
{ (void)data; if(o==&owner && active && !active->base && !active->el) releases++; }
static int reject(yb_native_playback_context *p,yb_native_playback_frame *f)
{ uint32_t w=31,h=37; return !base_contract(p,f,&w,&h) && w==31 && h==37; }
int main(void)
{
    yb_native_playback_context p={0}; yb_native_playback_frame f={0}; unsigned checks=0;
    active=&p;
    p.settings.va_display=(VADisplay)(uintptr_t)1;
    AVFrame *src=av_frame_alloc(); if(!src) return 1;
    src->format=AV_PIX_FMT_VAAPI; src->width=64; src->height=64; src->data[3]=(uint8_t *)(uintptr_t)7;
    src->pts=123; src->best_effort_timestamp=124; src->time_base=(AVRational){1,1000};
    src->chroma_location=AVCHROMA_LOC_LEFT; src->color_range=AVCOL_RANGE_MPEG;
    AVFrameSideData *side=av_frame_new_side_data(src,AV_FRAME_DATA_DOVI_METADATA,4);
    if(!side) return 1;
    memset(side->data,42,4);
    AVBufferRef *guard=av_buffer_create(NULL,0,drop,&owner,0); if(!guard) return 1;
    f.base_frame=src; f.base_surface=7; f.base_width=64; f.base_height=64;
    f.base_storage=YB_NATIVE_BASE_KODI_SURFACE;
    f.kodi_base=(yb_native_kodi_base_surface){1,VA_FOURCC_P010,80,80,p.settings.va_display,9,&owner,guard,valid,mark};
#define CHECK(x) do { if(!(x)) return 1; checks++; } while(0)
    uint32_t w=0,h=0; CHECK(base_contract(&p,&f,&w,&h) && w==80 && h==80);
    f.kodi_base.generation=10; CHECK(reject(&p,&f)); f.kodi_base.generation=9;
    f.kodi_base.owner_identity=&p; CHECK(reject(&p,&f)); f.kodi_base.owner_identity=&owner;
    f.kodi_base.render_guard=NULL; CHECK(reject(&p,&f)); f.kodi_base.render_guard=guard;
    f.kodi_base.validate=NULL; CHECK(reject(&p,&f)); f.kodi_base.validate=valid;
    f.kodi_base.mark_quarantine=NULL; CHECK(reject(&p,&f)); f.kodi_base.mark_quarantine=mark;
    f.kodi_base.fourcc=VA_FOURCC_NV12; CHECK(reject(&p,&f)); f.kodi_base.fourcc=VA_FOURCC_P010;
    f.kodi_base.allocation_width=63; CHECK(reject(&p,&f)); f.kodi_base.allocation_width=80;
    f.base_surface=8; CHECK(reject(&p,&f)); f.base_surface=7;
    f.base_storage=2; CHECK(reject(&p,&f)); f.base_storage=1;
    for(unsigned i=0;i<AV_NUM_DATA_POINTERS;i++) {
        src->buf[i]=av_buffer_alloc(1); if(!src->buf[i]) return 1;
        CHECK(reject(&p,&f)); av_buffer_unref(&src->buf[i]);
    }
    src->opaque_ref=av_buffer_alloc(1); if(!src->opaque_ref) return 1;
    CHECK(reject(&p,&f)); av_buffer_unref(&src->opaque_ref);
    src->hw_frames_ctx=av_buffer_alloc(1); if(!src->hw_frames_ctx) return 1;
    CHECK(reject(&p,&f)); av_buffer_unref(&src->hw_frames_ctx);
    src->opaque=&owner; CHECK(reject(&p,&f)); src->opaque=NULL;
    src->nb_extended_buf=1; CHECK(reject(&p,&f)); src->nb_extended_buf=0;
    f.base_storage=0; CHECK(reject(&p,&f)); f.base_storage=1;
    p.base=copy_kodi_properties(src); CHECK(p.base);
    AVFrameSideData *copied=av_frame_get_side_data(p.base,AV_FRAME_DATA_DOVI_METADATA);
    CHECK(copied && copied->data!=side->data && copied->size==4 && copied->data[0]==42);
    CHECK(p.base->pts==123 && p.base->best_effort_timestamp==124 && p.base->time_base.den==1000 &&
        p.base->format==src->format && p.base->data[3]==src->data[3] && !p.base->buf[0] &&
        !p.base->hw_frames_ctx && !p.base->opaque_ref && !p.base->opaque);
    side->data[0]=99; CHECK(copied->data[0]==42);
    p.base_render_guard=av_buffer_ref(guard); p.base_owner_identity=&owner; p.base_mark_quarantine=mark;
    CHECK(p.base_render_guard && av_buffer_get_ref_count(guard)==2);
    av_frame_free(&src); av_buffer_unref(&guard); CHECK(releases==0);
    CHECK(yb_native_playback_quarantine_retained(NULL)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(yb_native_playback_quarantine_retained(&p)==YB_NATIVE_PLAYBACK_QUARANTINED);
    CHECK(marks==1 && p.quarantined && releases==0);
    yb_native_playback_context *handle=&p;
    CHECK(yb_native_playback_abandon_after_display_teardown(&handle,1)==YB_NATIVE_PLAYBACK_QUARANTINED && handle==&p);
    /* Host-only fixture has never submitted hardware work. This is NOT a
     * production quarantine recovery procedure; production retains the lease. */
    release_decoded_refs(&p); CHECK(releases==1 && !p.base && !p.base_render_guard);
    printf("{\"schema\":\"yblod.native-playback-kodi-snapshot-host.v1\",\"checks_passed\":%u,\"gpu_attempted\":false}\n",checks);
    return 0;
}
