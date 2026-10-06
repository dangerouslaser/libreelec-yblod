/* Public deterministic whole-code composer fixtures; no film or DV parser.
 * Instruction blob is explicitly a same-build ABI artifact, not interchange. */
#include "native_dovi_adapter.h"
#include "native_gpu_guard.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#define WIDTH 64U
#define HEIGHT 64U
static int write_new(const char *directory,const char *name,const void *data,size_t bytes)
{
 char path[4096];int n=snprintf(path,sizeof(path),"%s/%s",directory,name);
 if(n<0||(size_t)n>=sizeof(path))return 0;
 FILE *f=fopen(path,"wbx");if(!f)return 0;
 int okay=fwrite(data,1,bytes,f)==bytes;
 if(fclose(f))okay=0;
 return okay;
}
int main(int argc,char **argv)
{
 if((argc!=4&&argc!=5)||strlen(argv[2])!=1||strlen(argv[3])!=2)return 2;
 int small=argc==5;
 if(small&&strcmp(argv[4],"small"))return 2;
 unsigned order=(unsigned)(argv[2][0]-'0');
 int output=!strcmp(argv[3],"10")?10:!strcmp(argv[3],"12")?12:0;
 const uint16_t endian=1;
 if(order<1||order>3||!output||*(const uint8_t *)&endian!=1)return 2;
 yb_dovi_integer_instructions instruction={0};
 instruction.version=1;instruction.residual_enabled=1;instruction.output_depth=output;
 instruction.mapping.bit_depth=10;instruction.mapping.denominator=order==2?32:23;
 const int32_t pivots[]={0,1,100,300,700,1023};
 for(unsigned c=0;c<3;c++){
  struct yb_component_mapping *curve=&instruction.mapping.components[c];
  curve->pivot_count=6;memcpy(curve->pivots,pivots,sizeof(pivots));
  for(unsigned s=0;s<5;s++){
   struct yb_segment *segment=&curve->segments[s];
   segment->method=c?YB_MMR:YB_POLYNOMIAL;segment->order=c?(int32_t)order:2;
   int64_t scale=INT64_C(1)<<(instruction.mapping.denominator-3);
   if(!c){segment->coefficients[0][0]=scale;segment->coefficients[0][1]=scale*6;
    segment->coefficients[0][2]=(s&1U)?scale:-scale;}
   else{
    segment->constant=(s&1U)?-scale:scale;
    for(unsigned r=0;r<order;r++)for(unsigned t=0;t<7;t++){
     int64_t coefficient=scale/(int64_t)(r+t+1U);
     segment->coefficients[r][t]=((r+t+s+c)&1U)?coefficient:-coefficient;
    }
   }
  }
  struct yb_nlq_config *nlq=&instruction.nlq[c];
  nlq->bit_depth=10;nlq->denominator=instruction.mapping.denominator;
  nlq->offset=c==0?512:c==1?0:1023;
  nlq->slope=UINT64_C(1)<<(nlq->denominator-(small?12:1));
  nlq->threshold=UINT64_C(1)<<(nlq->denominator-(small?15:5));
  nlq->maximum=UINT64_C(1)<<(nlq->denominator-(small?4:3));
  if(yb_validate_nlq(nlq))return 1;
 }
 struct yb_gpu_width_report bounds;
 if(sizeof(instruction)!=9216||yb_validate_mapping(&instruction.mapping)||
    yb_gpu_check_mapping_width(&instruction.mapping,&bounds)||!bounds.supported)return 1;
 const uint16_t codes[]={0,1,2,99,100,101,299,300,301,511,512,513,699,700,701,1021,1022,1023};
 uint16_t y[WIDTH*HEIGHT],cb[WIDTH*HEIGHT/4],cr[WIDTH*HEIGHT/4],guide[WIDTH*HEIGHT/4];
 uint16_t p010[WIDTH*HEIGHT*3/2];
 for(unsigned i=0;i<WIDTH*HEIGHT;i++){
  y[i]=codes[i%18U];p010[i]=(uint16_t)(codes[(i*7U+5U)%18U]<<6U);
 }
 for(unsigned i=0;i<WIDTH*HEIGHT/4;i++){
  cb[i]=codes[(i/18U)%18U];cr[i]=codes[(i/324U+i)%18U];guide[i]=codes[i%18U];
  p010[WIDTH*HEIGHT+2U*i]=(uint16_t)(codes[(i*5U)%18U]<<6U);
  p010[WIDTH*HEIGHT+2U*i+1U]=(uint16_t)(codes[(i*11U+17U)%18U]<<6U);
 }
 if(!write_new(argv[1],"instructions.bin",&instruction,sizeof(instruction))||
    !write_new(argv[1],"bl_Y.u16le",y,sizeof(y))||!write_new(argv[1],"bl_Cb.u16le",cb,sizeof(cb))||
    !write_new(argv[1],"bl_Cr.u16le",cr,sizeof(cr))||!write_new(argv[1],"mmr_luma.u16le",guide,sizeof(guide))||
    !write_new(argv[1],"scaled1.p010",p010,sizeof(p010)))return 1;
 printf("{\"public_synthetic\":true,\"width\":64,\"height\":64,\"mmr_order\":%u,\"output_depth\":%d,\"pivots_per_component\":6,\"signed_coefficients\":true,\"nlq_offsets\":[512,0,1023],\"denominator\":%d,\"small_slope\":%s}\n",order,output,instruction.mapping.denominator,small?"true":"false");
 return 0;
}
