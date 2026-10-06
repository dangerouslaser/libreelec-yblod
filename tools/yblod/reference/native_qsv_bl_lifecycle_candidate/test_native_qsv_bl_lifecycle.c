/* Source-only lifecycle accounting and ownership fixture. No decoder, device,
 * media or mapped hardware lifetime is exercised by this CPU mock. */
#include <libavcodec/avcodec.h>
#include <libavutil/error.h>
static AVCodecContext *mock_contexts[2];
static unsigned mock_sends[2],mock_receives[2];
static int mock_mode;
static int mock_route(AVCodecContext *c){return c==mock_contexts[1];}
static int mock_send(AVCodecContext *c,const AVPacket *p)
{
 int route=mock_route(c);mock_sends[route]++;
 if(p||mock_mode==1)return AVERROR(EINVAL);
 if(mock_mode==2||mock_sends[route]==1)return AVERROR(EAGAIN);
 return 0;
}
static int mock_receive(AVCodecContext *c,AVFrame *f)
{
 (void)f;int route=mock_route(c);mock_receives[route]++;
 return mock_mode==3||mock_sends[route]<2?AVERROR(EAGAIN):AVERROR_EOF;
}
#define avcodec_send_packet mock_send
#define avcodec_receive_frame mock_receive
#define main bl_probe_main
#include "native_qsv_bl_compare_probe.c"
#undef main
#include <assert.h>

int main(void)
{
 struct yb_pair_state s={0};
 uint64_t accepted[2]={2,2};
 int end[2]={AVERROR_EOF,AVERROR_EOF};
 s.event_count=2;s.paired=2;s.events[0].decoded_mask=3;s.events[1].decoded_mask=3;
 assert(window_accounted(&s,accepted,end));
 end[1]=AVERROR(EAGAIN);assert(!window_accounted(&s,accepted,end));end[1]=AVERROR_EOF;
 accepted[0]=1;assert(!window_accounted(&s,accepted,end));accepted[0]=2;
 s.events[1].decoded_mask=1;assert(!window_accounted(&s,accepted,end));s.events[1].decoded_mask=3;
 s.paired=1;assert(!window_accounted(&s,accepted,end));s.paired=2;
 s.snapshot_count=1;assert(!window_accounted(&s,accepted,end));s.snapshot_count=0;
 s.snapshot_bytes=1;assert(!window_accounted(&s,accepted,end));s.snapshot_bytes=0;
 s.event_count=0;assert(!window_accounted(&s,accepted,end));
 assert(!same_picture(NULL,NULL));assert(!selected_pairs_equal());
 mock_contexts[0]=avcodec_alloc_context3(NULL);mock_contexts[1]=avcodec_alloc_context3(NULL);
 assert(mock_contexts[0]&&mock_contexts[1]);
 for(mock_mode=0;mock_mode<4;mock_mode++){
  memset(mock_sends,0,sizeof(mock_sends));memset(mock_receives,0,sizeof(mock_receives));
  memset(&pair_state,0,sizeof(pair_state));pair_state.event_count=pair_state.paired=2;
  pair_state.events[0].decoded_mask=pair_state.events[1].decoded_mask=3;
  submitted[0]=submitted[1]=2;deadline=time(NULL)+10;
  int ok=finish_window(mock_contexts,NULL,NULL);assert(ok==(mock_mode==0));
  assert(mock_sends[0]<=8&&mock_sends[1]<=8);
  if(!mock_mode)assert(mock_sends[0]==2&&mock_sends[1]==2&&receive_end[0]==AVERROR_EOF&&receive_end[1]==AVERROR_EOF);
 }
 mock_mode=0;deadline=time(NULL)-1;assert(!finish_window(mock_contexts,NULL,NULL));
 avcodec_free_context(&mock_contexts[0]);avcodec_free_context(&mock_contexts[1]);
 held_owner=av_frame_alloc();assert(held_owner);
 held_owner->format=AV_PIX_FMT_GRAY8;held_owner->width=16;held_owner->height=16;
 assert(av_frame_get_buffer(held_owner,32)>=0);
 AVBufferRef *saved=av_buffer_ref(held_owner->buf[0]);assert(saved);
 selected[0][0]=av_frame_clone(held_owner);assert(selected[0][0]);
 submitted[0]=2;frames_seen[1]=2;receive_end[0]=AVERROR_EOF;mapped=3;handshake_done=1;
 clear_epoch();
 assert(held_owner&&held_owner->buf[0]->data==saved->data);
 assert(!selected[0][0]&&!submitted[0]&&!frames_seen[1]&&!receive_end[0]&&!mapped);
 assert(handshake_done==1);
 av_frame_free(&held_owner);av_buffer_unref(&saved);
 puts("lifecycle accounting, bounded mocked NULL drain and CPU owner-reference fixtures PASS; hardware lifetime unqualified");
 return 0;
}
