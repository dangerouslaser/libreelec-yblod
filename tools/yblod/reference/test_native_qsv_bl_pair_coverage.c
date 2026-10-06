/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Source-only CPU snapshot/event mock; does not decode or create hardware. */
#include <assert.h>
#include <libavutil/mem.h>
#define main yb_unexecuted_probe_main
#include "native_qsv_bl_compare_probe.c"
#undef main
static AVFrame *metadata_picture(int64_t pts)
{
 AVFrame *f=av_frame_alloc();assert(f);f->width=3840;f->height=2160;f->pts=pts;
 f->best_effort_timestamp=pts;f->time_base=(AVRational){0,1};
 size_t size;AVDOVIMetadata *m=av_dovi_metadata_alloc(&size);assert(m);
 for(int c=0;c<3;c++)av_dovi_get_mapping(m)->curves[c].num_pivots=2;
 AVFrameSideData *d=av_frame_new_side_data(f,AV_FRAME_DATA_DOVI_METADATA,size);assert(d);memcpy(d->data,m,size);av_free(m);
 return f;
}
int main(void)
{
 struct yb_pair_state *s=av_mallocz(sizeof(*s));assert(s);
 struct yb_au_coverage no_rpu={.first_slice_count=1};
 struct yb_au_coverage previous={.first_slice_count=1,.rpu_count=1,.rpu_present=1,.use_previous=1,.selected_reference_id=15};
 assert(yb_record_event(s,10,no_rpu));assert(!yb_record_event(s,10,no_rpu));
 AVFrame *a=metadata_picture(10),*b=metadata_picture(10);
 assert(yb_pair_frame(s,a,0)&&s->snapshot_count==1&&s->paired==0);
 assert(!s->snapshots[0].frame->hw_frames_ctx&&!s->snapshots[0].frame->data[0]);
 assert(yb_pair_frame(s,b,1)&&s->snapshot_count==0&&s->without_rpu==1&&s->paired==1);
 assert(!yb_pair_frame(s,a,0)); /* Duplicate decoder association fails. */
 assert(yb_record_event(s,20,previous));a->pts=b->pts=20;a->best_effort_timestamp=b->best_effort_timestamp=20;
 assert(yb_pair_frame(s,a,0));assert(yb_pair_frame(s,b,1));assert(s->previous_rpu==1);
 /* Requested reference ID classification is not semantic reference validation. */
 assert(yb_record_event(s,30,no_rpu));a->pts=b->pts=30;a->best_effort_timestamp=b->best_effort_timestamp=30;
 assert(yb_pair_frame(s,a,0));av_dovi_get_header((void*)av_frame_get_side_data(b,AV_FRAME_DATA_DOVI_METADATA)->data)->disable_residual_flag=1;
 assert(!yb_pair_frame(s,b,1));yb_pairs_clear(s);memset(s,0,sizeof(*s));
 av_frame_free(&a);av_frame_free(&b);a=metadata_picture(100);
 size_t estimate=0;assert(yb_snapshot_size(a,&estimate));
 AVFrameSideData *side=av_frame_get_side_data(a,AV_FRAME_DATA_DOVI_METADATA);
 char huge[4098];memset(huge,'x',sizeof(huge)-1);huge[sizeof(huge)-1]=0;
 assert(av_dict_set(&side->metadata,"oversized",huge,0)==0);assert(!yb_snapshot_size(a,&estimate));av_dict_free(&side->metadata);
 assert(av_dict_set(&a->metadata,"oversized",huge,0)==0);assert(!yb_snapshot_size(a,&estimate));av_dict_free(&a->metadata);
 for(unsigned i=0;i<64;i++){char key[32];snprintf(key,sizeof(key),"entry%u",i);assert(av_dict_set(&a->metadata,key,"value",0)==0);}
 assert(av_dict_set(&side->metadata,"extra","value",0)==0);assert(!yb_snapshot_size(a,&estimate));av_dict_free(&a->metadata);av_dict_free(&side->metadata);
 a->opaque_ref=av_buffer_alloc(1);assert(a->opaque_ref);assert(!yb_snapshot_size(a,&estimate));av_buffer_unref(&a->opaque_ref);
 /* Diagnostic refusal only: never dereference or free an opaque private slot. */
 a->private_ref=&estimate;assert(!yb_snapshot_size(a,&estimate));a->private_ref=NULL;
 a->opaque=&estimate;assert(yb_record_event(s,a->pts,no_rpu));assert(!yb_pair_frame(s,a,0));a->opaque=NULL;memset(s,0,sizeof(*s));
 AVFrame *empty=av_frame_alloc();assert(empty&&yb_snapshot_unowned(empty));
 for(unsigned i=0;i<AV_NUM_DATA_POINTERS;i++){
  empty->data[i]=(uint8_t*)&estimate;assert(!yb_snapshot_unowned(empty));empty->data[i]=NULL;
  empty->buf[i]=av_buffer_alloc(1);assert(empty->buf[i]&&!yb_snapshot_unowned(empty));av_buffer_unref(&empty->buf[i]);
 }
 empty->hw_frames_ctx=av_buffer_alloc(1);assert(empty->hw_frames_ctx&&!yb_snapshot_unowned(empty));av_buffer_unref(&empty->hw_frames_ctx);
 AVBufferRef *extended=NULL;empty->extended_buf=&extended;empty->nb_extended_buf=1;assert(!yb_snapshot_unowned(empty));empty->extended_buf=NULL;empty->nb_extended_buf=0;
 uint8_t *extended_data=NULL;empty->extended_data=&extended_data;assert(!yb_snapshot_unowned(empty));empty->extended_data=empty->data;
 av_frame_free(&empty);
 for(unsigned i=0;i<YB_SNAPSHOT_MAX;i++){a->pts=100+i;a->best_effort_timestamp=a->pts;assert(yb_record_event(s,a->pts,no_rpu));assert(yb_pair_frame(s,a,0));}
 a->pts=1000;a->best_effort_timestamp=1000;assert(yb_record_event(s,1000,no_rpu));assert(!yb_pair_frame(s,a,0));
 yb_pairs_clear(s);memset(s,0,sizeof(*s));assert(yb_record_event(s,a->pts,no_rpu));s->snapshot_bytes=YB_SNAPSHOT_BYTES;
 assert(!yb_pair_frame(s,a,0));s->snapshot_bytes=0;
 memset(s,0,sizeof(*s));
 AVFrameSideData *large=av_frame_new_side_data(a,AV_FRAME_DATA_A53_CC,700000);assert(large);memset(large->data,0,large->size);
 assert(yb_snapshot_size(a,&estimate));unsigned accepted=0;
 for(unsigned i=0;i<64;i++){
  a->pts=2000+i;a->best_effort_timestamp=a->pts;assert(yb_record_event(s,a->pts,no_rpu));
  if(!yb_pair_frame(s,a,0)){break;}accepted++;
 }
 assert(accepted>0&&accepted<64&&s->snapshot_bytes<=YB_SNAPSHOT_BYTES&&estimate>YB_SNAPSHOT_BYTES-s->snapshot_bytes);
 yb_pairs_clear(s);
 av_frame_free(&a);av_free(s);
 puts("CPU bounded snapshot/actual-pair event classification mocks PASS");return 0;
}
