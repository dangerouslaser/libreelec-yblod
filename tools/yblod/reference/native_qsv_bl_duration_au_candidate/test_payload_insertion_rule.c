/* SPDX-License-Identifier: GPL-3.0-or-later */
#include <assert.h>
#include <stdio.h>
#include "native_qsv_bl_payload_guard-insertion-rule.h"
static size_t packet(uint8_t *p,const unsigned *types,size_t count)
{size_t n=0;for(size_t i=0;i<count;i++){p[n++]=0;p[n++]=0;p[n++]=0;p[n++]=3;p[n++]=(uint8_t)(types[i]<<1);p[n++]=1;p[n++]=128;}return n;}
static size_t annex(uint8_t *p,const unsigned *types,size_t count)
{size_t n=0;for(size_t i=0;i<count;i++){memcpy(p+n,"\0\0\0\1",4);n+=4;p[n++]=(uint8_t)(types[i]<<1);p[n++]=1;p[n++]=128;}return n;}
int main(void)
{
 uint8_t prefix[64],original[128],normalized[256],wrong[256];
 const unsigned ps[]={32,33,34},aud_irap[]={35,19},aud_ps_irap[]={35,32,19},nonirap[]={35,1};
 size_t pn=annex(prefix,ps,3);struct yb_normalization n={4,prefix,pn};
 size_t os=packet(original,aud_irap,2),ns=annex(normalized,aud_irap,1);
 memcpy(normalized+ns,prefix,pn);ns+=pn;ns+=annex(normalized+ns,aud_irap+1,1);
 assert(yb_literal_normalized(&n,original,os,normalized,ns));
 memcpy(wrong,prefix,pn);annex(wrong+pn,aud_irap,2);
 assert(!yb_literal_normalized(&n,original,os,wrong,ns)); /* wrong byte0 insertion */
 annex(wrong,aud_irap,2);memcpy(wrong+14,prefix,pn);
 assert(!yb_literal_normalized(&n,original,os,wrong,ns)); /* wrong trailing insertion */
 memcpy(wrong,normalized,ns);wrong[10]^=1;
 assert(!yb_literal_normalized(&n,original,os,wrong,ns)); /* rewritten parameter set */
 memcpy(wrong,normalized,ns);wrong[ns-1]^=1;
 assert(!yb_literal_normalized(&n,original,os,wrong,ns)); /* rewritten original NAL */
 assert(!yb_literal_normalized(&n,original,os,normalized,ns-7)); /* dropped original */
 memcpy(wrong,normalized,ns);memcpy(wrong+ns,prefix,pn);
 assert(!yb_literal_normalized(&n,original,os,wrong,ns+pn)); /* duplicate injection */
 memcpy(wrong,normalized,ns);memcpy(wrong+7,prefix+7,7);memcpy(wrong+14,prefix,7);
 assert(!yb_literal_normalized(&n,original,os,wrong,ns)); /* reordered prefix */
 os=packet(original,aud_ps_irap,3);ns=annex(normalized,aud_ps_irap,1);
 memcpy(normalized+ns,prefix,pn);ns+=pn;ns+=annex(normalized+ns,aud_ps_irap+1,2);
 assert(yb_literal_normalized(&n,original,os,normalized,ns)); /* prefix before first PS */
 os=packet(original,nonirap,2);ns=annex(normalized,nonirap,2);
 assert(yb_literal_normalized(&n,original,os,normalized,ns));
 memcpy(wrong,prefix,pn);memcpy(wrong+pn,normalized,ns);
 assert(!yb_literal_normalized(&n,original,os,wrong,ns+pn)); /* non-IRAP injection */
 os=packet(original,aud_irap+1,1);memcpy(normalized,prefix,pn);ns=pn+annex(normalized+pn,aud_irap+1,1);
 assert(yb_literal_normalized(&n,original,os,normalized,ns));
 assert(!yb_literal_normalized(&n,original,os,normalized+pn,ns-pn)); /* required prefix omitted */
 /* hvcC initialization remains an independently required input contract. */
 struct yb_normalization unused={0};assert(yb_normalization_init(&unused,NULL,0,NULL,0));yb_normalization_clear(&unused);
 puts("14 exact upstream insertion contract cases PASS");return 0;
}
