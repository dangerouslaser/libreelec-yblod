/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Synthetic HEADER classifier fixtures, never full-RPU conformance evidence. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "native_qsv_bl_rpu_coverage.h"
struct writer {uint8_t bytes[128];unsigned pos;};
static void bits(struct writer *w,uint32_t v,unsigned n)
{for(unsigned i=n;i;i--){if((v>>(i-1))&1)w->bytes[w->pos>>3]|=1u<<(7-(w->pos&7));w->pos++;}}
static void ue(struct writer *w,unsigned v)
{unsigned n=0,k=v+1;for(unsigned x=k;x>1;x>>=1)n++;bits(w,0,n);bits(w,k,n+1);}
static size_t header(uint8_t *p,int previous,unsigned id,int seq,unsigned denom)
{
 struct writer w={{0},0};bits(&w,2,6);bits(&w,0,11);bits(&w,0,4);bits(&w,0,4);
 bits(&w,seq,1);bits(&w,0,1);bits(&w,0,2);ue(&w,denom);
 bits(&w,0,2);bits(&w,0,1);ue(&w,2);ue(&w,2);ue(&w,4);
 bits(&w,0,1);bits(&w,0,3);bits(&w,0,1);bits(&w,0,1);
 bits(&w,0,1);bits(&w,previous,1);ue(&w,id);bits(&w,1,1);
 p[0]=25;size_t n=(w.pos+7)/8;memcpy(p+1,w.bytes,n);return n+1;
}
static size_t append(uint8_t *packet,size_t pos,unsigned type,const uint8_t *p,size_t n)
{
 packet[pos++]=0;packet[pos++]=0;packet[pos++]=1;
 packet[pos++]=type<<1;packet[pos++]=1;unsigned zeros=0;
 for(size_t i=0;i<n;i++){
  if(zeros>=2&&p[i]<=3){packet[pos++]=3;zeros=0;}
  packet[pos++]=p[i];zeros=p[i]==0?zeros+1:0;
 }
 return pos;
}
int main(void)
{
 uint8_t p[128],packet[1024];int previous=-1;unsigned id=99;
 size_t n=header(p,0,0,1,13);
 assert(yb_rpu_previous(p,n,&previous,&id)&&!previous&&id==0);
 n=header(p,1,15,1,32);assert(yb_rpu_previous(p,n,&previous,&id)&&previous&&id==15);
 n=header(p,1,16,1,13);assert(!yb_rpu_previous(p,n,&previous,&id));
 n=header(p,0,0,0,13);assert(!yb_rpu_previous(p,n,&previous,&id));
 n=header(p,0,0,1,12);assert(!yb_rpu_previous(p,n,&previous,&id));
 n=header(p,0,0,1,13);for(size_t z=0;z<5;z++)assert(!yb_rpu_previous(p,z,&previous,&id));
 uint8_t slice=128;size_t size=append(packet,0,1,&slice,1);struct yb_au_coverage c;
 assert(yb_scan_au(packet,size,&c)&&!c.rpu_present&&c.first_slice_count==1);
 size=append(packet,size,62,p,n);assert(yb_scan_au(packet,size,&c)&&c.rpu_present&&!c.use_previous&&c.rpu_count==1);
 n=header(p,1,0,1,13);size=append(packet,size,62,p,n);
 assert(yb_scan_au(packet,size,&c)&&c.use_previous&&c.rpu_count==2&&c.selected_reference_id==0);
 size=append(packet,size,1,&slice,1);assert(!yb_scan_au(packet,size,&c));
 size=append(packet,0,62,p,n);assert(!yb_scan_au(packet,size,&c));
 size=append(packet,0,1,&slice,1);packet[4]=0;assert(!yb_scan_au(packet,size,&c));
 size=append(packet,0,1,&slice,1);packet[4]|=8;assert(!yb_scan_au(packet,size,&c));
 puts("Synthetic bounded P7 RPU header/last selection/no-RPU/AU grammar classifier contracts PASS");return 0;
}
