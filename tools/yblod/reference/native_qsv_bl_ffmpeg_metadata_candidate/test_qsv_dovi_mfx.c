/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Actual qsv_decode function; only MFX submission/completion is scripted. */
#define ff_hevc_qsv_decoder fixture_hevc_qsv_decoder
#define av_gettime_relative fixture_gettime_relative
#include "qsvdec.c"
#include <assert.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/wait.h>

enum { PARTIAL, COMPLETE, BUFFER_ONLY, ZERO_CONSUME, UNKNOWN_OUTPUT, PREPARED_OUTPUT, DRAIN_EMPTY,
       INVALID_OFFSET, PARAM_WARNING, BUSY_FOREVER, SURFACE_FOREVER, BUSY_THEN_SUCCESS };
static int behavior, calls;
static uint64_t returned_token;
static uint64_t observed[128];
static mfxFrameSurface1 *sync_surfaces[128];
static uint64_t sync_tokens[128];
static int done, closes, buffer_eagain, sync_calls, frame_frees;
static mfxStatus sync_status=MFX_ERR_NONE, close_status=MFX_ERR_NONE;
static int64_t fixture_clock, fixture_clock_step;
static int busy_remaining;
int64_t fixture_gettime_relative(void) { fixture_clock+=fixture_clock_step; return fixture_clock; }

static void frame_drop(void *opaque, uint8_t *data) { ++frame_frees; av_free(data); }

int __wrap_ff_decode_frame_props(AVCodecContext *avctx, AVFrame *frame)
{
    frame->format=avctx->pix_fmt;
    return 0;
}
int __wrap_ff_attach_decode_data(AVCodecContext *avctx, AVFrame *frame) { return 0; }
int __wrap_ff_get_buffer(AVCodecContext *avctx, AVFrame *frame, int flags)
{
    if (buffer_eagain) {
        buffer_eagain=0;
        return AVERROR(EAGAIN);
    }
    frame->format=AV_PIX_FMT_QSV;
    frame->width=frame->height=4;
    uint8_t *data=av_mallocz(sizeof(mfxFrameSurface1));
    if (!data) return AVERROR(ENOMEM);
    frame->buf[0]=av_buffer_create(data,sizeof(mfxFrameSurface1),frame_drop,NULL,0);
    if (!frame->buf[0]) av_free(data);
    if (!frame->buf[0]) return AVERROR(ENOMEM);
    frame->data[3]=frame->buf[0]->data;
    return 0;
}

mfxStatus MFXVideoDECODE_DecodeFrameAsync(mfxSession session, mfxBitstream *bs,
                                        mfxFrameSurface1 *in, mfxFrameSurface1 **out,
                                        mfxSyncPoint *sync)
{
    assert(session);
    if (!bs) { *sync=NULL; assert(behavior==DRAIN_EMPTY); return MFX_ERR_MORE_DATA; }
    observed[calls++]=bs->TimeStamp;
    *sync=NULL;
    if (behavior==BUSY_FOREVER || behavior==SURFACE_FOREVER ||
        (behavior==BUSY_THEN_SUCCESS && busy_remaining-- > 0)) {
        if (behavior==SURFACE_FOREVER) in->Data.Locked=1;
        return behavior!=SURFACE_FOREVER ? MFX_WRN_DEVICE_BUSY : MFX_ERR_MORE_SURFACE;
    }
    if (behavior == ZERO_CONSUME)
        return MFX_ERR_MORE_DATA;
    bs->DataOffset = behavior == INVALID_OFFSET ? bs->DataLength + 1 :
                     behavior == PARTIAL || behavior == PREPARED_OUTPUT ? 2 : bs->DataLength;
    bs->DataLength -= bs->DataOffset;
    if (behavior == PARTIAL || behavior == BUFFER_ONLY)
        return MFX_ERR_MORE_DATA;
    in->Data.TimeStamp = MFX_TIMESTAMP_UNKNOWN;
    sync_surfaces[calls]=in;
    sync_tokens[calls]=behavior == UNKNOWN_OUTPUT ? 999 : returned_token ? returned_token : bs->TimeStamp;
    *out=in; *sync=(mfxSyncPoint)(uintptr_t)calls;
    return behavior == PARAM_WARNING ? MFX_WRN_VIDEO_PARAM_CHANGED : MFX_ERR_NONE;
}
mfxStatus MFXVideoCORE_SyncOperation(mfxSession session, mfxSyncPoint sync, mfxU32 wait)
{
    assert(session && sync); ++sync_calls;
    if (sync_status==MFX_ERR_NONE) {
        unsigned index=(uintptr_t)sync; assert(index<128 && sync_surfaces[index]);
        sync_surfaces[index]->Data.TimeStamp=sync_tokens[index];
    }
    return sync_status;
}
mfxStatus MFXVideoDECODE_Close(mfxSession session) { ++closes; return close_status; }

