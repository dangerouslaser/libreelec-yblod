/* Pure static admission helper replay. Synthetic FFmpeg buffers, no VA/EGL
 * calls and no claim these fixtures are actual decoded hardware frames. */
#include "native_playback_context.c"
#include <stdio.h>
int main(void)
{
    AVFrame *frame=av_frame_alloc();
    AVBufferRef *device=av_buffer_alloc(sizeof(AVHWDeviceContext));
    if(!frame||!device){av_frame_free(&frame);av_buffer_unref(&device);return 1;}
    frame->hw_frames_ctx=av_buffer_alloc(sizeof(AVHWFramesContext));
    frame->buf[0]=av_buffer_alloc(8);
    if(!frame->hw_frames_ctx||!frame->buf[0]){av_frame_free(&frame);av_buffer_unref(&device);return 1;}
    AVVAAPIDeviceContext va={0};va.display=(VADisplay)(uintptr_t)1;
    AVHWDeviceContext *dev=(AVHWDeviceContext *)device->data;
    memset(dev,0,sizeof(*dev));dev->type=AV_HWDEVICE_TYPE_VAAPI;dev->hwctx=&va;
    AVHWFramesContext *frames=(AVHWFramesContext *)frame->hw_frames_ctx->data;
    memset(frames,0,sizeof(*frames));frames->format=AV_PIX_FMT_VAAPI;
    frames->sw_format=AV_PIX_FMT_P010LE;frames->width=frames->height=64;frames->device_ref=device;
    frame->format=AV_PIX_FMT_VAAPI;frame->width=frame->height=64;
    frame->data[3]=(uint8_t *)(uintptr_t)7;
    yb_native_playback_context context={0};context.settings.va_display=va.display;
    uint32_t width=31,height=37;
    int good=frame_contract(&context,frame,7,64,64,&width,&height)&&width==64&&height==64;
    AVBufferRef *held=frame->buf[0];frame->buf[0]=NULL;width=31;height=37;
    int rejected=!frame_contract(&context,frame,7,64,64,&width,&height)&&width==31&&height==37;
    frame->buf[0]=held;
    int restored=frame_contract(&context,frame,7,64,64,&width,&height);
    /* The synthetic frame buffer destructor does not own our synthetic device
     * ref; free it explicitly, avoiding any driver teardown callbacks. */
    frames->device_ref=NULL;av_buffer_unref(&device);av_frame_free(&frame);
    int okay=good&&rejected&&restored;
    printf("{\"schema\":\"yblod.playback-frame-admission-host-probe.v1\",\"complete\":%s,\"gpu_attempted\":false,\"checks\":3,\"missing_buf0_rejection_atomic\":%s}\n",okay?"true":"false",rejected?"true":"false");
    return okay?0:1;
}
