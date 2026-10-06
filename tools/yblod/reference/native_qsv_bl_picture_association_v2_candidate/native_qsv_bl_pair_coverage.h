/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Source-only diagnostic integration. CPU property snapshots never retain a
 * decoded pixel plane or hw_frames_ctx. Private AU events/IDs are not exported. */
#ifndef YB_BL_PAIR_COVERAGE_H
#define YB_BL_PAIR_COVERAGE_H
#include <libavutil/dict.h>
#include "native_qsv_bl_rpu_coverage.h"
enum { YB_EVENT_MAX=4096,YB_SNAPSHOT_MAX=64,YB_SNAPSHOT_BYTES=4*1024*1024,YB_FRAME_SIDEBYTES=1024*1024 };
struct yb_event {int64_t pts,duration;struct yb_au_coverage coverage;unsigned decoded_mask;};
struct yb_geometry_observation {int width,height,pool_width,pool_height,pool_observed,pool_p010,pool_covers,zero_crop_shape;size_t crop_left,crop_top,crop_right,crop_bottom;};
static struct yb_geometry_observation yb_geometry_observe(const AVFrame *f)
{
 struct yb_geometry_observation g={.width=f->width,.height=f->height,.crop_left=f->crop_left,.crop_top=f->crop_top,.crop_right=f->crop_right,.crop_bottom=f->crop_bottom};
 if(f->hw_frames_ctx&&f->hw_frames_ctx->data&&f->hw_frames_ctx->size>=sizeof(AVHWFramesContext)){
  const AVHWFramesContext *p=(const void*)f->hw_frames_ctx->data;
  g.pool_observed=1;g.pool_width=p->width;g.pool_height=p->height;g.pool_p010=p->sw_format==AV_PIX_FMT_P010;
  g.pool_covers=p->width>=f->width&&p->height>=f->height;
 }
 g.zero_crop_shape=g.pool_observed&&g.pool_p010&&g.pool_covers&&f->width>0&&f->height>0&&f->width<=8192&&f->height<=8192&&
  !(f->flags&AV_FRAME_FLAG_INTERLACED)&&!f->crop_left&&!f->crop_top&&!f->crop_right&&!f->crop_bottom;
 return g;
}
struct yb_snapshot {int64_t pts;AVFrame *frame;unsigned route;size_t bytes;struct yb_geometry_observation geometry;};
struct yb_pair_diagnostic {unsigned reason,route;uint32_t property_mask;int metadata_equal,raw_equal;int64_t expected_duration,observed_duration;uint32_t reference_flags,candidate_flags;struct yb_geometry_observation reference_geometry,candidate_geometry;};
struct yb_dts_observations {uint64_t observed,equal,different,reference_unknown,candidate_unknown,both_unknown,known,max_route_delta,max_reference_pts_delta,max_candidate_pts_delta;};
static uint64_t yb_absolute_timestamp_delta(int64_t a,int64_t b){__int128 d=(__int128)a-b;return (uint64_t)(d<0?-d:d);}
static void yb_observe_transport_dts(struct yb_dts_observations *s,const AVFrame *a,const AVFrame *b){
 s->observed++;if(a->pkt_dts==b->pkt_dts)s->equal++;else s->different++;
 if(a->pkt_dts==AV_NOPTS_VALUE)s->reference_unknown++;
 if(b->pkt_dts==AV_NOPTS_VALUE)s->candidate_unknown++;
 if(a->pkt_dts==AV_NOPTS_VALUE&&b->pkt_dts==AV_NOPTS_VALUE)s->both_unknown++;
 if(a->pkt_dts!=AV_NOPTS_VALUE&&b->pkt_dts!=AV_NOPTS_VALUE){s->known++;uint64_t d=yb_absolute_timestamp_delta(a->pkt_dts,b->pkt_dts);if(d>s->max_route_delta)s->max_route_delta=d;}
 if(a->pkt_dts!=AV_NOPTS_VALUE){uint64_t d=yb_absolute_timestamp_delta(a->pkt_dts,a->pts);if(d>s->max_reference_pts_delta)s->max_reference_pts_delta=d;}
 if(b->pkt_dts!=AV_NOPTS_VALUE){uint64_t d=yb_absolute_timestamp_delta(b->pkt_dts,b->pts);if(d>s->max_candidate_pts_delta)s->max_candidate_pts_delta=d;}
}
struct yb_pair_state {
 struct yb_dts_observations dts;
 struct yb_pair_diagnostic diagnostic;
 struct yb_event events[YB_EVENT_MAX];unsigned event_count;
 struct yb_snapshot snapshots[YB_SNAPSHOT_MAX];unsigned snapshot_count;size_t snapshot_bytes;
 uint64_t paired,without_rpu,new_rpu,previous_rpu,duplicate_rpu_aus;
};
static int yb_record_event(struct yb_pair_state *s,int64_t pts,int64_t duration,struct yb_au_coverage c)
{
 if(!s||pts==AV_NOPTS_VALUE||duration<0||s->event_count==YB_EVENT_MAX)return 0;
 for(unsigned i=0;i<s->event_count;i++)if(s->events[i].pts==pts)return 0;
 s->events[s->event_count++]=(struct yb_event){pts,duration,c,0};return 1;
}
static int yb_dictionary_size(const AVDictionary *dict,size_t *total,unsigned *entries)
{
 const AVDictionaryEntry *e=NULL;
 while((e=av_dict_get(dict,"",e,AV_DICT_IGNORE_SUFFIX))){
  if(++*entries>64||!e->key||!e->value)return 0;
  size_t key=strnlen(e->key,4097),value=strnlen(e->value,4097);
  if(key>4096||value>4096||*total>YB_FRAME_SIDEBYTES||key+value+258>YB_FRAME_SIDEBYTES-*total)return 0;
  *total+=key+value+258;
 }
 return 1;
}
static int yb_snapshot_size(const AVFrame *f,size_t *bytes)
{
 if(!f||f->opaque_ref||f->private_ref||f->nb_side_data<0||f->nb_side_data>64||
    (f->nb_side_data&&!f->side_data))return 0;
 size_t total=sizeof(AVFrame)+512+(size_t)f->nb_side_data*256;int metadata_seen=0,raw_seen=0;
 unsigned entries=0;
 if(!yb_dictionary_size(f->metadata,&total,&entries))return 0;
 for(int i=0;i<f->nb_side_data;i++){
  const AVFrameSideData *d=f->side_data[i];
  if(!d||!d->data||d->size>YB_FRAME_SIDEBYTES-total)return 0;
  total+=d->size;
  if(!yb_dictionary_size(d->metadata,&total,&entries))return 0;
  if(d->type==AV_FRAME_DATA_DOVI_METADATA){if(++metadata_seen!=1||!yb_metadata_valid(d))return 0;}
  if(d->type==AV_FRAME_DATA_DOVI_RPU_BUFFER&&++raw_seen!=1)return 0;
 }
 if(metadata_seen!=1)return 0;
 *bytes=total;return 1;
}
static int yb_snapshot_unowned(const AVFrame *copy)
{
 if(!copy||copy->hw_frames_ctx||copy->opaque_ref||copy->private_ref||copy->opaque||copy->extended_buf||copy->nb_extended_buf)return 0;
 for(unsigned i=0;i<AV_NUM_DATA_POINTERS;i++)if(copy->buf[i]||copy->data[i])return 0;
 return copy->extended_data==copy->data;
}
static int yb_pair_reject(struct yb_pair_state *s,unsigned reason)
{if(s)s->diagnostic.reason=reason;return 0;}
static int yb_pair_frame(struct yb_pair_state *s,const AVFrame *frame,unsigned route)
{
 if(s)s->diagnostic=(struct yb_pair_diagnostic){.route=route};
 if(!s||route>1||!frame||frame->pts==AV_NOPTS_VALUE)return yb_pair_reject(s,1);
 if(frame->best_effort_timestamp==AV_NOPTS_VALUE||frame->best_effort_timestamp!=frame->pts)return yb_pair_reject(s,11);
 unsigned index=s->event_count;
 for(unsigned i=0;i<s->event_count;i++)if(s->events[i].pts==frame->pts){index=i;break;}
 if(index==s->event_count)return yb_pair_reject(s,2);
 s->diagnostic.expected_duration=s->events[index].duration;s->diagnostic.observed_duration=frame->duration;
 if(frame->duration!=s->events[index].duration)return yb_pair_reject(s,3);
 if(s->events[index].decoded_mask&(1u<<route))return yb_pair_reject(s,4);
 size_t bytes;
 if(!yb_snapshot_size(frame,&bytes))return yb_pair_reject(s,5);
 if(bytes>YB_SNAPSHOT_BYTES-s->snapshot_bytes||s->snapshot_count==YB_SNAPSHOT_MAX)return yb_pair_reject(s,6);
 AVFrame *copy=av_frame_alloc();if(!copy)return yb_pair_reject(s,7);
 if(av_frame_copy_props(copy,frame)<0){av_frame_free(&copy);return yb_pair_reject(s,8);}
 copy->width=frame->width;copy->height=frame->height;copy->format=frame->format;
 if(!yb_snapshot_unowned(copy)){av_frame_free(&copy);return yb_pair_reject(s,9);}
 unsigned other=s->snapshot_count;
 for(unsigned i=0;i<s->snapshot_count;i++)if(s->snapshots[i].pts==frame->pts&&s->snapshots[i].route!=route){other=i;break;}
 s->events[index].decoded_mask|=1u<<route;
 if(other<s->snapshot_count){
  const AVFrame *reference=route?s->snapshots[other].frame:copy;
  const AVFrame *candidate=route?copy:s->snapshots[other].frame;
  s->diagnostic.reference_flags=(uint32_t)reference->flags;s->diagnostic.candidate_flags=(uint32_t)candidate->flags;
  s->diagnostic.reference_geometry=route?s->snapshots[other].geometry:yb_geometry_observe(frame);
  s->diagnostic.candidate_geometry=route?yb_geometry_observe(frame):s->snapshots[other].geometry;
  s->diagnostic.property_mask=props_field_mask(reference,candidate);
  s->diagnostic.metadata_equal=yb_metadata_equal(reference,candidate);
  s->diagnostic.raw_equal=raw_rpu_equal(reference,candidate);
  int equal=picture_props(reference,candidate)&&s->diagnostic.metadata_equal&&s->diagnostic.raw_equal;
  if(equal)yb_observe_transport_dts(&s->dts,reference,candidate);
  av_frame_free(&copy);s->snapshot_bytes-=s->snapshots[other].bytes;
  av_frame_free(&s->snapshots[other].frame);
  s->snapshots[other]=s->snapshots[--s->snapshot_count];
  if(!equal)return yb_pair_reject(s,10);
  struct yb_au_coverage c=s->events[index].coverage;
  s->paired++;if(!c.rpu_present)s->without_rpu++;else if(c.use_previous)s->previous_rpu++;else s->new_rpu++;
  if(c.rpu_count>1)s->duplicate_rpu_aus++;
 }else{
  s->snapshots[s->snapshot_count++]=(struct yb_snapshot){frame->pts,copy,route,bytes,yb_geometry_observe(frame)};s->snapshot_bytes+=bytes;
 }
 return 1;
}
static void yb_pairs_clear(struct yb_pair_state *s)
{for(unsigned i=0;i<s->snapshot_count;i++)av_frame_free(&s->snapshots[i].frame);s->snapshot_count=0;s->snapshot_bytes=0;}
#endif
