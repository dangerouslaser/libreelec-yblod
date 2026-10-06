#define _GNU_SOURCE 1
#include "native_gpu_nlq_lut.h"
#include <sys/mman.h>
#include <unistd.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc,char **argv)
{
 if(argc!=2)return 2;
 struct yb_nlq_config configs[3]={{0}},other[3];int32_t table[YB_GPU_NLQ_LUT_ENTRIES],saved[YB_GPU_NLQ_LUT_ENTRIES];
 uint64_t compared=0,composed=0;int64_t minimum=0,maximum=0;
 for(int den=15;den<=32;den++)for(unsigned offset=0;offset<3;offset++)for(unsigned flags=0;flags<8;flags++){
  const uint64_t limit=UINT64_C(1)<<(den+1);
  for(unsigned c=0;c<3;c++){
   configs[c].bit_depth=10;configs[c].denominator=den;
   configs[c].offset=offset==0?0:offset==1?512:1023;
   configs[c].slope=(flags&1U)?limit-1U:0;
   configs[c].threshold=(flags&2U)?limit-1U:0;
   configs[c].maximum=(flags&4U)?limit-1U:0;
  }
  assert(yb_gpu_nlq_lut_build(configs,table)==YB_OK);
  for(unsigned c=0;c<3;c++)for(unsigned code=0;code<1024;code++){
   int64_t expected=0;assert(yb_nlq(&configs[c],(int64_t)code,&expected)==YB_OK);
   assert(table[c*1024+code]==expected);compared++;
   if(expected<minimum)minimum=expected;
   if(expected>maximum)maximum=expected;
   static const int64_t mapped[]={0,1,32768,65534,65535};
   for(unsigned m=0;m<5;m++)for(int depth=10;depth<=12;depth+=2){
    uint16_t direct=0,lookup=0;
    assert(yb_compose(&configs[c],mapped[m],code,depth,&direct)==YB_OK);
    assert(yb_compose_residual(mapped[m],table[c*1024+code],depth,&lookup)==YB_OK);
    assert(direct==lookup);composed++;
   }
  }
 }
 assert(minimum==-131072&&maximum==131071);
 for(unsigned trial=0;trial<8;trial++){
  int den=15+(int)((trial*5U)%18U);uint64_t limit=UINT64_C(1)<<(den+1);
  for(unsigned c=0;c<3;c++){
   configs[c].bit_depth=10;configs[c].denominator=den;
   configs[c].offset=(int32_t)((trial*137U+c*71U+23U)%1024U);
   configs[c].slope=limit/(17U+trial+c)+7U;
   configs[c].threshold=limit/(129U+trial+c)+3U;
   configs[c].maximum=limit/3U+17U;
  }
  assert(yb_gpu_nlq_lut_build(configs,table)==YB_OK);
  for(unsigned c=0;c<3;c++)for(unsigned code=0;code<1024;code++){
   int64_t expected=0;assert(yb_nlq(&configs[c],code,&expected)==YB_OK);
   assert(table[c*1024+code]==expected);compared++;
   uint16_t direct=0,lookup=0;
   assert(yb_compose(&configs[c],32768,code,12,&direct)==YB_OK);
   assert(yb_compose_residual(32768,table[c*1024+code],12,&lookup)==YB_OK);
   assert(direct==lookup);composed++;
   if(code==(unsigned)configs[c].offset)assert(expected==0);
  }
 }
 memcpy(other,configs,sizeof(other));assert(yb_gpu_nlq_lut_configs_equal(configs,other));
 other[0].offset--;assert(!yb_gpu_nlq_lut_configs_equal(configs,other));
 for(unsigned c=0;c<3;c++){
#define DIFFERENT(field) do{memcpy(other,configs,sizeof(other));other[c].field--;assert(!yb_gpu_nlq_lut_configs_equal(configs,other));}while(0)
  DIFFERENT(bit_depth);DIFFERENT(denominator);DIFFERENT(offset);
  DIFFERENT(slope);DIFFERENT(threshold);DIFFERENT(maximum);
#undef DIFFERENT
 }
 for(unsigned i=0;i<YB_GPU_NLQ_LUT_ENTRIES;i++)table[i]=12345;
 memcpy(saved,table,sizeof(saved));other[0].bit_depth=9;
 assert(yb_gpu_nlq_lut_build(other,table)==YB_INVALID_CONFIG&&!memcmp(table,saved,sizeof(table)));
 assert(yb_gpu_nlq_lut_build(NULL,table)==YB_INVALID_ARGUMENT);
 assert(yb_gpu_nlq_lut_build(configs,NULL)==YB_INVALID_ARGUMENT);
 other[0]=configs[0];other[1].denominator=31;
 assert(yb_gpu_nlq_lut_build(other,table)==YB_INVALID_CONFIG&&!memcmp(table,saved,sizeof(table)));
 FILE *file=fopen(argv[1],"rb");assert(file);char source[65537];size_t bytes=fread(source,1,65536,file);
 assert(bytes&&bytes<65536&&!ferror(file)&&feof(file));assert(!fclose(file));source[bytes]=0;
 char *patched=NULL;size_t length=0;
 assert(yb_gpu_nlq_lut_shader_patch(source,bytes,&patched,&length));
 assert(patched&&length==strlen(patched)&&strstr(patched,YB_GPU_NLQ_LUT_SHADER_MARKER));
 assert(strstr(patched,"yb_nlq_residuals[uint(component)*1024u+sample_value.w]"));
 assert(!strstr(patched,"int64_t accumulator=((int64_t(2)*distance-direction)"));
 assert(strstr(patched,"int64_t summed=mapped+residual;"));
 long page_size=sysconf(_SC_PAGESIZE);assert(page_size>0);size_t page=(size_t)page_size;
 size_t writable=(bytes+page-1U)/page*page;
 void *region=mmap(NULL,writable+page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 assert(region!=MAP_FAILED&&mprotect((char *)region+writable,page,PROT_NONE)==0);
 char *span=(char *)region+writable-bytes;memcpy(span,source,bytes);
 char *bounded=NULL;size_t bounded_bytes=0;
 assert(yb_gpu_nlq_lut_shader_patch(span,bytes,&bounded,&bounded_bytes));
 assert(bounded_bytes==length&&!memcmp(bounded,patched,length+1U));
 free(bounded);assert(munmap(region,writable+page)==0);
 char *repatch=NULL;size_t invalid_length=777;
 assert(!yb_gpu_nlq_lut_shader_patch(patched,length,&repatch,&invalid_length)&&!repatch&&invalid_length==777);
 free(patched);patched=NULL;
 char *gain=strstr(source,"int64_t gain=");assert(gain);gain[8]='x';
 assert(!yb_gpu_nlq_lut_shader_patch(source,bytes,&patched,&invalid_length)&&!patched&&invalid_length==777);
 printf("NLQ table exact residual comparisons=%llu composition comparisons=%llu bounds=[%lld,%lld]; invalid input atomicity/cache/shader splice PASS\n",
        (unsigned long long)compared,(unsigned long long)composed,(long long)minimum,(long long)maximum);
 return 0;
}
