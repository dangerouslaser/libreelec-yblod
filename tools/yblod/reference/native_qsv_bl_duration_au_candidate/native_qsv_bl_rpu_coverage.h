/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Diagnostic header classifier ONLY, not a Dolby RPU decoder/conformance test.
 * Mirrors supported P7 header field order in original dovi_rpudec.c428-504.
 * Caller feeds independently normalized AnnexB clones of actual submitted AUs;
 * full native decoder remains the independent validator/resolved-state source. */
#ifndef YB_BL_RPU_COVERAGE_H
#define YB_BL_RPU_COVERAGE_H
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
struct yb_bits {const uint8_t *p;size_t bits,pos;int failed;};
static uint32_t yb_read(struct yb_bits *b,unsigned n)
{
 uint32_t v=0;
 if(n>32||b->pos>b->bits||n>b->bits-b->pos){b->failed=1;return 0;}
 while(n--){v=(v<<1)|((b->p[b->pos>>3]>>(7-(b->pos&7)))&1);b->pos++;}
 return v;
}
static uint32_t yb_ue(struct yb_bits *b)
{
 unsigned zero=0;
 while(!b->failed&&!yb_read(b,1))if(++zero>=32){b->failed=1;return 0;}
 if(b->failed)return 0;
 return ((uint32_t)1<<zero)-1+yb_read(b,zero);
}
/* Input is RPU RBSP starting with native prefix25, not a HEVC NAL header. */
static int yb_rpu_previous(const uint8_t *p,size_t n,int *previous,unsigned *reference_id)
{
 if(!p||!previous||!reference_id||n<5||n>1024*1024||p[0]!=25)return 0;
 while(n&&p[n-1]==0)n--;
 if(n<2)return 0;
 struct yb_bits b={p+1,(n-1)*8,0,0};
 if(yb_read(&b,6)!=2)return 0;
 unsigned format=yb_read(&b,11);yb_read(&b,4);yb_read(&b,4);
 if(!yb_read(&b,1)||(format&0x700))return 0;
 yb_read(&b,1);unsigned coeff=yb_read(&b,2);
 if(coeff>1)return 0;
 if(coeff==0){unsigned denom=yb_ue(&b);if(denom<13||denom>32)return 0;}
 yb_read(&b,2);yb_read(&b,1);
 unsigned bl=yb_ue(&b),el=yb_ue(&b),vdr=yb_ue(&b);
 if(bl>8||(el&255)>8||(el>>8)>255||vdr>8)return 0;
 yb_read(&b,1);unsigned compression=yb_read(&b,3);
 yb_read(&b,1);yb_read(&b,1);
 unsigned dm=yb_read(&b,1),prev=yb_read(&b,1);
 if(b.failed||compression>1||(compression&&!dm))return 0;
 unsigned id=yb_ue(&b);if(b.failed||id>15)return 0;
 *previous=prev;*reference_id=id;return 1;
}
struct yb_au_coverage {unsigned nal_count,first_slice_count,rpu_count,selected_reference_id;int rpu_present,use_previous;};
static size_t yb_start(const uint8_t *p,size_t n,size_t from,size_t *prefix)
{
 for(size_t i=from;i+3<=n;i++){
  if(p[i]||p[i+1])continue;
  if(p[i+2]==1){*prefix=3;return i;}
  if(i+4<=n&&!p[i+2]&&p[i+3]==1){*prefix=4;return i;}
 }
 *prefix=0;return n;
}
static int yb_scan_au(const uint8_t *p,size_t n,struct yb_au_coverage *out)
{
 if(!p||!out||n<6||n>64*1024*1024)return 0;
 struct yb_au_coverage c={0};size_t prefix,start=yb_start(p,n,0,&prefix);
 int seen_vcl=0,trailer=0,ended=0,picture_type=-1,picture_tid=-1;
 if(start>3||!prefix)return 0;
 for(size_t z=0;z<start;z++)if(p[z])return 0;
 while(prefix){
  size_t at=start+prefix,next_prefix,end=yb_start(p,n,at,&next_prefix);
  if(end-at<2||++c.nal_count>4096)return 0;
  unsigned type=(p[at]>>1)&63,layer=((p[at]&1)<<5)|(p[at+1]>>3),tid=p[at+1]&7;
  if((p[at]&128)||!tid||layer)return 0;
  if(ended&&type!=36&&type!=37)return 0;
  if(type<=31){
   if(trailer||end-at<3)return 0;
   if(p[at+2]&128){if(++c.first_slice_count!=1)return 0;picture_type=type;picture_tid=tid;}
   else if(!c.first_slice_count)return 0;
   if((int)type!=picture_type||(int)tid!=picture_tid)return 0;
   seen_vcl=1;
  }else if(type==62){if(!seen_vcl)return 0;trailer=1;}
  else if(type==63){if(!seen_vcl||trailer)return 0;}
  else if(type==36||type==37||type==40){if(!seen_vcl)return 0;trailer=1;if(type!=40)ended=1;}
  else if((type>=32&&type<=35)||type==39){if(seen_vcl||trailer)return 0;}
  else return 0;
  if(type==62){
   if(tid!=1||end-at<=2||end-at>1024*1024)return 0;
   uint8_t *rbsp=malloc(end-at-2);if(!rbsp)return 0;
   size_t used=0;unsigned zeros=0;
   for(size_t i=at+2;i<end;i++){
    if(zeros>=2&&p[i]==3){if(i+1>=end||p[i+1]>3){free(rbsp);return 0;}zeros=0;continue;}
    rbsp[used++]=p[i];zeros=p[i]==0?zeros+1:0;
   }
   int previous=0;unsigned reference_id=0;int valid=yb_rpu_previous(rbsp,used,&previous,&reference_id);free(rbsp);
   if(!valid)return 0;
   c.rpu_count++;c.rpu_present=1;c.use_previous=previous;c.selected_reference_id=reference_id;
  }
  start=end;prefix=next_prefix;
 }
 if(c.first_slice_count!=1)return 0;
 /* Preserve native backwards-last-RPU selection; count duplicates explicitly. */
 *out=c;return 1;
}
#endif



