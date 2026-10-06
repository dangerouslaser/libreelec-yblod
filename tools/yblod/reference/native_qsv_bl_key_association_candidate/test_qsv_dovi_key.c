#include "qsv_dovi.h"
#include <assert.h>
#include <stdio.h>
static AVPacket packet(const uint8_t *p,int n,int64_t pts){return (AVPacket){.data=(uint8_t*)p,.size=n,.pts=pts,.duration=41000};}
static void key_associations(void)
{
    QSVDOVIContext s={0};
    uint64_t tokens[10];int expected[10];
    for(unsigned i=0;i<10;i++){
        uint8_t bytes[]={0,0,1,2,1,0xc0};
        unsigned type=i<8?16+i:1;
        bytes[3]=type*2;
        AVPacket pkt=packet(bytes,sizeof(bytes),100+i);
        assert(!qsv_dovi_prepare(&s,&pkt,0));
        tokens[i]=s.pending.token;expected[i]=i<8;
        assert(s.pending.key_frame==expected[i]);
        assert(!qsv_dovi_consume(&s,2));
        pkt.data+=2;pkt.size-=2;
        assert(!qsv_dovi_prepare(&s,&pkt,0)&&s.pending.token==tokens[i]);
        assert(!qsv_dovi_consume(&s,pkt.size));
    }
    for(int i=9;i>=0;i--){
        AVFrame *f=av_frame_alloc();assert(f);
        f->flags=AV_FRAME_FLAG_CORRUPT|AV_FRAME_FLAG_KEY|AV_FRAME_FLAG_DISCARD;
        assert(!qsv_dovi_output(&s,tokens[i],f));
        assert(!!(f->flags&AV_FRAME_FLAG_KEY)==expected[i]);
        assert((f->flags&~AV_FRAME_FLAG_KEY)==(AV_FRAME_FLAG_CORRUPT|AV_FRAME_FLAG_DISCARD));
        av_frame_free(&f);
    }
    uint8_t mixed[]={0,0,1,42,1,0xc0,0,0,1,38,1,0x40};
    AVPacket bad=packet(mixed,sizeof(mixed),0);
    assert(qsv_dovi_prepare(&s,&bad,0)==AVERROR_INVALIDDATA&&!s.pending.token);
    uint8_t cra[]={0,0,1,42,1,0xc0};AVPacket p=packet(cra,sizeof(cra),0);
    assert(!qsv_dovi_prepare(&s,&p,0)&&s.pending.key_frame);
    qsv_dovi_flush(&s);assert(!s.pending.token&&!s.count&&!s.pending.key_frame);
    qsv_dovi_uninit(&s);
}

int main(void){key_associations();puts("10 IRAP/nonIRAP token classification, partial/reorder/KEY-only/reset cases PASS");return 0;}
