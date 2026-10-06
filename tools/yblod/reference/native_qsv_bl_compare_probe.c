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
enum { N=3, VIDEO_LIMIT=4096, READ_LIMIT=65536 };
static const char *stage="preflight";
static time_t deadline;
static int64_t targets[N];
static uint64_t submitted[2], mapped, frames_seen[2];
static AVFrame *selected[2][N];
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
 int w,h;if(f->format!=AV_PIX_FMT_P010||!geometry(f,&w,&h))return 0;
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
#include "native_qsv_bl_pair_coverage.h"
static struct yb_pair_state pair_state;
static int drain(AVCodecContext *decoder,unsigned route,AVBufferRef *va,AVBufferRef *qsv)
{
 for(unsigned bounded=0;bounded<128;bounded++){
  AVFrame *f=av_frame_alloc();if(!f)return 0;
  stage="receive_frame";int result=avcodec_receive_frame(decoder,f);
  if(result==AVERROR(EAGAIN)||result==AVERROR_EOF){av_frame_free(&f);return 1;}
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
  if(route&&mapped==1){stage="live_identity_before_readback";if(!qsv_probe_handshake(deadline))goto frame_fail;}
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
int main(int argc,char **argv)
{
 /* argv: private MKV path, render node, seek microseconds, three exact targets.
  * Launcher captures all decoder stderr privately; no default AV log output. */
 av_log_set_level(AV_LOG_QUIET);
 AVFormatContext *input=NULL;AVCodecContext *dec[2]={0};AVBufferRef *va=NULL,*qsv=NULL;
 AVBSFContext *scanner_bsf=NULL;struct yb_normalization normalization={0};
 AVPacket *packet=av_packet_alloc();struct stat before,after;int success=0,stream=-1,reported=0;
 uint64_t reads=0,videos=0;int64_t seek=0;deadline=time(NULL)+170;
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
 stage="independent_scanner_bsf_init";
 if(av_bsf_alloc(av_bsf_get_by_name("hevc_mp4toannexb"),&scanner_bsf)<0||avcodec_parameters_copy(scanner_bsf->par_in,par)<0)goto done;
 scanner_bsf->time_base_in=(AVRational){1,1000000};
 if(av_bsf_init(scanner_bsf)<0||par->extradata_size<0||scanner_bsf->par_out->extradata_size<0||
    !yb_normalization_init(&normalization,par->extradata,(size_t)par->extradata_size,scanner_bsf->par_out->extradata,(size_t)scanner_bsf->par_out->extradata_size))goto done;
 for(unsigned i=0;i<input->nb_streams;i++)input->streams[i]->discard=i==(unsigned)stream?AVDISCARD_DEFAULT:AVDISCARD_ALL;
 stage="devices";
 if(av_hwdevice_ctx_create(&va,AV_HWDEVICE_TYPE_VAAPI,argv[2],NULL,0)<0||av_hwdevice_ctx_create_derived(&qsv,AV_HWDEVICE_TYPE_QSV,va,0)<0)goto done;
 for(unsigned route=0;route<2;route++){
  const AVCodec *codec=avcodec_find_decoder_by_name(route?"hevc_qsv":"hevc");
  dec[route]=avcodec_alloc_context3(codec);
  if(!codec||!dec[route]||avcodec_parameters_to_context(dec[route],input->streams[stream]->codecpar)<0)goto done;
  dec[route]->hw_device_ctx=av_buffer_ref(route?qsv:va);dec[route]->get_format=format;
  dec[route]->pkt_timebase=(AVRational){1,1000000};dec[route]->thread_count=1;
  AVDictionary *options=NULL;
  if(route){av_dict_set(&options,"dovi_metadata","1",0);av_dict_set(&options,"async_depth","1",0);}
  stage="decoder_open";int opened=avcodec_open2(dec[route],codec,&options);int unused=av_dict_count(options);av_dict_free(&options);
  if(opened<0||unused)goto done;
 }
 stage="seek";int64_t offset=input->start_time==AV_NOPTS_VALUE?0:input->start_time;
 if((offset>0&&seek>INT64_MAX-offset)||(offset<0&&seek<INT64_MIN-offset))goto done;
 int64_t absolute=seek+offset;
 if(av_seek_frame(input,-1,absolute,AVSEEK_FLAG_BACKWARD)<0)goto done;
 while(reads<READ_LIMIT&&videos<VIDEO_LIMIT&&time(NULL)<deadline){
  stage="read_packet";int rr=av_read_frame(input,packet);if(rr<0)break;reads++;
  if(packet->stream_index!=stream){av_packet_unref(packet);continue;}videos++;
  if(packet->size<=0||!packet->data)goto done;
  int64_t pts,dts;
  if(!timestamp(packet->pts,input->streams[stream]->time_base,input->start_time,&pts)||!timestamp(packet->dts,input->streams[stream]->time_base,input->start_time,&dts))goto done;
  packet->pts=pts;packet->dts=dts;packet->duration=0;packet->time_base=(AVRational){1,1000000};
  stage="private_literal_au_coverage";
  AVPacket *scanner_input=av_packet_clone(packet),*normalized=av_packet_alloc();
  if(!scanner_input||!normalized){av_packet_free(&scanner_input);av_packet_free(&normalized);goto done;}
  int normalization_ok=av_bsf_send_packet(scanner_bsf,scanner_input)>=0&&av_bsf_receive_packet(scanner_bsf,normalized)==0;
  av_packet_free(&scanner_input);
  struct yb_au_coverage coverage;
  if(!normalization_ok||normalized->pts!=packet->pts||normalized->dts!=packet->dts||normalized->duration!=packet->duration||
     !yb_literal_normalized(&normalization,packet->data,(size_t)packet->size,normalized->data,(size_t)normalized->size)||
     !yb_scan_au(normalized->data,(size_t)normalized->size,&coverage)||!yb_record_event(&pair_state,packet->pts,coverage)){
   av_packet_free(&normalized);goto done;
  }
  av_packet_unref(normalized);int surplus=av_bsf_receive_packet(scanner_bsf,normalized);av_packet_free(&normalized);
  if(surplus!=AVERROR(EAGAIN))goto done;
  for(unsigned route=0;route<2;route++){
   AVPacket *copy=av_packet_clone(packet);if(!copy)goto done;
   /* Private literal packet identity, no exported content hash. */
   if(copy->size!=packet->size||memcmp(copy->data,packet->data,packet->size)){av_packet_free(&copy);goto done;}
   stage="send_packet";int sent=avcodec_send_packet(dec[route],copy);
   if(sent==AVERROR(EAGAIN)){if(!drain(dec[route],route,va,qsv)){av_packet_free(&copy);goto done;}sent=avcodec_send_packet(dec[route],copy);}
   av_packet_free(&copy);if(sent<0)goto done;submitted[route]++;
   if(!drain(dec[route],route,va,qsv))goto done;
  }
  av_packet_unref(packet);
  int complete=1;for(unsigned route=0;route<2;route++)for(int i=0;i<N;i++)complete&=selected[route][i]!=NULL;
  if(complete){success=1;break;}
 }
 stage="compare";
 if(!success||mapped<N||submitted[0]!=submitted[1]){success=0;goto done;}
 for(int i=0;i<N;i++){
  unsigned e;for(e=0;e<pair_state.event_count;e++)if(pair_state.events[e].pts==targets[i])break;
  if(e==pair_state.event_count||pair_state.events[e].decoded_mask!=3)success=0;
 }
 for(int i=0;i<N;i++)if(!props(selected[0][i],selected[1][i])||!yb_metadata_equal(selected[0][i],selected[1][i])||!raw_rpu_equal(selected[0][i],selected[1][i]))success=0;
 if(stat(argv[1],&after)||!same_source(&before,&after))success=0;
 reported=1;
 printf("{\"scope\":\"three raw BL frames and independent native HEVC Dolby metadata only; not Kodi or performance\",\"packet_clone_identity_verified\":true,\"submitted_packets_equal\":%s,\"frames\":[",submitted[0]==submitted[1]?"true":"false");
 for(int i=0;i<N;i++){
  int aw,ah,bw,bh;int safe=geometry(selected[0][i],&aw,&ah)&&geometry(selected[1][i],&bw,&bh)&&aw==bw&&ah==bh;
  printf("%s{\"pts_microseconds\":%"PRId64",\"properties_equal\":%s,\"resolved_dolby_metadata_equal\":%s,\"raw_rpu_presence_and_bytes_equal\":%s,\"reference_raw_rpu_present\":%s,\"candidate_raw_rpu_present\":%s,\"sample_comparison_completed\":%s,\"planes\":[",i?",":"",targets[i],props(selected[0][i],selected[1][i])?"true":"false",yb_metadata_equal(selected[0][i],selected[1][i])?"true":"false",raw_rpu_equal(selected[0][i],selected[1][i])?"true":"false",av_frame_get_side_data(selected[0][i],AV_FRAME_DATA_DOVI_RPU_BUFFER)?"true":"false",av_frame_get_side_data(selected[1][i],AV_FRAME_DATA_DOVI_RPU_BUFFER)?"true":"false",safe?"true":"false");
  for(unsigned p=0;p<3;p++){struct plane_result r=safe?compare(selected[0][i],selected[1][i],p):(struct plane_result){0,0,0,0};if(r.different||!r.low_bits_zero)success=0;printf("%s{\"plane\":\"%c\",\"sample_count\":%"PRIu64",\"differing_uint16_samples\":%"PRIu64",\"maximum_absolute_sample_codes\":%u,\"p010_low_bits_zero\":%s}",p?",":"","YUV"[p],r.samples,r.different,r.maximum,r.low_bits_zero?"true":"false");}
  printf("]}");
 }
 printf("],\"decoded_pair_coverage\":{\"paired_frames\":%"PRIu64",\"without_rpu\":%"PRIu64",\"new_rpu\":%"PRIu64",\"previous_rpu\":%"PRIu64",\"multiple_rpu_aus\":%"PRIu64",\"pending_unpaired_snapshots\":%u,\"previous_reference_validity_scope\":\"independent native decoder resolution, not header classifier\"},\"pass\":%s}\n",pair_state.paired,pair_state.without_rpu,pair_state.new_rpu,pair_state.previous_rpu,pair_state.duplicate_rpu_aus,pair_state.snapshot_count,success?"true":"false");
done:
 if(!reported)printf("{\"scope\":\"raw BL diagnostic, no quality or performance qualification\",\"pass\":false,\"failure_stage\":\"%s\",\"submitted_packets\":[%"PRIu64",%"PRIu64"],\"decoded_frames\":[%"PRIu64",%"PRIu64"],\"matched_metadata_pairs\":%"PRIu64"}\n",stage,submitted[0],submitted[1],frames_seen[0],frames_seen[1],pair_state.paired);
 if(!success)fprintf(stderr,"BL diagnostic failure stage: %s\n",stage);
 for(unsigned route=0;route<2;route++){for(int i=0;i<N;i++)av_frame_free(&selected[route][i]);avcodec_free_context(&dec[route]);}
 av_buffer_unref(&qsv);av_buffer_unref(&va);av_packet_free(&packet);avformat_close_input(&input);
 yb_pairs_clear(&pair_state);av_bsf_free(&scanner_bsf);yb_normalization_clear(&normalization);
 return success?0:1;
}
