/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Actual init/process/decode functions; device allocation and MFX are mocked. */
#define ff_hevc_qsv_decoder fixture_hevc_qsv_decoder
#include "qsvdec.c"
#include <assert.h>
#include <stdio.h>

static unsigned init_calls, decode_calls, sync_calls, close_calls, frame_frees;
static AVFrame *producer_frame;
static mfxFrameSurface1 *completed;
static uint64_t timestamp;
static int corrupt_output;
static const mfxFrameInfo pool_prefill={.Width=64,.Height=32,.CropX=1,.CropY=1,.CropW=2,.CropH=2};
static void frame_drop(void *opaque, uint8_t *data) { ++frame_frees; av_free(data); }
static void pool_drop(void *opaque, uint8_t *data)
{
    AVHWFramesContext *frames=(AVHWFramesContext*)data;
    av_buffer_unref(&frames->device_ref); av_free(data);
}
int __wrap_ff_decode_frame_props(AVCodecContext *avctx, AVFrame *frame)
{ frame->format=avctx->pix_fmt; return 0; }
int __wrap_ff_attach_decode_data(AVCodecContext *avctx, AVFrame *frame) { return 0; }
int __wrap_ff_get_buffer(AVCodecContext *avctx, AVFrame *frame, int flags)
{
    uint8_t *data=av_mallocz(sizeof(mfxFrameSurface1)); assert(data);
    frame->buf[0]=av_buffer_create(data,sizeof(mfxFrameSurface1),frame_drop,NULL,0); assert(frame->buf[0]);
    frame->hw_frames_ctx=av_buffer_ref(avctx->hw_frames_ctx); assert(frame->hw_frames_ctx);
    frame->format=AV_PIX_FMT_QSV; frame->width=frame->height=4; frame->data[3]=data;
    ((mfxFrameSurface1*)data)->Info=pool_prefill;
    producer_frame=frame; return 0;
}
mfxStatus MFXVideoDECODE_Init(mfxSession session, mfxVideoParam *param)
{ assert(session && param->mfx.FrameInfo.FourCC==MFX_FOURCC_P010); ++init_calls; return MFX_ERR_NONE; }
mfxStatus MFXVideoDECODE_DecodeFrameAsync(mfxSession session, mfxBitstream *bs,
                                        mfxFrameSurface1 *in, mfxFrameSurface1 **out, mfxSyncPoint *sync)
{
    assert(session && bs && bs->DataLength); ++decode_calls;
    timestamp=bs->TimeStamp; bs->DataOffset=bs->DataLength; bs->DataLength=0;
    completed=in; in->Data.TimeStamp=MFX_TIMESTAMP_UNKNOWN;
    in->Info.CropX=3; in->Info.CropY=2;
    *out=in; *sync=(mfxSyncPoint)(uintptr_t)1; return MFX_ERR_NONE;
}
mfxStatus MFXVideoCORE_SyncOperation(mfxSession session, mfxSyncPoint sync, mfxU32 wait)
{
    assert(session && sync); ++sync_calls; completed->Data.TimeStamp=timestamp;
    if (corrupt_output==1) producer_frame->format=AV_PIX_FMT_P010;
    if (corrupt_output==2) av_buffer_unref(&producer_frame->hw_frames_ctx);
    if (corrupt_output==3)
        ((AVHWFramesContext*)producer_frame->hw_frames_ctx->data)->sw_format=AV_PIX_FMT_NV12;
    if (corrupt_output==4) {
        AVHWFramesContext *frames=(AVHWFramesContext*)producer_frame->hw_frames_ctx->data;
        av_buffer_unref(&frames->device_ref);
        frames->device_ref=av_buffer_allocz(sizeof(AVHWDeviceContext)); assert(frames->device_ref);
        ((AVHWDeviceContext*)frames->device_ref->data)->type=AV_HWDEVICE_TYPE_QSV;
    }
    return MFX_ERR_NONE;
}
mfxStatus MFXVideoDECODE_Close(mfxSession session) { assert(session); ++close_calls; return MFX_ERR_NONE; }
static void setup(QSVContext *q, AVCodecContext *avctx)
{
    *q=(QSVContext){0}; *avctx=(AVCodecContext){0};
    avctx->codec_id=AV_CODEC_ID_HEVC; avctx->pkt_timebase=(AVRational){1,1000000};
    avctx->hw_device_ctx=av_buffer_allocz(sizeof(AVHWDeviceContext)); assert(avctx->hw_device_ctx);
    ((AVHWDeviceContext*)avctx->hw_device_ctx->data)->type=AV_HWDEVICE_TYPE_QSV;
    AVHWFramesContext *pool=av_mallocz(sizeof(*pool)); assert(pool);
    pool->format=AV_PIX_FMT_QSV; pool->sw_format=AV_PIX_FMT_P010;
    pool->device_ref=av_buffer_ref(avctx->hw_device_ctx); assert(pool->device_ref);
    avctx->hw_frames_ctx=av_buffer_create((uint8_t*)pool,sizeof(*pool),pool_drop,NULL,0); assert(avctx->hw_frames_ctx);
    q->dovi_device_ref=av_buffer_ref(avctx->hw_device_ctx); assert(q->dovi_device_ref);
    q->dovi_metadata=1; q->session=(mfxSession)(uintptr_t)1; q->async_depth=1;
    q->iopattern=MFX_IOPATTERN_OUT_VIDEO_MEMORY;
    q->async_fifo=av_fifo_alloc2(1,sizeof(QSVAsyncFrame),0); assert(q->async_fifo);
    mfxVideoParam param={.mfx.FrameInfo={.FourCC=MFX_FOURCC_P010,.Width=128,.Height=64,
                                        .CropW=4,.CropH=4,.PicStruct=MFX_PICSTRUCT_PROGRESSIVE}};
    assert(!qsv_decode_init_context(avctx,q,&param)); q->initialized=1;
    assert(avctx->pix_fmt==AV_PIX_FMT_P010 && !q->pool);
}
static void cleanup(QSVContext *q, AVCodecContext *avctx)
{
    assert(!qsv_decode_close_qsvcontext(q)); qsv_dovi_uninit(&q->dovi);
    av_buffer_unref(&q->dovi_device_ref);
    av_buffer_unref(&avctx->hw_frames_ctx); av_buffer_unref(&avctx->hw_device_ctx);
}
int main(void)
{
    const uint8_t data[]={0,0,1,2,1,0xc0};
    AVPacket pkt={.data=(uint8_t*)data,.size=sizeof(data),.pts=-37,.duration=41708};
    AVFrame *frame=av_frame_alloc(); assert(frame);
    QSVContext q; AVCodecContext avctx; int got=0; unsigned cases=0;
    setup(&q,&avctx);
    assert(qsv_process_data(&avctx,&q,frame,&got,&pkt)==pkt.size && got);
    assert(frame->format==AV_PIX_FMT_QSV && frame->hw_frames_ctx && frame->pts==-37 &&
           frame->duration==41708 && !q.dovi.count && q.dovi.next==1 && sync_calls==1);
    assert(!memcmp(&((mfxFrameSurface1*)frame->data[3])->Info,&completed->Info,sizeof(completed->Info)) &&
           memcmp(&completed->Info,&pool_prefill,sizeof(pool_prefill)) &&
           frame->crop_left==3 && frame->crop_top==2 &&
           ((mfxFrameSurface1*)frame->data[3])->Info.CropX==3 &&
           ((mfxFrameSurface1*)frame->data[3])->Info.CropY==2);
    AVBufferRef *consumer=av_buffer_ref(frame->buf[0]); assert(consumer);
    av_frame_unref(frame); unsigned before=frame_frees;
    cleanup(&q,&avctx); assert(frame_frees==before);
    av_buffer_unref(&consumer); assert(frame_frees==before+1); ++cases;
    setup(&q,&avctx); q.dovi_metadata=0; got=0;
    assert(qsv_process_data(&avctx,&q,frame,&got,&pkt)==pkt.size && got);
    assert(frame->format==AV_PIX_FMT_QSV &&
           !memcmp(&((mfxFrameSurface1*)frame->data[3])->Info,&pool_prefill,sizeof(pool_prefill)));
    av_frame_unref(frame); cleanup(&q,&avctx); ++cases;
    for (int mode=1;mode<=4;mode++) {
        setup(&q,&avctx); corrupt_output=mode; got=0;
        assert(qsv_process_data(&avctx,&q,frame,&got,&pkt)==AVERROR_INVALIDDATA && !got &&
               q.dovi.failed && q.dovi.count==1 && !frame->buf[0]);
        cleanup(&q,&avctx); ++cases;
    }
    corrupt_output=0;
    for (int mode=0;mode<4;mode++) {
        setup(&q,&avctx); got=0; unsigned before_decode=decode_calls;
        AVHWFramesContext *pool=(AVHWFramesContext*)avctx.hw_frames_ctx->data;
        if (mode==0) pool->sw_format=AV_PIX_FMT_NV12;
        if (mode==1) q.iopattern=MFX_IOPATTERN_OUT_SYSTEM_MEMORY;
        if (mode==2) q.frame_info.FourCC=MFX_FOURCC_NV12;
        if (mode==3) avctx.field_order=AV_FIELD_TT;
        assert(qsv_process_data(&avctx,&q,frame,&got,&pkt)==AVERROR_INVALIDDATA && !got &&
               q.dovi.failed && decode_calls==before_decode);
        cleanup(&q,&avctx); ++cases;
    }
    av_frame_free(&frame);
    printf("{\"schema\":\"yblod.qsv-dovi-real-init-cpu.v1\",\"cases\":%u,"
           "\"actual_init_calls\":%u,\"actual_process_decode_calls\":%u,\"sync_calls\":%u,"
           "\"cached_pix_fmt_is_p010\":true,\"returned_frame_format_is_qsv\":true,"
           "\"all_passed\":true,\"hardware_allocation_and_mfx_mocked\":true,\"hardware_qualified\":false}\n",
           cases,init_calls,decode_calls,sync_calls);
    return 0;
}