static void setup(QSVContext *q, AVCodecContext *avctx)
{
    *q=(QSVContext){0}; *avctx=(AVCodecContext){0};
    q->dovi_metadata=1; q->async_depth=1; q->session=(mfxSession)(uintptr_t)1;
    q->frame_info=(mfxFrameInfo){.FourCC=MFX_FOURCC_NV12,.Width=128,.Height=64,
                               .CropW=4,.CropH=4,.PicStruct=MFX_PICSTRUCT_PROGRESSIVE};
    q->async_fifo=av_fifo_alloc2(1,sizeof(QSVAsyncFrame),0); assert(q->async_fifo);
    q->initialized=1; q->orig_pix_fmt=AV_PIX_FMT_P010;
    avctx->pix_fmt=AV_PIX_FMT_QSV; avctx->sw_pix_fmt=AV_PIX_FMT_P010;
    avctx->coded_width=4; avctx->coded_height=4;
    avctx->field_order=AV_FIELD_PROGRESSIVE; avctx->codec_id=AV_CODEC_ID_HEVC;
    avctx->pkt_timebase=(AVRational){1,1000000}; returned_token=0;
}
static void cleanup(QSVContext *q)
{
    /* Fake session is not an internally-owned dispatcher session. */
    qsv_decode_close_qsvcontext(q); qsv_dovi_uninit(&q->dovi);
}
static QSVDecContext *init_decoder(QSVDecContext *s, AVCodecContext *avctx)
{
    *s=(QSVDecContext){0}; *avctx=(AVCodecContext){0};
    avctx->priv_data=s; avctx->codec_id=AV_CODEC_ID_HEVC;
    avctx->hw_device_ctx=av_buffer_allocz(sizeof(AVHWDeviceContext)); assert(avctx->hw_device_ctx);
    ((AVHWDeviceContext*)avctx->hw_device_ctx->data)->type=AV_HWDEVICE_TYPE_QSV;
    s->qsv.dovi_metadata=1; s->qsv.async_depth=1;
    assert(!qsv_decode_init(avctx));
    s=qsv_decoder_owner(avctx);
    s->qsv.session=(mfxSession)(uintptr_t)1; s->qsv.initialized=1;
    s->qsv.frame_info=(mfxFrameInfo){.FourCC=MFX_FOURCC_P010,.Width=128,.Height=64,
                                   .CropW=4,.CropH=4,.PicStruct=MFX_PICSTRUCT_PROGRESSIVE};
    s->qsv.async_fifo=av_fifo_alloc2(1,sizeof(QSVAsyncFrame),0); assert(s->qsv.async_fifo);
    avctx->pix_fmt=AV_PIX_FMT_QSV; avctx->sw_pix_fmt=AV_PIX_FMT_P010;
    avctx->field_order=AV_FIELD_PROGRESSIVE; avctx->coded_width=avctx->coded_height=4;
    avctx->pkt_timebase=(AVRational){1,1000000}; returned_token=0;
    return s;
}
static void quarantine_case(int failure)
{
    QSVDecContext *original=av_mallocz(sizeof(*original)); assert(original);
    AVCodecContext avctx; QSVDecContext *s=init_decoder(original,&avctx);
    const uint8_t data[]={0,0,1,2,1,0xc0};
    AVPacket pkt={.data=(uint8_t*)data,.size=sizeof(data),.pts=-11};
    AVPacket owned_pkt={0};
    assert(!av_new_packet(&owned_pkt,sizeof(data)));
    memcpy(owned_pkt.data,data,sizeof(data)); owned_pkt.pts=pkt.pts;
    AVFrame *frame=av_frame_alloc(); assert(frame); int got=0;
    if (failure < 2) {
        sync_status=failure?MFX_ERR_DEVICE_FAILED:MFX_WRN_IN_EXECUTION;
        behavior=COMPLETE; int before=sync_calls;
        assert(qsv_decode_frame(&avctx,frame,&got,&owned_pkt)==AVERROR_EXTERNAL && !got);
        assert(s->buffer_pkt.buf && s->buffer_pkt.data==owned_pkt.data &&
               s->buffer_pkt.size==owned_pkt.size && s->dovi_queued_bytes==owned_pkt.size);
        av_packet_unref(&owned_pkt);
        assert(s->buffer_pkt.buf && av_buffer_get_ref_count(s->buffer_pkt.buf)==1);
        assert(sync_calls-before==(failure?1:5));
        assert(av_fifo_can_read(s->qsv.async_fifo)==1 && s->qsv.work_frames->queued==1 && s->qsv.dovi.count==1);
    } else {
        close_status=failure==2?MFX_ERR_DEVICE_FAILED:MFX_WRN_IN_EXECUTION;
        qsv_decode_flush(&avctx);
    }
    assert(s->qsv.dovi_quarantined && s->qsv.dovi.failed && atomic_load(&qsv_dovi_process_quarantined));
    QSVDecContext *owner=s;
    AVBufferRef *device=s->qsv.dovi_device_ref;
    QSVFrame *frames=s->qsv.work_frames;
    int before_frees=frame_frees;
    assert(qsv_decode_close(&avctx)==AVERROR_EXTERNAL);
    assert(owner->dovi_owner==owner && owner->qsv.dovi_device_ref==device &&
           owner->qsv.work_frames==frames && owner->qsv.session && frame_frees==before_frees);
    memset(original,0,sizeof(*original)); av_free(original); avctx.priv_data=NULL;
    av_buffer_unref(&avctx.hw_device_ctx);
    assert(av_buffer_get_ref_count(owner->qsv.dovi_device_ref)==1);
    QSVDecContext reopened={0}; AVCodecContext other={.priv_data=&reopened,.codec_id=AV_CODEC_ID_HEVC};
    reopened.qsv.dovi_metadata=1;
    assert(qsv_decode_init(&other)==AVERROR_EXTERNAL && !reopened.dovi_owner);
    av_frame_free(&frame);
    av_packet_unref(&owned_pkt);
    /* Driver ownership is intentionally retained until this child exits. */
}
int main(void)
{
    const uint8_t data[]={0,0,1,2,1,0xc0,0,0,1,2,1,0x40};
    AVPacket pkt={.data=(uint8_t*)data,.size=sizeof(data),.pts=INT64_MAX-7,.duration=41708};
    AVCodecContext avctx; QSVContext q; AVFrame *frame=av_frame_alloc(); assert(frame);
    setup(&q,&avctx); int got=0;
    behavior=PARTIAL; assert(qsv_decode(&avctx,&q,frame,&got,&pkt)==2 && !got);
    assert(q.dovi.pending.token==1 && !q.dovi.count && q.dovi.next==0);
    AVPacket tail=pkt; tail.data+=2; tail.size-=2;
    behavior=COMPLETE; assert(qsv_decode(&avctx,&q,frame,&got,&tail)==tail.size && got);
    assert(observed[0]==1 && observed[1]==1 && frame->pts==pkt.pts && frame->duration==pkt.duration);
    assert(!q.dovi.pending.token && !q.dovi.count && q.dovi.next==1);
    cleanup(&q); av_frame_unref(frame); ++done;

    setup(&q,&avctx); behavior=BUFFER_ONLY;
    for (int i=0;i<3;i++) {
        pkt.pts=i==1?AV_NOPTS_VALUE:INT64_MAX-i;
        got=0; assert(qsv_decode(&avctx,&q,frame,&got,&pkt)==pkt.size && !got);
    }
    assert(q.dovi.count==3);
    const unsigned order[]={3,1,2};
    behavior=COMPLETE;
    for (unsigned i=0;i<3;i++) {
        returned_token=order[i]; pkt.pts=5; got=0;
        assert(qsv_decode(&avctx,&q,frame,&got,&pkt)==pkt.size && got);
        assert(frame->pts==(order[i]==2?AV_NOPTS_VALUE:INT64_MAX-(order[i]-1)));
        av_frame_unref(frame);
    }
    assert(q.dovi.count==3); /* newer accepted pictures remain owned */
    cleanup(&q); ++done;

    setup(&q,&avctx); behavior=COMPLETE; got=0;
    assert(qsv_decode(&avctx,&q,frame,&got,&pkt)==pkt.size && got);
    av_frame_unref(frame); returned_token=1; got=0;
    assert(qsv_decode(&avctx,&q,frame,&got,&pkt)==AVERROR_INVALIDDATA && !got && q.dovi.failed);
    assert(q.dovi.count==1 && q.dovi.entries[0].token==2);
    cleanup(&q); av_frame_unref(frame); ++done;

    for (int mode=ZERO_CONSUME;mode<=PREPARED_OUTPUT;mode++) {
        setup(&q,&avctx); behavior=mode; got=0;
        assert(qsv_decode(&avctx,&q,frame,&got,&pkt)==AVERROR_INVALIDDATA && !got);
        assert(q.dovi.failed);
        if (mode==ZERO_CONSUME || mode==PREPARED_OUTPUT)
            assert(q.dovi.pending.token && !q.dovi.count && !q.dovi.next);
        else
            assert(!q.dovi.pending.token && q.dovi.count==1 && q.dovi.next==1);
        cleanup(&q); av_frame_unref(frame); ++done;
    }
    setup(&q,&avctx); q.dovi_metadata=0; behavior=ZERO_CONSUME; got=0;
    assert(qsv_decode(&avctx,&q,frame,&got,&pkt)==pkt.size && !got && !q.dovi.pending.token);
    cleanup(&q); ++done;

    for (int mode=INVALID_OFFSET;mode<=PARAM_WARNING;mode++) {
        setup(&q,&avctx); behavior=mode; got=0;
        int before_sync=sync_calls, before_close=closes;
        assert(qsv_decode(&avctx,&q,frame,&got,&pkt)==AVERROR_INVALIDDATA && !got);
        assert(q.dovi.failed && q.dovi_untracked_sync && !q.dovi_quarantined &&
               !av_fifo_can_read(q.async_fifo) && q.dovi.pending.token);
        assert(!qsv_decode_close_qsvcontext(&q));
        assert(sync_calls==before_sync+1 && closes==before_close+1 && !q.dovi_untracked_sync);
        qsv_dovi_uninit(&q.dovi); av_frame_unref(frame); ++done;
    }

    for (int mode=BUSY_FOREVER;mode<=SURFACE_FOREVER;mode++) {
        setup(&q,&avctx); behavior=mode; got=0; int before=calls;
        fixture_clock_step=mode==BUSY_FOREVER?1000000:0;
        assert(qsv_decode(&avctx,&q,frame,&got,&pkt)==AVERROR(ETIMEDOUT) && !got);
        assert(calls-before==(mode==BUSY_FOREVER?4:16) && q.dovi.failed && q.dovi.pending.token && !q.dovi.count);
        unsigned frames=0; for (QSVFrame *it=q.work_frames;it;it=it->next) ++frames;
        assert(frames<=16 && !q.dovi_untracked_sync);
        cleanup(&q); av_frame_unref(frame); ++done;
    }
    fixture_clock_step=0;
    setup(&q,&avctx); behavior=BUSY_THEN_SUCCESS; busy_remaining=20; got=0; int before_busy=calls;
    assert(qsv_decode(&avctx,&q,frame,&got,&pkt)==pkt.size && got && calls-before_busy==21);
    assert(q.work_frames && !q.work_frames->next);
    cleanup(&q); av_frame_unref(frame); ++done;

    QSVDecContext decoder={0};
    setup(&decoder.qsv,&avctx); avctx.priv_data=&decoder;
    decoder.packet_fifo=av_fifo_alloc2(1,sizeof(AVPacket),AV_FIFO_FLAG_AUTO_GROW); assert(decoder.packet_fifo);
    buffer_eagain=1; behavior=COMPLETE; got=0; unsigned before_calls=calls;
    assert(qsv_decode_frame(&avctx,frame,&got,&pkt)==pkt.size && !got);
    assert(decoder.qsv.dovi.pending.token==1 && decoder.buffer_pkt.size==pkt.size &&
           !decoder.qsv.dovi.failed && !decoder.qsv.dovi.count && calls==(int)before_calls);
    AVPacket drain={0};
    assert(qsv_decode_frame(&avctx,frame,&got,&drain)==0 && got && observed[calls-1]==1);
    assert(frame->pts==pkt.pts && !decoder.qsv.dovi.pending.token);
    cleanup(&decoder.qsv); av_frame_unref(frame);
    qsv_clear_buffers(&decoder); av_fifo_freep2(&decoder.packet_fifo); ++done;

    setup(&decoder.qsv,&avctx); avctx.priv_data=&decoder;
    decoder.packet_fifo=av_fifo_alloc2(1,sizeof(AVPacket),AV_FIFO_FLAG_AUTO_GROW); assert(decoder.packet_fifo);
    decoder.qsv.async_depth=3; av_fifo_freep2(&decoder.qsv.async_fifo);
    decoder.qsv.async_fifo=av_fifo_alloc2(3,sizeof(QSVAsyncFrame),0); assert(decoder.qsv.async_fifo);
    behavior=COMPLETE; returned_token=0;
    for (int i=0;i<2;i++) { got=0; assert(qsv_decode(&avctx,&decoder.qsv,frame,&got,&pkt)==pkt.size && !got); }
    assert(decoder.qsv.dovi.count==2 && av_fifo_can_read(decoder.qsv.async_fifo)==2);
    int before_closes=closes; qsv_decode_flush(&avctx);
    assert(closes==before_closes+1 && !decoder.qsv.session && !decoder.qsv.async_fifo &&
           !decoder.qsv.work_frames && !decoder.qsv.dovi.count && decoder.qsv.dovi.next==2);
    assert(!qsv_dovi_prepare(&decoder.qsv.dovi,&pkt,0) && decoder.qsv.dovi.pending.token==3);
    assert(qsv_dovi_output(&decoder.qsv.dovi,1,frame)==AVERROR_INVALIDDATA);
    qsv_dovi_uninit(&decoder.qsv.dovi); av_fifo_freep2(&decoder.packet_fifo); ++done;

    QSVDecContext *owned;
    owned=init_decoder(&decoder,&avctx); behavior=BUFFER_ONLY; got=0;
    assert(qsv_decode_frame(&avctx,frame,&got,&pkt)==pkt.size && !got && owned->qsv.dovi.count==1);
    behavior=DRAIN_EMPTY;
    assert(qsv_decode_frame(&avctx,frame,&got,&drain)==AVERROR_INVALIDDATA && owned->qsv.dovi.failed);
    assert(!qsv_decode_close(&avctx)); av_buffer_unref(&avctx.hw_device_ctx); ++done;

    owned=init_decoder(&decoder,&avctx); behavior=COMPLETE; got=0; before_calls=calls;
    assert(!av_packet_ref(&owned->buffer_pkt,&pkt));
    owned->dovi_queued_bytes=pkt.size;
    for (unsigned i=0;i<QSV_DOVI_MAX-1;i++) {
        AVPacket queued={0}; assert(!av_packet_ref(&queued,&pkt));
        assert(!av_fifo_write(owned->packet_fifo,&queued,1));
        owned->dovi_queued_bytes+=pkt.size;
    }
    assert(!owned->qsv.dovi.pending.token && !owned->qsv.dovi.count);
    assert(qsv_decode_frame(&avctx,frame,&got,&pkt)==AVERROR(ENOBUFS) && calls==(int)before_calls &&
           owned->buffer_pkt.size==pkt.size && av_fifo_can_read(owned->packet_fifo)==QSV_DOVI_MAX-1);
    assert(!qsv_decode_close(&avctx)); av_buffer_unref(&avctx.hw_device_ctx); ++done;

    owned=init_decoder(&decoder,&avctx); behavior=COMPLETE; got=0; before_calls=calls;
    for (unsigned i=0;i<QSV_DOVI_MAX;i++) {
        buffer_eagain=1;
        assert(qsv_decode_frame(&avctx,frame,&got,&pkt)==pkt.size && !got);
        assert(owned->qsv.dovi.pending.token==1 && !owned->qsv.dovi.count);
    }
    assert(av_fifo_can_read(owned->packet_fifo)==QSV_DOVI_MAX-1 && calls==(int)before_calls);
    assert(qsv_decode_frame(&avctx,frame,&got,&pkt)==AVERROR(ENOBUFS) &&
           av_fifo_can_read(owned->packet_fifo)==QSV_DOVI_MAX-1 && owned->qsv.dovi.failed);
    assert(!qsv_decode_close(&avctx)); av_buffer_unref(&avctx.hw_device_ctx); ++done;

    owned=init_decoder(&decoder,&avctx); behavior=COMPLETE; got=0; int before_frees=frame_frees;
    assert(qsv_decode_frame(&avctx,frame,&got,&pkt)==pkt.size && got);
    AVBufferRef *consumer=av_buffer_ref(frame->buf[0]); assert(consumer);
    av_frame_unref(frame); qsv_decode_flush(&avctx);
    assert(frame_frees==before_frees && av_buffer_get_ref_count(consumer)==1);
    av_buffer_unref(&consumer); assert(frame_frees==before_frees+1);
    assert(!qsv_decode_close(&avctx)); av_buffer_unref(&avctx.hw_device_ctx); ++done;

    owned=init_decoder(&decoder,&avctx); owned->qsv.initialized=0; before_closes=closes;
    assert(!qsv_decode_close(&avctx) && closes==before_closes && !atomic_load(&qsv_dovi_process_quarantined));
    av_buffer_unref(&avctx.hw_device_ctx); ++done;

    owned=init_decoder(&decoder,&avctx); buffer_eagain=1; behavior=COMPLETE; got=0;
    assert(qsv_decode_frame(&avctx,frame,&got,&pkt)==pkt.size && !got);
    owned->dovi_queued_bytes=64*1024*1024;
    assert(qsv_decode_frame(&avctx,frame,&got,&pkt)==AVERROR(ENOBUFS) &&
           owned->qsv.dovi.failed && owned->qsv.dovi.pending.token==1 && !av_fifo_can_read(owned->packet_fifo));
    assert(!qsv_decode_close(&avctx)); av_buffer_unref(&avctx.hw_device_ctx); ++done;

    for (int i=0;i<4;i++) {
        pid_t child=fork(); assert(child>=0);
        if (!child) { quarantine_case(i); _exit(0); }
        int status; assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
        assert(!atomic_load(&qsv_dovi_process_quarantined)); ++done;
    }
    av_frame_free(&frame);
    printf("{\"schema\":\"yblod.qsv-dovi-mfx-contracts.v1\",\"cases\":%d,"
           "\"parent_process_qsv_decode_calls\":%d,\"quarantine_child_cases\":4,\"all_passed\":true,\"mfx_is_mocked\":true,"
           "\"hardware_qualified\":false}\n",done,calls);
    return 0;
}
