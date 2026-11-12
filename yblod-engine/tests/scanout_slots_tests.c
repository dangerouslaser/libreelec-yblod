#include "dv_scanout_slots.h"
#include "dv_engine.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void)
{
    dv_scanout_slots p;dv_scanout_slots_init(&p);assert(dv_scanout_slots_can_destroy(&p));
    dv_scanout_lease a,b;dv_scanout_identity id={1,41708};
    assert(dv_scanout_slots_acquire(&p,id,&a)==DV_OK&&a.slot==0&&a.refresh&&a.packet_id==0);
    assert(!dv_scanout_slots_can_destroy(&p));
    assert(dv_scanout_slots_reset_stream(&p)==DV_SCANOUT_BUSY&&p.writing);
    memset(&b,0xab,sizeof(b));dv_scanout_lease saved=b;
    assert(dv_scanout_slots_acquire(&p,id,&b)==DV_SCANOUT_BUSY&&!memcmp(&b,&saved,sizeof(b)));
    assert(dv_scanout_slots_committed(&p,&a,DV_SCANOUT_ACCEPTED)==DV_IDENTITY);
    b=a;++b.identity.pts;assert(dv_scanout_slots_written(&p,&b,DV_SCANOUT_ACCEPTED)==DV_IDENTITY);
    assert(dv_scanout_slots_written(&p,&a,DV_SCANOUT_ACCEPTED)==DV_OK);
    assert(dv_scanout_slots_acquire(&p,id,&b)==DV_SCANOUT_BUSY);
    assert(dv_scanout_slots_committed(&p,&a,DV_SCANOUT_ACCEPTED)==DV_OK&&p.current==0&&p.packet_id==1);
    assert(dv_scanout_slots_committed(&p,&a,DV_SCANOUT_ACCEPTED)==DV_IDENTITY);
    for(unsigned frame=0;frame<1000;++frame){int current=p.current;unsigned packet=p.packet_id;
        id.frame_id++;id.pts+=41708;
        assert(dv_scanout_slots_acquire(&p,id,&b)==DV_OK&&(int)b.slot!=current&&b.packet_id==packet);
        assert(dv_scanout_slots_written(&p,&a,DV_SCANOUT_ACCEPTED)==DV_IDENTITY);
        assert(dv_scanout_slots_written(&p,&b,DV_SCANOUT_ACCEPTED)==DV_OK);
        dv_scanout_outcome result=frame%3?DV_SCANOUT_ACCEPTED:DV_SCANOUT_REJECTED;
        assert(dv_scanout_slots_committed(&p,&b,result)==DV_OK);
        if(result==DV_SCANOUT_ACCEPTED)assert(p.current==(int)b.slot&&p.packet_id==((packet+1)&15u)&&!p.refresh);
        else assert(p.current==current&&p.packet_id==packet&&p.refresh);
        a=b;
    }
    assert(dv_scanout_slots_acquire(&p,id,&a)==DV_OK);
    int old=p.current;
    assert(dv_scanout_slots_reset_stream(&p)==DV_SCANOUT_BUSY&&p.current==old);
    assert(dv_scanout_slots_written(&p,&a,DV_SCANOUT_ACCEPTED)==DV_OK);
    assert(dv_scanout_slots_reset_stream(&p)==DV_OK&&p.current==old&&p.refresh&&p.packet_id==0);
    assert(!dv_scanout_slots_can_destroy(&p));
    assert(dv_scanout_slots_committed(&p,&a,DV_SCANOUT_ACCEPTED)==DV_IDENTITY);
    assert(dv_scanout_slots_acquire(&p,id,&b)==DV_OK&&(int)b.slot!=old);
    assert(dv_scanout_slots_written(&p,&a,DV_SCANOUT_ACCEPTED)==DV_IDENTITY);
    a=b;
    assert(dv_scanout_slots_written(&p,&a,DV_SCANOUT_REJECTED)==DV_OK&&p.refresh);
    assert(dv_scanout_slots_acquire(&p,id,&b)==DV_OK);
    assert(dv_scanout_slots_written(&p,&b,DV_SCANOUT_UNCERTAIN)==DV_BACKEND);
    assert(!dv_scanout_slots_can_destroy(&p)&&dv_scanout_slots_acquire(&p,id,&a)==DV_BACKEND);
    assert(dv_scanout_slots_reset_stream(&p)==DV_BACKEND);
    dv_scanout_slots_restored(&p);assert(dv_scanout_slots_can_destroy(&p));
    assert(dv_scanout_slots_acquire(&p,id,&a)==DV_OK&&a.serial>b.serial&&a.refresh&&a.packet_id==0);
    assert(dv_scanout_slots_written(&p,&b,DV_SCANOUT_ACCEPTED)==DV_IDENTITY);
    assert(dv_scanout_slots_written(&p,&a,DV_SCANOUT_ACCEPTED)==DV_OK);
    assert(dv_scanout_slots_committed(&p,&a,DV_SCANOUT_UNCERTAIN)==DV_BACKEND);
    assert(!dv_scanout_slots_can_destroy(&p)&&dv_scanout_slots_acquire(&p,id,&b)==DV_BACKEND);
    dv_scanout_slots_restored(&p);p.serial=UINT64_MAX;
    assert(dv_scanout_slots_acquire(&p,id,&b)==DV_BACKEND&&dv_scanout_slots_can_destroy(&p));

    /* An unfinished write certified over: rejected, the quarantine lifted,
     * the display's buffer kept. */
    dv_scanout_slots_init(&p);
    assert(dv_scanout_slots_acquire(&p,id,&a)==DV_OK&&dv_scanout_slots_written(&p,&a,DV_SCANOUT_ACCEPTED)==DV_OK);
    assert(dv_scanout_slots_committed(&p,&a,DV_SCANOUT_ACCEPTED)==DV_OK&&p.current==(int)a.slot);
    old=p.current;
    assert(dv_scanout_slots_acquire(&p,id,&b)==DV_OK);
    assert(dv_scanout_slots_written(&p,&b,DV_SCANOUT_UNCERTAIN)==DV_BACKEND&&p.quarantined);
    dv_scanout_slots_drained(&p);
    assert(!p.quarantined&&!p.writing&&!p.ready&&p.refresh&&p.current==old);
    assert(dv_scanout_slots_written(&p,&b,DV_SCANOUT_ACCEPTED)==DV_IDENTITY);
    assert(dv_scanout_slots_acquire(&p,id,&b)==DV_OK&&(int)b.slot!=old&&b.refresh);
    dv_scanout_slots_drained(&p);
    assert(!p.writing&&dv_scanout_slots_acquire(&p,id,&b)==DV_OK);
    assert(dv_scanout_slots_written(&p,&b,DV_SCANOUT_ACCEPTED)==DV_OK);
    assert(dv_scanout_slots_committed(&p,&b,DV_SCANOUT_ACCEPTED)==DV_OK);

    /* Queued flips: three buffers, one on screen, one queued, one written. */
    dv_scanout_slots_init(&p);assert(p.queued<0);
    assert(dv_scanout_slots_flipped(&p)==DV_IDENTITY);
    assert(dv_scanout_slots_acquire(&p,id,&a)==DV_OK&&a.slot==0);
    assert(dv_scanout_slots_queue(&p,&a)==DV_IDENTITY);           /* not written yet */
    assert(dv_scanout_slots_written(&p,&a,DV_SCANOUT_ACCEPTED)==DV_OK);
    assert(dv_scanout_slots_committed(&p,&a,DV_SCANOUT_ACCEPTED)==DV_OK&&p.current==0);
    unsigned used[3]={0,0,0},queued_flips=0,blocking=0,rejected=0;
    for(unsigned frame=0;frame<3000;++frame){int current=p.current,queued=p.queued;unsigned packet=p.packet_id;
        id.frame_id++;id.pts+=16683;
        /* the next picture is written while one flip is queued */
        assert(dv_scanout_slots_acquire(&p,id,&b)==DV_OK&&b.slot<3&&(int)b.slot!=current&&(int)b.slot!=queued);
        assert(queued>=0||b.slot<2);                              /* slot 2 only with a flip queued */
        assert(b.packet_id==packet);++used[b.slot];
        assert(dv_scanout_slots_acquire(&p,id,&a)==DV_SCANOUT_BUSY);
        assert(dv_scanout_slots_written(&p,&b,DV_SCANOUT_ACCEPTED)==DV_OK);
        if(queued>=0){
            /* one flip at a time, and no blocking replacement past it */
            assert(dv_scanout_slots_queue(&p,&b)==DV_SCANOUT_BUSY&&p.ready&&p.queued==queued);
            assert(dv_scanout_slots_committed(&p,&b,DV_SCANOUT_ACCEPTED)==DV_SCANOUT_BUSY&&p.ready);
            assert(!dv_scanout_slots_can_destroy(&p));
            if(frame%7==0)assert(dv_scanout_slots_reset_stream(&p)==DV_OK&&p.queued==queued&&!p.ready);
            assert(dv_scanout_slots_flipped(&p)==DV_OK&&p.current==queued&&p.queued<0);
            assert(dv_scanout_slots_flipped(&p)==DV_IDENTITY);
            if(frame%7==0){                                       /* the reset discarded the ready picture */
                assert(dv_scanout_slots_queue(&p,&b)==DV_IDENTITY);
                assert(p.packet_id==0&&p.refresh);continue;
            }
        }
        packet=p.packet_id;current=p.current;
        switch(frame%5){
        case 0:                                                    /* a rejected commit: nothing changes on screen */
            assert(dv_scanout_slots_committed(&p,&b,DV_SCANOUT_REJECTED)==DV_OK);
            assert(p.current==current&&p.queued<0&&p.packet_id==packet&&p.refresh);++rejected;break;
        case 1:                                                    /* the blocking fallback */
            assert(dv_scanout_slots_committed(&p,&b,DV_SCANOUT_ACCEPTED)==DV_OK);
            assert(p.current==(int)b.slot&&p.queued<0&&p.packet_id==((packet+1)&15u)&&!p.refresh);++blocking;break;
        default:
            assert(dv_scanout_slots_queue(&p,&b)==DV_OK);
            assert(p.current==current&&p.queued==(int)b.slot&&!p.ready&&p.packet_id==((packet+1)&15u)&&!p.refresh);
            assert(dv_scanout_slots_queue(&p,&b)==DV_IDENTITY);   /* a lease queues once */
            ++queued_flips;break;
        }
    }
    assert(used[0]&&used[1]&&used[2]&&queued_flips>1000&&blocking>100&&rejected>100);
    /* a rejected commit while a flip is queued leaves the flip queued */
    if(p.queued<0){
        assert(dv_scanout_slots_acquire(&p,id,&b)==DV_OK&&dv_scanout_slots_written(&p,&b,DV_SCANOUT_ACCEPTED)==DV_OK);
        assert(dv_scanout_slots_queue(&p,&b)==DV_OK);
    }
    int queued=p.queued;old=p.current;
    assert(dv_scanout_slots_acquire(&p,id,&b)==DV_OK&&dv_scanout_slots_written(&p,&b,DV_SCANOUT_ACCEPTED)==DV_OK);
    assert(dv_scanout_slots_committed(&p,&b,DV_SCANOUT_REJECTED)==DV_OK&&p.queued==queued&&p.current==old&&p.refresh);
    /* an engine failure while a flip is queued: the flip is the display's */
    assert(dv_scanout_slots_acquire(&p,id,&b)==DV_OK);
    assert(dv_scanout_slots_written(&p,&b,DV_SCANOUT_UNCERTAIN)==DV_BACKEND);
    assert(dv_scanout_slots_flipped(&p)==DV_BACKEND&&dv_scanout_slots_queue(&p,&b)==DV_BACKEND);
    dv_scanout_slots_drained(&p);
    assert(p.queued==queued&&p.current==old&&!dv_scanout_slots_can_destroy(&p));
    assert(dv_scanout_slots_flipped(&p)==DV_OK&&p.current==queued);
    /* the display handed back after the flip: everything free again */
    dv_scanout_slots_restored(&p);
    assert(dv_scanout_slots_can_destroy(&p)&&p.queued<0);
    puts("{\"blocking_scanout_transitions\":1000,\"failure_quarantine\":true,\"stale_lease_rejected\":true,"
         "\"drained_write\":true,\"queued_flip_frames\":3000,\"passed\":true}");
    return 0;
}
