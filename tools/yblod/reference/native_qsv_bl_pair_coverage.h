/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Source-only diagnostic integration. CPU property snapshots never retain a
 * decoded pixel plane or hw_frames_ctx. Private AU events/IDs are not exported. */
#ifndef YB_BL_PAIR_COVERAGE_H
#define YB_BL_PAIR_COVERAGE_H
#include <libavutil/dict.h>
#include "native_qsv_bl_rpu_coverage.h"
enum { YB_EVENT_MAX=4096,YB_SNAPSHOT_MAX=64,YB_SNAPSHOT_BYTES=4*1024*1024,YB_FRAME_SIDEBYTES=1024*1024 };
struct yb_event {int64_t pts;struct yb_au_coverage coverage;unsigned decoded_mask;};
struct yb_snapshot {int64_t pts;AVFrame *frame;unsigned route;size_t bytes;};
struct yb_pair_state {
 struct yb_event events[YB_EVENT_MAX];unsigned event_count;
 struct yb_snapshot snapshots[YB_SNAPSHOT_MAX];unsigned snapshot_count;size_t snapshot_bytes;
 uint64_t paired,without_rpu,new_rpu,previous_rpu,duplicate_rpu_aus;
};
static int yb_record_event(struct yb_pair_state *s,int64_t pts,struct yb_au_coverage c)
{
 if(!s||pts==AV_NOPTS_VALUE||s->event_count==YB_EVENT_MAX)return 0;
 for(unsigned i=0;i<s->event_count;i++)if(s->events[i].pts==pts)return 0;
 s->events[s->event_count++]=(struct yb_event){pts,c,0};return 1;
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
static int yb_pair_frame(struct yb_pair_state *s,const AVFrame *frame,unsigned route)
{
 if(!s||route>1||!frame||frame->pts==AV_NOPTS_VALUE)return 0;
 unsigned index=s->event_count;
 for(unsigned i=0;i<s->event_count;i++)if(s->events[i].pts==frame->pts){index=i;break;}
 if(index==s->event_count||(s->events[index].decoded_mask&(1u<<route)))return 0;
 size_t bytes;
 if(!yb_snapshot_size(frame,&bytes)||bytes>YB_SNAPSHOT_BYTES-s->snapshot_bytes||s->snapshot_count==YB_SNAPSHOT_MAX)return 0;
 AVFrame *copy=av_frame_alloc();if(!copy)return 0;
 if(av_frame_copy_props(copy,frame)<0){av_frame_free(&copy);return 0;}
 copy->width=frame->width;copy->height=frame->height;copy->format=frame->format;
 if(!yb_snapshot_unowned(copy)){av_frame_free(&copy);return 0;}
 unsigned other=s->snapshot_count;
 for(unsigned i=0;i<s->snapshot_count;i++)if(s->snapshots[i].pts==frame->pts&&s->snapshots[i].route!=route){other=i;break;}
 s->events[index].decoded_mask|=1u<<route;
 if(other<s->snapshot_count){
  const AVFrame *reference=route?s->snapshots[other].frame:copy;
  const AVFrame *candidate=route?copy:s->snapshots[other].frame;
  int equal=props(reference,candidate)&&yb_metadata_equal(reference,candidate)&&raw_rpu_equal(reference,candidate);
  av_frame_free(&copy);s->snapshot_bytes-=s->snapshots[other].bytes;
  av_frame_free(&s->snapshots[other].frame);
  s->snapshots[other]=s->snapshots[--s->snapshot_count];
  if(!equal)return 0;
  struct yb_au_coverage c=s->events[index].coverage;
  s->paired++;if(!c.rpu_present)s->without_rpu++;else if(c.use_previous)s->previous_rpu++;else s->new_rpu++;
  if(c.rpu_count>1)s->duplicate_rpu_aus++;
 }else{
  s->snapshots[s->snapshot_count++]=(struct yb_snapshot){frame->pts,copy,route,bytes};s->snapshot_bytes+=bytes;
 }
 return 1;
}
static void yb_pairs_clear(struct yb_pair_state *s)
{for(unsigned i=0;i<s->snapshot_count;i++)av_frame_free(&s->snapshots[i].frame);s->snapshot_count=0;s->snapshot_bytes=0;}
#endif
