/* SPDX-License-Identifier: GPL-3.0-or-later */
/* SOURCE-ONLY EXPERIMENT. Diagnostic CPU readback; never a product download.
 * Both independent decoders receive byte-identical packet clones, in identical
 * order from one ordinary-MKV demux. Native HEVC independently resolves RPU.
 * Baseline native HEVC/RPU source identity must be proven by the launcher.
 * No media bytes, metadata values, paths or content hashes are exported. */
#include <libavcodec/avcodec.h>
#include <libavcodec/bsf.h>
#include <libavformat/avformat.h>
#include <libavutil/hwcontext.h>
#include <libavutil/log.h>
#include <libavutil/sha.h>
#include <libavutil/mem.h>
#include <inttypes.h>
#include <math.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include "native_qsv_probe_handshake.h"
#include "native_qsv_bl_metadata_equal.h"
#include "native_qsv_bl_payload_guard.h"
#include "native_qsv_bl_duration.h"
enum { N=3, VIDEO_LIMIT=4096, READ_LIMIT=65536 };
static const char *stage="preflight";
static time_t deadline;
static int64_t targets[N];
static uint64_t submitted[2], mapped, frames_seen[2];
static AVFrame *selected[2][N];
static int lifecycle_enabled,handshake_done,receive_end[2];
static unsigned lifecycle_epoch;
static AVFrame *held_owner;
struct private_packet_identity {int64_t pts,dts,duration;int size;uint8_t digest[32];};
static struct private_packet_identity *packet_identities;
static struct AVSHA *packet_sha;
static unsigned fixed_window_packets;
static uint64_t positive_duration_packets,unknown_duration_packets;
static int raw_rpu_equal(const AVFrame *a,const AVFrame *b);
static enum AVPixelFormat format(AVCodecContext *ctx,const enum AVPixelFormat *choices)
{
 if(!ctx||!ctx->hw_device_ctx||!ctx->hw_device_ctx->data)return AV_PIX_FMT_NONE;
 enum AVPixelFormat wanted=((AVHWDeviceContext*)ctx->hw_device_ctx->data)->type==AV_HWDEVICE_TYPE_QSV?AV_PIX_FMT_QSV:AV_PIX_FMT_VAAPI;
 for(;*choices!=AV_PIX_FMT_NONE;choices++)if(*choices==wanted)return wanted;
 return AV_PIX_FMT_NONE;
}
static int same_source(const struct stat *a,const struct stat *b)
{return S_ISREG(a->st_mode)&&a->st_dev==b->st_dev&&a->st_ino==b->st_ino&&a->st_size==b->st_size&&a->st_mtim.tv_sec==b->st_mtim.tv_sec&&a->st_mtim.tv_nsec==b->st_mtim.tv_nsec&&a->st_ctim.tv_sec==b->st_ctim.tv_sec&&a->st_ctim.tv_nsec==b->st_ctim.tv_nsec;}
static int timestamp(int64_t raw,AVRational tb,int64_t start,int64_t *out)
{
 if(raw==AV_NOPTS_VALUE){*out=raw;return 1;}
 if(tb.num<=0||tb.den<=0)return 0;
 double t=(double)raw*tb.num/tb.den,s=start==AV_NOPTS_VALUE?0:(double)start/AV_TIME_BASE;
 if(t>s)t-=s;else if(t+0.5>s)t=0;
 double v=(t*1000000.0)/1000000.0*AV_TIME_BASE;
 if(!isfinite(v)||v<=(double)INT64_MIN||v>=(double)INT64_MAX)return 0;
 *out=(int64_t)v;return 1;
}
static int geometry(const AVFrame *f,int *w,int *h)
{
 if(!f||f->width<=0||f->width>4096||f->height<=0||f->height>2304||
    ((f->crop_left|f->crop_right|f->crop_top|f->crop_bottom)&1)||
    f->crop_left>=(size_t)f->width||f->crop_right>=(size_t)f->width||
    f->crop_top>=(size_t)f->height||f->crop_bottom>=(size_t)f->height||
    f->crop_left+f->crop_right>=(size_t)f->width||f->crop_top+f->crop_bottom>=(size_t)f->height)return 0;
 *w=f->width-f->crop_left-f->crop_right;*h=f->height-f->crop_top-f->crop_bottom;
 return !(*w&1)&&!(*h&1);
}
static int buffers(const AVFrame *f)
{
 int w,h;if(!f||f->format!=AV_PIX_FMT_P010||!geometry(f,&w,&h))return 0;
 for(unsigned p=0;p<2;p++){
  AVBufferRef *b=av_frame_get_plane_buffer(f,p);
  size_t rows=((size_t)f->height+(1u<<p)-1)>>p,bytes=(size_t)f->width*2;
  if(!b||!f->data[p]||(uintptr_t)f->data[p]%_Alignof(uint16_t)||f->linesize[p]<=0||
     (f->linesize[p]&1)||(size_t)f->linesize[p]<bytes)return 0;
  uintptr_t begin=(uintptr_t)b->data,data=(uintptr_t)f->data[p];
  size_t span=(rows-1)*(size_t)f->linesize[p]+bytes;
  if(data<begin||data-begin>b->size||span>b->size-(data-begin))return 0;
 }
 return 1;
}
static int props(const AVFrame *a,const AVFrame *b)
{
 int aw,ah,bw,bh;
 return geometry(a,&aw,&ah)&&geometry(b,&bw,&bh)&&aw==bw&&ah==bh&&
  a->crop_left==b->crop_left&&a->crop_top==b->crop_top&&
  a->pts==b->pts&&a->best_effort_timestamp==b->best_effort_timestamp&&a->duration==b->duration&&
  a->time_base.num==b->time_base.num&&a->time_base.den==b->time_base.den&&
  a->pkt_dts==b->pkt_dts&&a->sample_aspect_ratio.num==b->sample_aspect_ratio.num&&
  a->sample_aspect_ratio.den==b->sample_aspect_ratio.den&&a->flags==b->flags&&
  a->repeat_pict==b->repeat_pict&&a->pict_type==b->pict_type&&
  a->chroma_location==b->chroma_location&&a->color_range==b->color_range&&
  a->color_primaries==b->color_primaries&&a->color_trc==b->color_trc&&a->colorspace==b->colorspace;
}
static int picture_props(const AVFrame *a,const AVFrame *b)
{
 int aw,ah,bw,bh;
 return geometry(a,&aw,&ah)&&geometry(b,&bw,&bh)&&aw==bw&&ah==bh&&
  a->crop_left==b->crop_left&&a->crop_top==b->crop_top&&
  a->pts==b->pts&&a->best_effort_timestamp==b->best_effort_timestamp&&a->duration==b->duration&&
  a->time_base.num==b->time_base.num&&a->time_base.den==b->time_base.den&&
  a->sample_aspect_ratio.num==b->sample_aspect_ratio.num&&
  a->sample_aspect_ratio.den==b->sample_aspect_ratio.den&&a->flags==b->flags&&
  a->repeat_pict==b->repeat_pict&&a->pict_type==b->pict_type&&
  a->chroma_location==b->chroma_location&&a->color_range==b->color_range&&
  a->color_primaries==b->color_primaries&&a->color_trc==b->color_trc&&a->colorspace==b->colorspace;
}
static uint32_t props_field_mask(const AVFrame *a,const AVFrame *b)
{
 int aw,ah,bw,bh;uint32_t mask=0;
 if(geometry(a,&aw,&ah)&&geometry(b,&bw,&bh)&&aw==bw&&ah==bh)mask|=UINT32_C(1)<<0;
 if(a->crop_left==b->crop_left)mask|=UINT32_C(1)<<1;
 if(a->crop_top==b->crop_top)mask|=UINT32_C(1)<<2;
 if(a->pts==b->pts)mask|=UINT32_C(1)<<3;
 if(a->best_effort_timestamp==b->best_effort_timestamp)mask|=UINT32_C(1)<<4;
 if(a->duration==b->duration)mask|=UINT32_C(1)<<5;
 if(a->time_base.num==b->time_base.num&&a->time_base.den==b->time_base.den)mask|=UINT32_C(1)<<6;
 if(a->pkt_dts==b->pkt_dts)mask|=UINT32_C(1)<<7;
 if(a->sample_aspect_ratio.num==b->sample_aspect_ratio.num&&a->sample_aspect_ratio.den==b->sample_aspect_ratio.den)mask|=UINT32_C(1)<<8;
 if(a->flags==b->flags)mask|=UINT32_C(1)<<9;
 if(a->repeat_pict==b->repeat_pict)mask|=UINT32_C(1)<<10;
 if(a->pict_type==b->pict_type)mask|=UINT32_C(1)<<11;
 if(a->chroma_location==b->chroma_location)mask|=UINT32_C(1)<<12;
 if(a->color_range==b->color_range)mask|=UINT32_C(1)<<13;
 if(a->color_primaries==b->color_primaries)mask|=UINT32_C(1)<<14;
 if(a->color_trc==b->color_trc)mask|=UINT32_C(1)<<15;
 if(a->colorspace==b->colorspace)mask|=UINT32_C(1)<<16;
 return mask;
}
#include "native_qsv_bl_pair_coverage.h"
static struct yb_pair_state pair_state;
static void print_geometry_observation(const struct yb_geometry_observation *g)
{
 printf("{\"frame_width\":%d,\"frame_height\":%d,\"crop_left\":%zu,\"crop_top\":%zu,\"crop_right\":%zu,\"crop_bottom\":%zu,\"pool_observed\":%s,\"pool_width\":%d,\"pool_height\":%d,\"pool_p010\":%s,\"pool_covers_coded_frame\":%s,\"zero_crop_shape_compatible\":%s,\"mapped_buffer_admission_proven\":false}",g->width,g->height,g->crop_left,g->crop_top,g->crop_right,g->crop_bottom,g->pool_observed?"true":"false",g->pool_width,g->pool_height,g->pool_p010?"true":"false",g->pool_covers?"true":"false",g->zero_crop_shape?"true":"false");
}
static int drain(AVCodecContext *decoder,unsigned route,AVBufferRef *va,AVBufferRef *qsv)
{
 receive_end[route]=0;
 for(unsigned bounded=0;bounded<128;bounded++){
  AVFrame *f=av_frame_alloc();if(!f)return 0;
  stage="receive_frame";int result=avcodec_receive_frame(decoder,f);
  if(result==AVERROR(EAGAIN)||result==AVERROR_EOF){receive_end[route]=result;av_frame_free(&f);return 1;}
  if(result<0){av_frame_free(&f);return 0;}
  frames_seen[route]++;
  if(f->format!=(route?AV_PIX_FMT_QSV:AV_PIX_FMT_VAAPI)||!f->hw_frames_ctx||!f->hw_frames_ctx->data){av_frame_free(&f);return 0;}
  AVHWFramesContext *source_pool=(void*)f->hw_frames_ctx->data;
  if(source_pool->format!=f->format||source_pool->sw_format!=AV_PIX_FMT_P010||
     source_pool->device_ctx!=(AVHWDeviceContext*)(route?qsv:va)->data){av_frame_free(&f);return 0;}
  stage="independent_decoded_metadata_pair";
  if(!yb_pair_frame(&pair_state,f,route)){av_frame_free(&f);return 0;}
  int index=-1;for(int i=0;i<N;i++)if(f->pts==targets[i])index=i;
  if(index<0){av_frame_free(&f);continue;}
  if(selected[route][index]){av_frame_free(&f);return 0;}
  AVFrame *hardware=f,*map=NULL;AVBufferRef *mapping=NULL;
  if(route){
   stage="direct_qsv_vaapi_map";
   map=av_frame_alloc();
   if(!map||av_hwframe_ctx_create_derived(&mapping,AV_PIX_FMT_VAAPI,va,f->hw_frames_ctx,AV_HWFRAME_MAP_READ|AV_HWFRAME_MAP_DIRECT)<0)goto frame_fail;
   map->format=AV_PIX_FMT_VAAPI;map->hw_frames_ctx=av_buffer_ref(mapping);
   if(!map->hw_frames_ctx||av_hwframe_map(map,f,AV_HWFRAME_MAP_READ|AV_HWFRAME_MAP_DIRECT)<0||av_frame_copy_props(map,f)<0)goto frame_fail;
   hardware=map;mapped++;
  }
  if(!hardware->hw_frames_ctx||!hardware->hw_frames_ctx->data)goto frame_fail;
  AVHWFramesContext *pool=(void*)hardware->hw_frames_ctx->data;
  if(hardware->format!=AV_PIX_FMT_VAAPI||pool->device_ctx!=(AVHWDeviceContext*)va->data||pool->sw_format!=AV_PIX_FMT_P010)goto frame_fail;
  if(route&&!mapped){goto frame_fail;}
  if(route&&mapped==1&&!handshake_done){stage="live_identity_before_readback";if(!qsv_probe_handshake(deadline))goto frame_fail;handshake_done=1;}
  if(lifecycle_enabled&&!lifecycle_epoch&&route&&index==0&&!held_owner){
   stage="retain_one_mapped_owner";held_owner=av_frame_clone(hardware);if(!held_owner)goto frame_fail;
  }
  stage="diagnostic_readback";
  selected[route][index]=av_frame_alloc();
  if(!selected[route][index]||av_hwframe_transfer_data(selected[route][index],hardware,0)<0||av_frame_copy_props(selected[route][index],hardware)<0||!buffers(selected[route][index]))goto frame_fail;
  av_frame_free(&map);av_buffer_unref(&mapping);av_frame_free(&f);continue;
frame_fail:
  av_frame_free(&map);av_buffer_unref(&mapping);av_frame_free(&f);return 0;
 }
 return 0;
}
struct plane_result {uint64_t samples,different;unsigned maximum;int low_bits_zero;};
static struct plane_result compare(const AVFrame *a,const AVFrame *b,unsigned plane)
{
 struct plane_result r={0,0,0,1};int w,h;geometry(a,&w,&h);
 unsigned shift=plane?1:0,p=plane?1:0;w>>=shift;h>>=shift;
 for(int y=0;y<h;y++){
  const uint16_t *ar=(const void*)(a->data[p]+((a->crop_top>>shift)+y)*a->linesize[p]);
  const uint16_t *br=(const void*)(b->data[p]+((b->crop_top>>shift)+y)*b->linesize[p]);
  ar+=a->crop_left;br+=b->crop_left;
  for(int x=0;x<w;x++){
   unsigned at=plane?2*x+(plane==2):x;unsigned av=ar[at],bv=br[at];
   unsigned delta=(av>>6)>(bv>>6)?(av>>6)-(bv>>6):(bv>>6)-(av>>6);
   r.samples++;r.different+=av!=bv;if(delta>r.maximum)r.maximum=delta;if((av|bv)&63)r.low_bits_zero=0;
  }
 }
 return r;
}
static int raw_rpu_equal(const AVFrame *a,const AVFrame *b)
{
 const AVFrameSideData *ra=av_frame_get_side_data(a,AV_FRAME_DATA_DOVI_RPU_BUFFER),*rb=av_frame_get_side_data(b,AV_FRAME_DATA_DOVI_RPU_BUFFER);
 if(!ra||!rb)return !ra&&!rb;
 return ra->size==rb->size&&!memcmp(ra->data,rb->data,ra->size);
}
static int same_picture(const AVFrame *a,const AVFrame *b)
{
 int aw,ah,bw,bh;
 if(!buffers(a)||!buffers(b)||!geometry(a,&aw,&ah)||!geometry(b,&bw,&bh)||aw!=bw||ah!=bh||
    !props(a,b)||!yb_metadata_equal(a,b)||!raw_rpu_equal(a,b))return 0;
 for(unsigned p=0;p<3;p++){struct plane_result r=compare(a,b,p);if(!r.samples||r.different||!r.low_bits_zero)return 0;}
 return 1;
}
static int selected_pairs_equal(void)
{for(int i=0;i<N;i++)if(!same_picture(selected[0][i],selected[1][i]))return 0;return 1;}
static int read_held_owner(const AVFrame *reference,AVBufferRef *va)
{
 stage="retained_mapped_owner_readback";
 if(!held_owner||!held_owner->hw_frames_ctx||!held_owner->hw_frames_ctx->data||held_owner->format!=AV_PIX_FMT_VAAPI)return 0;
 AVHWFramesContext *pool=(void*)held_owner->hw_frames_ctx->data;
 if(pool->format!=AV_PIX_FMT_VAAPI||pool->sw_format!=AV_PIX_FMT_P010||pool->device_ctx!=(AVHWDeviceContext*)va->data)return 0;
 AVFrame *copy=av_frame_alloc();if(!copy)return 0;
 int ok=av_hwframe_transfer_data(copy,held_owner,0)>=0&&av_frame_copy_props(copy,held_owner)>=0&&same_picture(reference,copy);
 av_frame_free(&copy);return ok;
}
static int open_decoders(AVCodecContext **dec,const AVCodecParameters *par,AVBufferRef *va,AVBufferRef *qsv)
{
 for(unsigned route=0;route<2;route++){
  const AVCodec *codec=avcodec_find_decoder_by_name(route?"hevc_qsv":"hevc");
  dec[route]=avcodec_alloc_context3(codec);
  if(!codec||!dec[route]||avcodec_parameters_to_context(dec[route],par)<0)return 0;
  dec[route]->hw_device_ctx=av_buffer_ref(route?qsv:va);dec[route]->get_format=format;
  dec[route]->pkt_timebase=(AVRational){1,1000000};dec[route]->thread_count=1;
  AVDictionary *options=NULL;
  if(route){av_dict_set(&options,"dovi_metadata","1",0);av_dict_set(&options,"async_depth","1",0);}
  stage="decoder_open";int opened=avcodec_open2(dec[route],codec,&options);int unused=av_dict_count(options);av_dict_free(&options);
  if(opened<0||unused)return 0;
 }
 return 1;
}
static int open_scanner(AVBSFContext **bsf,struct yb_normalization *normal,const AVCodecParameters *par)
{
 stage="independent_scanner_bsf_init";
 const AVBitStreamFilter *filter=av_bsf_get_by_name("hevc_mp4toannexb");
 if(!filter||av_bsf_alloc(filter,bsf)<0||avcodec_parameters_copy((*bsf)->par_in,par)<0)return 0;
 (*bsf)->time_base_in=(AVRational){1,1000000};
 return av_bsf_init(*bsf)>=0&&par->extradata_size>=0&&(*bsf)->par_out->extradata_size>=0&&
    yb_normalization_init(normal,par->extradata,(size_t)par->extradata_size,(*bsf)->par_out->extradata,(size_t)(*bsf)->par_out->extradata_size);
}
static int feed_window(AVFormatContext *input,int stream,AVCodecContext **dec,AVBufferRef *va,AVBufferRef *qsv,
                       AVBSFContext *scanner_bsf,const struct yb_normalization *normal,AVPacket *packet)
{
 uint64_t reads=0,videos=0;
 while(reads<READ_LIMIT&&videos<VIDEO_LIMIT&&time(NULL)<deadline){
  stage="read_packet";int rr=av_read_frame(input,packet);if(rr<0)break;reads++;
  if(packet->stream_index!=stream){av_packet_unref(packet);continue;}videos++;
  if(packet->size<=0||!packet->data)return 0;
  if(lifecycle_enabled&&(packet->flags&AV_PKT_FLAG_DISCARD)){stage="unsupported_discard_picture_au";return 0;}
  stage="packet_timestamp_conversion";
  int64_t pts,dts;
  if(!timestamp(packet->pts,input->streams[stream]->time_base,input->start_time,&pts)||!timestamp(packet->dts,input->streams[stream]->time_base,input->start_time,&dts))return 0;
  stage="packet_duration_conversion";
  int64_t duration;
  if(!yb_duration_microseconds(packet->duration,input->streams[stream]->time_base,&duration))return 0;
  if(duration)positive_duration_packets++;else unknown_duration_packets++;
  packet->pts=pts;packet->dts=dts;packet->duration=duration;packet->time_base=(AVRational){1,1000000};
  if(lifecycle_enabled){
   stage="private_epoch_packet_identity";
   unsigned index=pair_state.event_count;if(index>=VIDEO_LIMIT||!packet_sha||!packet_identities)return 0;
   uint8_t digest[32];if(av_sha_init(packet_sha,256)<0)return 0;
   av_sha_update(packet_sha,packet->data,packet->size);av_sha_final(packet_sha,digest);
   if(!lifecycle_epoch){packet_identities[index]=(struct private_packet_identity){packet->pts,packet->dts,packet->duration,packet->size,{0}};memcpy(packet_identities[index].digest,digest,32);}
   else if(index>=fixed_window_packets||packet_identities[index].pts!=packet->pts||packet_identities[index].dts!=packet->dts||packet_identities[index].duration!=packet->duration||packet_identities[index].size!=packet->size||memcmp(packet_identities[index].digest,digest,32))return 0;
  }
  stage="private_literal_au_coverage";
  AVPacket *scanner_input=av_packet_clone(packet),*normalized=av_packet_alloc();
  if(!scanner_input||!normalized){av_packet_free(&scanner_input);av_packet_free(&normalized);return 0;}
  int normalization_ok=av_bsf_send_packet(scanner_bsf,scanner_input)>=0&&av_bsf_receive_packet(scanner_bsf,normalized)==0;
  av_packet_free(&scanner_input);struct yb_au_coverage coverage;
  stage="scanner_bsf_output";
  if(!normalization_ok){av_packet_free(&normalized);return 0;}
  stage="scanner_packet_properties";
  if(normalized->pts!=packet->pts||normalized->dts!=packet->dts||normalized->duration!=packet->duration){av_packet_free(&normalized);return 0;}
  stage="literal_packet_normalization";
  if(!yb_literal_normalized(normal,packet->data,(size_t)packet->size,normalized->data,(size_t)normalized->size)){av_packet_free(&normalized);return 0;}
  stage="literal_au_header_admission";
  if(!yb_scan_au(normalized->data,(size_t)normalized->size,&coverage)){av_packet_free(&normalized);return 0;}
  stage="au_event_registration";
  if(!yb_record_event(&pair_state,packet->pts,packet->duration,coverage)){av_packet_free(&normalized);return 0;}
  stage="scanner_surplus_output";
  av_packet_unref(normalized);int surplus=av_bsf_receive_packet(scanner_bsf,normalized);av_packet_free(&normalized);
  if(surplus!=AVERROR(EAGAIN))return 0;
  for(unsigned route=0;route<2;route++){
   AVPacket *copy=av_packet_clone(packet);if(!copy)return 0;
   if(copy->size!=packet->size||memcmp(copy->data,packet->data,packet->size)){av_packet_free(&copy);return 0;}
   stage="send_packet";int sent=avcodec_send_packet(dec[route],copy);
   if(sent==AVERROR(EAGAIN)){if(!drain(dec[route],route,va,qsv)){av_packet_free(&copy);return 0;}sent=avcodec_send_packet(dec[route],copy);}
   av_packet_free(&copy);if(sent<0)return 0;submitted[route]++;
   if(!drain(dec[route],route,va,qsv))return 0;
  }
  av_packet_unref(packet);
  int complete=1;for(unsigned route=0;route<2;route++)for(int i=0;i<N;i++)complete&=selected[route][i]!=NULL;
  if(lifecycle_enabled&&lifecycle_epoch){if(videos==fixed_window_packets)return 1;}
  else if(complete)return 1;
 }
 return 0;
}
static int window_accounted(const struct yb_pair_state *s,const uint64_t accepted[2],const int end[2])
{
 if(s->dts.observed!=s->paired||s->dts.equal+s->dts.different!=s->dts.observed)return 0;
 if(!s->event_count||end[0]!=AVERROR_EOF||end[1]!=AVERROR_EOF||accepted[0]!=s->event_count||accepted[1]!=s->event_count||
    s->paired!=s->event_count||s->snapshot_count||s->snapshot_bytes)return 0;
 for(unsigned i=0;i<s->event_count;i++)if(s->events[i].decoded_mask!=3)return 0;
 return 1;
}
static int finish_window(AVCodecContext **dec,AVBufferRef *va,AVBufferRef *qsv)
{
 for(unsigned route=0;route<2;route++){
  int accepted=0;
  for(unsigned step=0;step<8&&time(NULL)<deadline;step++){
   stage="controlled_window_send_null";int sent=avcodec_send_packet(dec[route],NULL);
   if(sent==0){accepted=1;break;}
   if(sent!=AVERROR(EAGAIN)||!drain(dec[route],route,va,qsv))return 0;
  }
  if(!accepted)return 0;
  for(unsigned step=0;step<8&&time(NULL)<deadline;step++){
   stage="controlled_window_receive_to_eof";
   if(!drain(dec[route],route,va,qsv))return 0;
   if(receive_end[route]==AVERROR_EOF)break;
  }
  if(receive_end[route]!=AVERROR_EOF)return 0;
 }
 stage="controlled_window_accounting";return window_accounted(&pair_state,submitted,receive_end);
}
struct lifecycle_result {uint64_t accepted[2],returned[2],paired,without_rpu,new_rpu,previous_rpu;int eof[2],owner_readback_equal,pictures_equal;};
static void save_lifecycle_result(struct lifecycle_result *r)
{
 r->accepted[0]=submitted[0];r->accepted[1]=submitted[1];r->returned[0]=frames_seen[0];r->returned[1]=frames_seen[1];
 r->paired=pair_state.paired;r->without_rpu=pair_state.without_rpu;r->new_rpu=pair_state.new_rpu;r->previous_rpu=pair_state.previous_rpu;
 r->eof[0]=receive_end[0]==AVERROR_EOF;r->eof[1]=receive_end[1]==AVERROR_EOF;
}
static void clear_epoch(void)
{
 for(unsigned route=0;route<2;route++)for(int i=0;i<N;i++)av_frame_free(&selected[route][i]);
 yb_pairs_clear(&pair_state);memset(&pair_state,0,sizeof(pair_state));
 memset(submitted,0,sizeof(submitted));memset(frames_seen,0,sizeof(frames_seen));memset(receive_end,0,sizeof(receive_end));mapped=0;
 positive_duration_packets=unknown_duration_packets=0;
}
int main(int argc,char **argv)
{
 /* argv: private MKV path, render node, seek microseconds, three exact targets.
  * Launcher captures all decoder stderr privately; no default AV log output. */
 av_log_set_level(AV_LOG_QUIET);
 AVFormatContext *input=NULL;AVCodecContext *dec[2]={0};AVBufferRef *va=NULL,*qsv=NULL;
 AVBSFContext *scanner_bsf=NULL;struct yb_normalization normalization={0};
 AVCodecParameters *frozen_par=NULL;AVFrame *baseline[N]={0};
 struct lifecycle_result epochs[3]={0};unsigned epochs_completed=0;
 AVPacket *packet=av_packet_alloc();struct stat before,after;int success=0,stream=-1,reported=0;
 int64_t seek=0;deadline=time(NULL)+170;
 const char *lifecycle=getenv("YB_BL_PROBE_LIFECYCLE");
 if(lifecycle&&strcmp(lifecycle,"0")&&strcmp(lifecycle,"1"))goto done;
 lifecycle_enabled=lifecycle&&!strcmp(lifecycle,"1");
 if(lifecycle_enabled){stage="picture_transport_v2_lifecycle_not_qualified";goto done;}
 if(lifecycle_enabled){packet_sha=av_sha_alloc();packet_identities=av_calloc(VIDEO_LIMIT,sizeof(*packet_identities));if(!packet_sha||!packet_identities)goto done;}
 if(argc!=7||!packet||stat(argv[1],&before))goto done;
 for(int i=0;i<4;i++){char *end=NULL;errno=0;int64_t v=strtoll(argv[i+3],&end,10);if(errno||!*argv[i+3]||*end||v<0)goto done;if(i)targets[i-1]=v;else seek=v;}
 if(!(targets[0]<targets[1]&&targets[1]<targets[2])||seek>targets[0])goto done;
 stage="demux_open";
 if(avformat_open_input(&input,argv[1],NULL,NULL)<0||avformat_find_stream_info(input,NULL)<0||!input->iformat||!input->iformat->name||!strstr(input->iformat->name,"matroska"))goto done;
 stream=av_find_best_stream(input,AVMEDIA_TYPE_VIDEO,-1,-1,NULL,0);
 if(stream<0||input->streams[stream]->codecpar->codec_id!=AV_CODEC_ID_HEVC)goto done;
 const AVCodecParameters *par=input->streams[stream]->codecpar;
 const AVPacketSideData *config=av_packet_side_data_get(par->coded_side_data,par->nb_coded_side_data,AV_PKT_DATA_DOVI_CONF);
 if(!config||!config->data||config->size<sizeof(AVDOVIDecoderConfigurationRecord))goto done;
 const AVDOVIDecoderConfigurationRecord *dv=(const void*)config->data;
 if(dv->dv_profile!=7||!dv->rpu_present_flag||!dv->el_present_flag||!dv->bl_present_flag)goto done;
 if(lifecycle_enabled){frozen_par=avcodec_parameters_alloc();if(!frozen_par||avcodec_parameters_copy(frozen_par,par)<0)goto done;}
 if(!open_scanner(&scanner_bsf,&normalization,par))goto done;
 for(unsigned i=0;i<input->nb_streams;i++)input->streams[i]->discard=i==(unsigned)stream?AVDISCARD_DEFAULT:AVDISCARD_ALL;
 stage="devices";
 if(av_hwdevice_ctx_create(&va,AV_HWDEVICE_TYPE_VAAPI,argv[2],NULL,0)<0||av_hwdevice_ctx_create_derived(&qsv,AV_HWDEVICE_TYPE_QSV,va,0)<0)goto done;
 if(!open_decoders(dec,par,va,qsv))goto done;
 stage="seek";int64_t offset=input->start_time==AV_NOPTS_VALUE?0:input->start_time;
 if((offset>0&&seek>INT64_MAX-offset)||(offset<0&&seek<INT64_MIN-offset))goto done;
 int64_t absolute=seek+offset;
 if(av_seek_frame(input,-1,absolute,AVSEEK_FLAG_BACKWARD)<0)goto done;
 success=feed_window(input,stream,dec,va,qsv,scanner_bsf,&normalization,packet);
 if(success&&!lifecycle_enabled&&!finish_window(dec,va,qsv))success=0;
 if(!success)goto done;
 stage="compare";
 if(mapped<N||submitted[0]!=submitted[1]){success=0;goto done;}
 for(int i=0;i<N;i++){
  unsigned e;for(e=0;e<pair_state.event_count;e++)if(pair_state.events[e].pts==targets[i])break;
  if(e==pair_state.event_count||pair_state.events[e].decoded_mask!=3)success=0;
 }
 for(int i=0;i<N;i++)if(!picture_props(selected[0][i],selected[1][i])||!yb_metadata_equal(selected[0][i],selected[1][i])||!raw_rpu_equal(selected[0][i],selected[1][i]))success=0;
 if(lifecycle_enabled){
  stage="lifecycle_initial_picture_equality";
  if(!success||!selected_pairs_equal()){success=0;goto done;}
  if(!finish_window(dec,va,qsv)){success=0;goto done;}
  fixed_window_packets=pair_state.event_count;
  for(int i=0;i<N;i++){baseline[i]=av_frame_clone(selected[0][i]);if(!baseline[i]){success=0;goto done;}}
  if(!read_held_owner(baseline[0],va)){success=0;goto done;}
  save_lifecycle_result(&epochs[0]);epochs[0].pictures_equal=epochs[0].owner_readback_equal=1;epochs_completed=1;
  for(lifecycle_epoch=1;lifecycle_epoch<3;lifecycle_epoch++){
   clear_epoch();av_packet_unref(packet);
   if(lifecycle_epoch==1){
    stage="lifecycle_flush_decoders";avcodec_flush_buffers(dec[0]);avcodec_flush_buffers(dec[1]);
   }else{
    stage="lifecycle_close_decoders";avcodec_free_context(&dec[0]);avcodec_free_context(&dec[1]);
    /* An AVFrame ref is not assumed to pin an MFX mid allocation. This actual
     * direct-mapped readback tests that hazard; failure remains unqualified. */
    if(!read_held_owner(baseline[0],va)||!open_decoders(dec,frozen_par,va,qsv)){success=0;goto done;}
   }
   stage="lifecycle_reset_normalization_epoch";av_bsf_flush(scanner_bsf);av_bsf_free(&scanner_bsf);yb_normalization_clear(&normalization);
   if(!open_scanner(&scanner_bsf,&normalization,frozen_par)||!read_held_owner(baseline[0],va)){success=0;goto done;}
   stage="lifecycle_reseek_same_input";
   if(av_seek_frame(input,-1,absolute,AVSEEK_FLAG_BACKWARD)<0||
      !feed_window(input,stream,dec,va,qsv,scanner_bsf,&normalization,packet)||!finish_window(dec,va,qsv)){
    success=0;goto done;
   }
   stage="lifecycle_epoch_picture_equality";
   if(!selected_pairs_equal()){success=0;goto done;}
   for(int i=0;i<N;i++)for(unsigned route=0;route<2;route++)if(!same_picture(baseline[i],selected[route][i]))success=0;
   if(!success||!read_held_owner(baseline[0],va)){success=0;goto done;}
   save_lifecycle_result(&epochs[lifecycle_epoch]);epochs[lifecycle_epoch].pictures_equal=epochs[lifecycle_epoch].owner_readback_equal=1;epochs_completed++;
  }
 }
 if(stat(argv[1],&after)||!same_source(&before,&after))success=0;
 reported=1;
 printf("{\"scope\":\"three raw BL frames and independent native HEVC Dolby metadata only; not Kodi or performance\",\"packet_clone_identity_verified\":true,\"submitted_packets_equal\":%s,\"frames\":[",submitted[0]==submitted[1]?"true":"false");
 for(int i=0;i<N;i++){
  int aw,ah,bw,bh;int safe=geometry(selected[0][i],&aw,&ah)&&geometry(selected[1][i],&bw,&bh)&&aw==bw&&ah==bh;
  printf("%s{\"pts_microseconds\":%"PRId64",\"legacy_all_properties_equal\":%s,\"picture_properties_equal\":%s,\"transport_pkt_dts_equal\":%s,\"resolved_dolby_metadata_equal\":%s,\"raw_rpu_presence_and_bytes_equal\":%s,\"reference_raw_rpu_present\":%s,\"candidate_raw_rpu_present\":%s,\"sample_comparison_completed\":%s,\"planes\":[",i?",":"",targets[i],props(selected[0][i],selected[1][i])?"true":"false",picture_props(selected[0][i],selected[1][i])?"true":"false",selected[0][i]->pkt_dts==selected[1][i]->pkt_dts?"true":"false",yb_metadata_equal(selected[0][i],selected[1][i])?"true":"false",raw_rpu_equal(selected[0][i],selected[1][i])?"true":"false",av_frame_get_side_data(selected[0][i],AV_FRAME_DATA_DOVI_RPU_BUFFER)?"true":"false",av_frame_get_side_data(selected[1][i],AV_FRAME_DATA_DOVI_RPU_BUFFER)?"true":"false",safe?"true":"false");
  for(unsigned p=0;p<3;p++){struct plane_result r=safe?compare(selected[0][i],selected[1][i],p):(struct plane_result){0,0,0,0};if(r.different||!r.low_bits_zero)success=0;printf("%s{\"plane\":\"%c\",\"sample_count\":%"PRIu64",\"differing_uint16_samples\":%"PRIu64",\"maximum_absolute_sample_codes\":%u,\"p010_low_bits_zero\":%s}",p?",":"","YUV"[p],r.samples,r.different,r.maximum,r.low_bits_zero?"true":"false");}
  printf("]}");
 }
 printf("],\"decoded_pair_coverage\":{\"paired_frames\":%"PRIu64",\"without_rpu\":%"PRIu64",\"new_rpu\":%"PRIu64",\"previous_rpu\":%"PRIu64",\"multiple_rpu_aus\":%"PRIu64",\"pending_unpaired_snapshots\":%u,\"previous_reference_validity_scope\":\"independent native decoder resolution, not header classifier\"}",pair_state.paired,pair_state.without_rpu,pair_state.new_rpu,pair_state.previous_rpu,pair_state.duplicate_rpu_aus,pair_state.snapshot_count);
 if(lifecycle_enabled){
  printf(",\"controlled_packet_window_lifecycle\":{\"full_film_eof\":false,\"epochs_completed\":%u,\"mapped_owners_retained\":1,\"private_packet_digest_sequence_equal\":true,\"epochs\":[",epochs_completed);
  for(unsigned e=0;e<epochs_completed;e++)printf("%s{\"epoch\":%u,\"accepted_aus\":[%"PRIu64",%"PRIu64"],\"returned_frames\":[%"PRIu64",%"PRIu64"],\"paired_instructions\":%"PRIu64",\"receive_eof\":[%s,%s],\"target_pictures_equal\":%s,\"retained_owner_readback_equal\":%s}",e?",":"",e,epochs[e].accepted[0],epochs[e].accepted[1],epochs[e].returned[0],epochs[e].returned[1],epochs[e].paired,epochs[e].eof[0]?"true":"false",epochs[e].eof[1]?"true":"false",epochs[e].pictures_equal?"true":"false",epochs[e].owner_readback_equal?"true":"false");
  printf("]}");
 }
 printf(",\"comparison_contract\":\"picture-association.v2\",\"transport_pkt_dts\":{\"qualifies_picture\":false,\"observed_pairs\":%"PRIu64",\"equal_pairs\":%"PRIu64",\"different_pairs\":%"PRIu64",\"reference_unknown\":%"PRIu64",\"candidate_unknown\":%"PRIu64",\"both_unknown\":%"PRIu64",\"known_pairs\":%"PRIu64",\"max_absolute_route_delta_us\":%"PRIu64",\"max_absolute_reference_minus_pts_us\":%"PRIu64",\"max_absolute_candidate_minus_pts_us\":%"PRIu64"}",pair_state.dts.observed,pair_state.dts.equal,pair_state.dts.different,pair_state.dts.reference_unknown,pair_state.dts.candidate_unknown,pair_state.dts.both_unknown,pair_state.dts.known,pair_state.dts.max_route_delta,pair_state.dts.max_reference_pts_delta,pair_state.dts.max_candidate_pts_delta);
 printf(",\"source_packet_duration\":{\"positive_packets\":%"PRIu64",\"unknown_zero_packets\":%"PRIu64",\"returned_frames_bound_to_au_duration\":true}",positive_duration_packets,unknown_duration_packets);
 if(!lifecycle_enabled)printf(",\"controlled_packet_window\":{\"full_film_eof\":false,\"accepted_aus\":[%"PRIu64",%"PRIu64"],\"returned_frames\":[%"PRIu64",%"PRIu64"],\"event_count\":%u,\"receive_eof\":[%s,%s],\"complete_event_pairs\":%s}",submitted[0],submitted[1],frames_seen[0],frames_seen[1],pair_state.event_count,receive_end[0]==AVERROR_EOF?"true":"false",receive_end[1]==AVERROR_EOF?"true":"false",window_accounted(&pair_state,submitted,receive_end)?"true":"false");
 printf(",\"pass\":%s}\n",success?"true":"false");
done:
 if(!reported){
 printf("{\"scope\":\"raw BL diagnostic, no quality or performance qualification\",\"pass\":false,\"failure_stage\":\"%s\",\"submitted_packets\":[%"PRIu64",%"PRIu64"],\"decoded_frames\":[%"PRIu64",%"PRIu64"],\"matched_metadata_pairs\":%"PRIu64",\"pair_rejection\":{\"reason\":%u,\"route\":%u,\"expected_duration\":%"PRId64",\"observed_duration\":%"PRId64",\"metadata_equal\":%s,\"raw_rpu_equal\":%s,\"property_equal\":{",stage,submitted[0],submitted[1],frames_seen[0],frames_seen[1],pair_state.paired,pair_state.diagnostic.reason,pair_state.diagnostic.route,pair_state.diagnostic.expected_duration,pair_state.diagnostic.observed_duration,pair_state.diagnostic.metadata_equal?"true":"false",pair_state.diagnostic.raw_equal?"true":"false");
 static const char *names[]={"active_geometry","crop_left","crop_top","pts","best_effort_timestamp","duration","time_base","pkt_dts","sample_aspect_ratio","flags","repeat_pict","pict_type","chroma_location","color_range","color_primaries","color_trc","colorspace"};
 for(unsigned i=0;i<sizeof(names)/sizeof(*names);i++)printf("%s\"%s\":%s",i?",":"",names[i],pair_state.diagnostic.property_mask&(UINT32_C(1)<<i)?"true":"false");
 uint32_t ref_flags=pair_state.diagnostic.reference_flags,cand_flags=pair_state.diagnostic.candidate_flags,changed=ref_flags^cand_flags;
 printf("},\"comparison_evaluated\":%s,\"reference_flags\":%"PRIu32",\"candidate_flags\":%"PRIu32",\"flags_xor\":%"PRIu32",\"changed_known_flags\":{",pair_state.diagnostic.reason==10?"true":"false",ref_flags,cand_flags,changed);
 static const char *flag_names[]={"corrupt","key","discard","interlaced","top_field_first","lossless"};
 static const uint32_t flag_bits[]={AV_FRAME_FLAG_CORRUPT,AV_FRAME_FLAG_KEY,AV_FRAME_FLAG_DISCARD,AV_FRAME_FLAG_INTERLACED,AV_FRAME_FLAG_TOP_FIELD_FIRST,AV_FRAME_FLAG_LOSSLESS};
 uint32_t known=0;
 for(unsigned i=0;i<sizeof(flag_bits)/sizeof(*flag_bits);i++){known|=flag_bits[i];printf("%s\"%s\":%s",i?",":"",flag_names[i],changed&flag_bits[i]?"true":"false");}
 printf("},\"unknown_changed_flag_bits\":%"PRIu32",\"reference_geometry\":",changed&~known);print_geometry_observation(&pair_state.diagnostic.reference_geometry);
 printf(",\"candidate_geometry\":");print_geometry_observation(&pair_state.diagnostic.candidate_geometry);printf("}}\n");
 }
 if(!success)fprintf(stderr,"BL diagnostic failure stage: %s\n",stage);
 for(unsigned route=0;route<2;route++){for(int i=0;i<N;i++)av_frame_free(&selected[route][i]);avcodec_free_context(&dec[route]);}
 av_buffer_unref(&qsv);av_buffer_unref(&va);av_packet_free(&packet);avformat_close_input(&input);
 yb_pairs_clear(&pair_state);av_bsf_free(&scanner_bsf);yb_normalization_clear(&normalization);
 for(int i=0;i<N;i++)av_frame_free(&baseline[i]);
 av_frame_free(&held_owner);avcodec_parameters_free(&frozen_par);av_freep(&packet_sha);av_freep(&packet_identities);
 return success?0:1;
}
