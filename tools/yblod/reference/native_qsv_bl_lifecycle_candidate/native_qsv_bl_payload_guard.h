/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Literal BSF guard. Only complete hvcC-derived parameter-set prefix at byte0
 * is admitted; arbitrary injection, relocation, dropping and rewriting fail. */
#ifndef YB_BL_PAYLOAD_GUARD_H
#define YB_BL_PAYLOAD_GUARD_H
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
struct yb_normalization {unsigned length_size;uint8_t *prefix;size_t prefix_size;};
static void yb_normalization_clear(struct yb_normalization *n)
{free(n->prefix);*n=(struct yb_normalization){0};}
static int yb_normalization_init(struct yb_normalization *out,const uint8_t *h,size_t size,const uint8_t *converted,size_t converted_size)
{
 if(!out||size>65536||converted_size>65536)return 0;
 struct yb_normalization n={0};
 if(!size||(size>=3&&h&&!h[0]&&!h[1]&&(h[2]==1||(size>=4&&!h[2]&&h[3]==1)))){*out=n;return 1;}
 if(!h||size<23||h[0]!=1||h[22]>64)return 0;
 n.length_size=(h[21]&3)+1;n.prefix=malloc(65536);if(!n.prefix)return 0;
 size_t at=23;unsigned nal_count=0;
 for(unsigned array=0;array<h[22];array++){
  if(size-at<3)goto fail;
  unsigned type=h[at++]&63,count=((unsigned)h[at]<<8)|h[at+1];at+=2;
  if(type<32||type>34)goto fail;
  for(unsigned i=0;i<count;i++){
   if(size-at<2||++nal_count>4096)goto fail;
   size_t bytes=((unsigned)h[at]<<8)|h[at+1];at+=2;
   if(bytes<2||bytes>size-at||((h[at]>>1)&63)!=type||bytes+4>65536-n.prefix_size)goto fail;
   memcpy(n.prefix+n.prefix_size,"\0\0\0\1",4);n.prefix_size+=4;
   memcpy(n.prefix+n.prefix_size,h+at,bytes);n.prefix_size+=bytes;at+=bytes;
  }
 }
 if(at!=size||n.prefix_size!=converted_size||(converted_size&&(!converted||memcmp(n.prefix,converted,converted_size))))goto fail;
 *out=n;return 1;
fail:free(n.prefix);return 0;
}
static int yb_literal_normalized_at(const struct yb_normalization *n,const uint8_t *original,size_t original_size,const uint8_t *normalized,size_t normalized_size,size_t offset)
{
 size_t at=0,out=offset;unsigned count=0;
 while(at<original_size){
  if(original_size-at<n->length_size||++count>4096)return 0;
  uint32_t bytes=0;for(unsigned i=0;i<n->length_size;i++)bytes=(bytes<<8)|original[at++];
  if(bytes<2||bytes>original_size-at||out>normalized_size||normalized_size-out<4||bytes>normalized_size-out-4)return 0;
  if(memcmp(normalized+out,"\0\0\0\1",4)||memcmp(normalized+out+4,original+at,bytes))return 0;
  at+=bytes;out+=4+bytes;
 }
 return count&&out==normalized_size;
}
static int yb_literal_normalized(const struct yb_normalization *n,const uint8_t *original,size_t original_size,const uint8_t *normalized,size_t normalized_size)
{
 if(!n||n->length_size>4||!original||!normalized||!original_size||original_size>64*1024*1024||normalized_size>65*1024*1024)return 0;
 if(!n->length_size)return original_size==normalized_size&&!memcmp(original,normalized,original_size);
 if(yb_literal_normalized_at(n,original,original_size,normalized,normalized_size,0))return 1;
 return n->prefix_size&&n->prefix_size<=normalized_size&&!memcmp(normalized,n->prefix,n->prefix_size)&&yb_literal_normalized_at(n,original,original_size,normalized,normalized_size,n->prefix_size);
}
#endif
