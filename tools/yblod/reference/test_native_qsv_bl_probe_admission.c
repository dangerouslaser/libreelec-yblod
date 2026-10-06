/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Source-only CPU fixture. Includes actual probe predicates, no GPU calls. */
#include <assert.h>
#include <limits.h>
#define main yb_unexecuted_probe_main
#include "native_qsv_bl_compare_probe.c"
#undef main
static AVFrame *picture(int padding)
{
 AVFrame *f=av_frame_alloc();assert(f);
 f->format=AV_PIX_FMT_P010;f->width=3840;f->height=2160+padding;
 f->crop_bottom=padding;assert(av_frame_get_buffer(f,32)==0);
 for(unsigned i=0;i<AV_NUM_DATA_POINTERS;i++)if(f->buf[i])memset(f->buf[i]->data,0,f->buf[i]->size);
 f->pts=f->best_effort_timestamp=1210000000;
 f->duration=0;f->pkt_dts=AV_NOPTS_VALUE;
 f->sample_aspect_ratio=(AVRational){1,1};f->time_base=(AVRational){0,1};
 assert(buffers(f));return f;
}
int main(void)
{
 AVFrame *a=picture(0),*b=picture(16);int w,h;
 assert(geometry(a,&w,&h)&&w==3840&&h==2160);
 assert(geometry(b,&w,&h)&&w==3840&&h==2160);
 for(unsigned p=0;p<2;p++)for(int y=2160>>p;y<b->height>>p;y++)memset(b->data[p]+(size_t)y*b->linesize[p],255,b->linesize[p]);
 assert(props(a,b)); /* Coded-pool padding is not active content. */
 for(unsigned plane=0;plane<3;plane++){
  struct plane_result r=compare(a,b,plane);assert(!r.different&&r.low_bits_zero);
  assert(r.samples==(plane?2073600:8294400));
 }
 uint8_t *saved=b->data[0];b->data[0]++;assert(!buffers(b));b->data[0]=saved;
 int stride=b->linesize[0];b->linesize[0]++;assert(!buffers(b));b->linesize[0]=stride;
 b->linesize[0]=2;assert(!buffers(b));b->linesize[0]=stride;
 b->crop_left=1;assert(!geometry(b,&w,&h));b->crop_left=0;
 b->crop_bottom=b->height;assert(!geometry(b,&w,&h));b->crop_bottom=16;
 b->crop_top=SIZE_MAX;assert(!geometry(b,&w,&h));b->crop_top=0;
#define CHANGE(field,value) do {__typeof__(b->field) old=b->field;b->field=(value);assert(!props(a,b));b->field=old;assert(props(a,b));} while(0)
 CHANGE(pts,1210000001);CHANGE(best_effort_timestamp,1210000001);
 CHANGE(duration,1);CHANGE(pkt_dts,1);CHANGE(time_base.num,1);
 CHANGE(time_base.den,1000000);CHANGE(sample_aspect_ratio.num,2);
 CHANGE(sample_aspect_ratio.den,2);CHANGE(flags,AV_FRAME_FLAG_INTERLACED);
 CHANGE(repeat_pict,1);CHANGE(pict_type,AV_PICTURE_TYPE_B);
 CHANGE(color_range,AVCOL_RANGE_JPEG);CHANGE(color_primaries,AVCOL_PRI_BT2020);
 CHANGE(color_trc,AVCOL_TRC_SMPTE2084);CHANGE(colorspace,AVCOL_SPC_BT2020_NCL);
 CHANGE(chroma_location,AVCHROMA_LOC_LEFT);
#undef CHANGE
 int64_t pts;assert(timestamp(1210000,(AVRational){1,1000},0,&pts)&&pts==1210000000);
 assert(timestamp(AV_NOPTS_VALUE,(AVRational){0,0},0,&pts)&&pts==AV_NOPTS_VALUE);
 assert(!timestamp(1,(AVRational){0,1},0,&pts));
 assert(!timestamp(INT64_MAX,(AVRational){INT_MAX,1},0,&pts));
 AVCodecContext *ctx=avcodec_alloc_context3(NULL);assert(ctx);
 const enum AVPixelFormat choices[]={AV_PIX_FMT_YUV420P,AV_PIX_FMT_VAAPI,AV_PIX_FMT_QSV,AV_PIX_FMT_NONE};
 assert(format(ctx,choices)==AV_PIX_FMT_NONE);
 ctx->hw_device_ctx=av_buffer_allocz(sizeof(AVHWDeviceContext));assert(ctx->hw_device_ctx);
 ((AVHWDeviceContext*)ctx->hw_device_ctx->data)->type=AV_HWDEVICE_TYPE_QSV;
 assert(format(ctx,choices)==AV_PIX_FMT_QSV);
 ((AVHWDeviceContext*)ctx->hw_device_ctx->data)->type=AV_HWDEVICE_TYPE_VAAPI;
 assert(format(ctx,choices)==AV_PIX_FMT_VAAPI);
 avcodec_free_context(&ctx);av_frame_free(&a);av_frame_free(&b);
 puts("CPU active geometry/P010 alignment/property/timestamp/hardware-format predicates PASS");return 0;
}
