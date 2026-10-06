#include "native_gpu_nlq_lut.h"
#include <limits.h>
#include <stdlib.h>
#include <string.h>
/* All admitted NLQ residuals fit [-2^17,2^17-1]. maximum<2^(den+1),
 * gain=2^(10-depth), clamp=2*gain*maximum, floor shift=den-5-depth.
 * Thus abs(unfloored residual)<2^17; negative floor reaches -2^17.
 * Keep independent runtime bounds checks, including int32 capacity. */
int yb_gpu_nlq_lut_build(const struct yb_nlq_config configs[3],int32_t out[YB_GPU_NLQ_LUT_ENTRIES])
{
 struct yb_nlq_config local[3];int32_t temporary[YB_GPU_NLQ_LUT_ENTRIES];
 if(!configs||!out||(uintptr_t)configs%_Alignof(struct yb_nlq_config)||(uintptr_t)out%_Alignof(int32_t))return YB_INVALID_ARGUMENT;
 uintptr_t a=(uintptr_t)configs,b=(uintptr_t)out;
 if(a>UINTPTR_MAX-sizeof(local)||b>UINTPTR_MAX-sizeof(temporary)||
    (a<b+sizeof(temporary)&&b<a+sizeof(local)))return YB_INVALID_ARGUMENT;
 memcpy(local,configs,sizeof(local));
 for(unsigned c=0;c<3;c++)if(local[c].bit_depth!=10||
    local[c].denominator!=local[0].denominator||yb_validate_nlq(&local[c])!=YB_OK)return YB_INVALID_CONFIG;
 for(unsigned c=0;c<3;c++)for(unsigned code=0;code<YB_GPU_NLQ_LUT_CODES;code++){
  int64_t value=0;
  if(yb_nlq(&local[c],(int64_t)code,&value)!=YB_OK||value<INT32_MIN||value>INT32_MAX||
     value<-131072||value>131071)return YB_INVALID_CONFIG;
  temporary[c*YB_GPU_NLQ_LUT_CODES+code]=(int32_t)value;
 }
 memcpy(out,temporary,sizeof(temporary));return YB_OK;
}
int yb_gpu_nlq_lut_configs_equal(const struct yb_nlq_config a[3],const struct yb_nlq_config b[3])
{
 if(!a||!b)return 0;
 for(unsigned c=0;c<3;c++)if(a[c].bit_depth!=b[c].bit_depth||a[c].denominator!=b[c].denominator||
   a[c].offset!=b[c].offset||a[c].slope!=b[c].slope||a[c].threshold!=b[c].threshold||a[c].maximum!=b[c].maximum)return 0;
 return 1;
}
int yb_gpu_nlq_lut_shader_patch(const char *source,size_t bytes,char **out,size_t *out_bytes)
{
 static const char original[]=
 "    int64_t residual=int64_t(0);\n"
 "    if (m[2]==int64_t(1)) {\n"
 "        int64_t distance=int64_t(sample_value.w)-m[7];\n"
 "        if (distance!=int64_t(0)) {\n"
 "            int64_t direction=distance>int64_t(0) ? int64_t(1) : -int64_t(1);\n"
 "            int64_t gain=int64_t(1) << (10-int(m[6]));\n"
 "            int64_t accumulator=((int64_t(2)*distance-direction)*m[8]+int64_t(2)*direction*m[9])*gain;\n"
 "            int64_t limit=int64_t(2)*gain*m[10];\n"
 "            residual=floor_power_two(bound(accumulator,-limit,limit),int(m[5])-5-int(m[6]));\n"
 "        }\n"
 "    }\n";
 static const char declaration[]=YB_GPU_NLQ_LUT_SHADER_MARKER
 "layout(std430,binding=2) readonly buffer NlqLookup { int yb_nlq_residuals[3072]; };\n";
 static const char replacement[]=
 "    int64_t residual=int64_t(0);\n"
 "    if (m[2]==int64_t(1)) {\n"
 "        residual=int64_t(yb_nlq_residuals[uint(component)*1024u+sample_value.w]);\n"
 "    }\n";
 if(!source||!out||!out_bytes||*out||!bytes||bytes>65536||memchr(source,0,bytes))return 0;
 char *terminated=malloc(bytes+1U);if(!terminated)return 0;
 memcpy(terminated,source,bytes);terminated[bytes]=0;source=terminated;
 const char *main=strstr(source,"void main()\n"),*old=strstr(source,original);
 if(!main||!old||main>=old||strstr(main+1,"void main()\n")||strstr(old+1,original)||strstr(source,YB_GPU_NLQ_LUT_SHADER_MARKER)){free(terminated);return 0;}
 size_t prefix=(size_t)(main-source),middle=(size_t)(old-main);
 size_t tail=bytes-(size_t)(old-source)-(sizeof(original)-1U);
 size_t length=prefix+sizeof(declaration)-1U+middle+sizeof(replacement)-1U+tail;
 if(length>65536){free(terminated);return 0;}
 char *text=malloc(length+1U);if(!text){free(terminated);return 0;}
 size_t at=0;
#define COPY(data,count) do{memcpy(text+at,data,count);at+=count;}while(0)
 COPY(source,prefix);COPY(declaration,sizeof(declaration)-1U);COPY(main,middle);
 COPY(replacement,sizeof(replacement)-1U);COPY(old+sizeof(original)-1U,tail);
#undef COPY
 text[at]=0;free(terminated);*out=text;*out_bytes=length;return 1;
}
int yb_gpu_nlq_lut_shader_has_marker(const char *source,size_t bytes)
{
 const char marker[]=YB_GPU_NLQ_LUT_SHADER_MARKER;
 if(!source||bytes<sizeof(marker)-1U||bytes>65536)return 0;
 for(size_t i=0;i<=bytes-(sizeof(marker)-1U);i++)
  if(!memcmp(source+i,marker,sizeof(marker)-1U))return 1;
 return 0;
}
