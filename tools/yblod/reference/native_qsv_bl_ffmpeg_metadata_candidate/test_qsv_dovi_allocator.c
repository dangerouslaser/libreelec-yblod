/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Actual registration/callback bodies; session setup and MFX calls are mocked. */
#define ff_hevc_qsv_decoder fixture_hevc_qsv_decoder
#include "qsvdec.c"
#include <assert.h>
#include <stdio.h>

static mfxFrameAllocator registered;
static int fixture_session_device(AVCodecContext *avctx, mfxSession *session,
                                  AVBufferRef *device, const char *plugins, int copy)
{
    assert(device && device->data); *session=(mfxSession)(uintptr_t)1; return 0;
}
#include "/tmp/qsv_allocator_fixture.c"

mfxStatus MFXVideoCORE_SetFrameAllocator(mfxSession session, mfxFrameAllocator *allocator)
{
    assert(session && allocator); registered=*allocator; return MFX_ERR_NONE;
}
mfxStatus MFXVideoDECODE_Close(mfxSession session)
{
    assert(session); return MFX_ERR_DEVICE_FAILED;
}
static unsigned frames_freed, device_freed;
static void device_drop(void *opaque, uint8_t *data) { ++device_freed; av_free(data); }
static void frames_drop(void *opaque, uint8_t *data)
{
    AVHWFramesContext *frames=(AVHWFramesContext*)data;
    ++frames_freed; av_buffer_unref(&frames->device_ref); av_free(frames->hwctx); av_free(data);
}
int main(void)
{
    QSVDecContext *original=av_mallocz(sizeof(*original)); assert(original);
    original->class=(AVClass*)&hevc_qsv_class; av_opt_set_defaults(original);
    assert(!av_opt_set(original,"load_plugin","none",0)); original->qsv.dovi_metadata=1;
    AVCodecContext avctx={.priv_data=original,.codec_id=AV_CODEC_ID_HEVC,.pkt_timebase={1,1000000}};
    AVHWDeviceContext *device=av_mallocz(sizeof(*device)); assert(device); device->type=AV_HWDEVICE_TYPE_QSV;
    avctx.hw_device_ctx=av_buffer_create((uint8_t*)device,sizeof(*device),device_drop,NULL,0); assert(avctx.hw_device_ctx);
    AVHWFramesContext *frames=av_mallocz(sizeof(*frames)); assert(frames);
    frames->hwctx=av_mallocz(sizeof(AVQSVFramesContext)); assert(frames->hwctx);
    frames->device_ref=av_buffer_ref(avctx.hw_device_ctx); assert(frames->device_ref);
    avctx.hw_frames_ctx=av_buffer_create((uint8_t*)frames,sizeof(*frames),frames_drop,NULL,0); assert(avctx.hw_frames_ctx);
    assert(!qsv_decode_init(&avctx));
    QSVDecContext *owner=qsv_decoder_owner(&avctx);
    assert(owner!=original && owner->dovi_owner==owner && !original->qsv.load_plugins);
    owner->qsv.frames_ctx.hw_frames_ctx=av_buffer_ref(avctx.hw_frames_ctx); assert(owner->qsv.frames_ctx.hw_frames_ctx);
    assert(!ff_qsv_init_session_frames(&avctx,&owner->qsv.session,&owner->qsv.frames_ctx,"",0,0));
    assert(registered.pthis==&owner->qsv.frames_ctx);
    owner->qsv.initialized=1;
    qsv_decode_flush(&avctx);
    assert(owner->qsv.dovi_quarantined && owner->qsv.dovi.failed && owner->qsv.frames_ctx.hw_frames_ctx);
    assert(qsv_decode_close(&avctx)==AVERROR_EXTERNAL && !original->dovi_owner);
    av_opt_free(original); memset(original,0,sizeof(*original)); av_free(original); avctx.priv_data=NULL;
    av_buffer_unref(&avctx.hw_device_ctx); av_buffer_unref(&avctx.hw_frames_ctx);
    memset(&avctx,0,sizeof(avctx));
    assert(!frames_freed && !device_freed && registered.pthis==&owner->qsv.frames_ctx &&
           !owner->qsv.frames_ctx.logctx && !owner->qsv.dovi.active.logctx);
    mfxHDLPair input={(mfxHDL)(uintptr_t)12,(mfxHDL)(uintptr_t)34}, output={0};
    assert(registered.GetHDL(registered.pthis,&input,(mfxHDL*)&output)==MFX_ERR_NONE);
    assert(output.first==input.first && output.second==input.second);
    mfxFrameData data={0};
    assert(registered.Lock(registered.pthis,NULL,&data)==MFX_ERR_UNSUPPORTED);
    assert(registered.Unlock(registered.pthis,NULL,&data)==MFX_ERR_UNSUPPORTED);
    mfxFrameAllocRequest request={0}; mfxFrameAllocResponse response={0};
    assert(registered.Alloc(registered.pthis,&request,&response)==MFX_ERR_UNSUPPORTED);
    request.Type=MFX_MEMTYPE_EXTERNAL_FRAME | MFX_MEMTYPE_VIDEO_MEMORY_DECODER_TARGET | MFX_MEMTYPE_FROM_DECODE;
    assert(registered.Alloc(registered.pthis,&request,&response)==MFX_ERR_NONE);
    assert(!response.mids && !response.NumFrameActual && !frames_freed && !device_freed);
    assert(registered.Free(registered.pthis,&response)==MFX_ERR_NONE);
    assert(!frames_freed && !device_freed);
    QSVDecContext retry={.qsv.dovi_metadata=1}; AVCodecContext reopened={.priv_data=&retry,.codec_id=AV_CODEC_ID_HEVC};
    assert(qsv_decode_init(&reopened)==AVERROR_EXTERNAL && !retry.dovi_owner);
    puts("{\"schema\":\"yblod.qsv-dovi-allocator-owner.v1\",\"actual_callbacks_after_privdata_free\":5,"
         "\"same_opaque_address\":true,\"owner_refs_retained\":true,\"reopen_poisoned\":true,"
         "\"all_passed\":true,\"session_and_mfx_mocked\":true,\"hardware_qualified\":false}");
    return 0;
}
