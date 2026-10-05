#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#include "native_scaled_surface.h"
#include "native_decoder_frame_bridge.h"
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* Separate instrumented profiling diagnostic. Baseline benchmark untouched.
 * Caller externally pins inputs/build/libraries/cgroup. Both clocks required.
 * Clock calls perturb execution; totals do NOT decompose the independent
 * uninstrumented benchmark additively. No playback FPS claim. */
enum { CHUNK=65536 };
static int stable(const struct stat *a,const struct stat *b)
{
#ifdef __APPLE__
#define MT st_mtimespec
#define CT st_ctimespec
#else
#define MT st_mtim
#define CT st_ctim
#endif
 return a->st_dev==b->st_dev && a->st_ino==b->st_ino && a->st_size==b->st_size &&
  a->MT.tv_sec==b->MT.tv_sec && a->MT.tv_nsec==b->MT.tv_nsec &&
  a->CT.tv_sec==b->CT.tv_sec && a->CT.tv_nsec==b->CT.tv_nsec;
#undef MT
#undef CT
}
static void *load(const char *path,size_t bytes)
{
 static struct stat identities[6];static size_t loaded;
 int fd=open(path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK); struct stat a,b,c;
 if(fd<0)return NULL;
 void *p=NULL; size_t done=0;
 if(fstat(fd,&a)||!S_ISREG(a.st_mode)||a.st_size<0||(uint64_t)a.st_size!=bytes)goto end;
 if(loaded>=6)goto end;
 for(size_t i=0;i<loaded;i++)
  if(a.st_dev==identities[i].st_dev&&a.st_ino==identities[i].st_ino)goto end;
 p=malloc(bytes);if(!p)goto end;
 while(done<bytes){size_t n=bytes-done;if(n>65536)n=65536;
  ssize_t got=read(fd,(unsigned char *)p+done,n);
  if(got<0&&errno==EINTR)continue;
  if(got<=0)goto fail;
  done+=(size_t)got;
 }
 unsigned char extra;
 if(read(fd,&extra,1)!=0||fstat(fd,&b)||lstat(path,&c)||!S_ISREG(c.st_mode)||
    !stable(&a,&b)||!stable(&a,&c))goto fail;
 identities[loaded++]=a;goto end;
fail:free(p);p=NULL;
end:close(fd);return p;
}
static int whole(uint16_t *p,size_t count)
{
 unsigned char *raw=(unsigned char *)p;
 for(size_t i=0;i<count;i++){
  uint16_t v=(uint16_t)((uint16_t)raw[2*i]|((uint16_t)raw[2*i+1]<<8));
  if(v>1023)return 0;
  p[i]=v;
 }
 return 1;
}
static int number(const char *s,uint32_t *v)
{
 uint32_t n=0;if(!*s)return 0;
 for(;*s;s++){if(*s<'0'||*s>'9'||n>3840)return 0;n=n*10U+(uint32_t)(*s-'0');}
 if(!n||n>3840||(n&1U))return 0;
 *v=n;return 1;
}
static int ns(const struct timespec *a,const struct timespec *b,uint64_t *result)
{
 if(a->tv_sec<0 || b->tv_sec<a->tv_sec || a->tv_nsec<0 ||
    b->tv_nsec<0 || a->tv_nsec>=1000000000 || b->tv_nsec>=1000000000)return 0;
 uint64_t seconds=(uint64_t)b->tv_sec-(uint64_t)a->tv_sec;
 int64_t nanos=(int64_t)b->tv_nsec-(int64_t)a->tv_nsec;
 if(nanos<0){if(!seconds)return 0;seconds--;nanos+=1000000000;}
 if(seconds>UINT64_MAX/1000000000U)return 0;
 uint64_t base=seconds*1000000000U;
 if((uint64_t)nanos>UINT64_MAX-base)return 0;
 *result=base+(uint64_t)nanos;return 1;
}

typedef struct { struct timespec wall, cpu; } clock_pair;
typedef struct { uint64_t wall, cpu; } elapsed_pair;
static int clocks(clock_pair *value)
{
#ifdef CLOCK_PROCESS_CPUTIME_ID
 if(clock_gettime(CLOCK_MONOTONIC,&value->wall) ||
    clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&value->cpu)) {
  fprintf(stderr,"required profiling clocks unavailable\n");return 0;
 }
 return 1;
#else
 (void)value;fprintf(stderr,"process CPU clock unavailable\n");return 0;
#endif
}
static int elapsed(const clock_pair *begin,const clock_pair *finish,elapsed_pair *value)
{
 return ns(&begin->wall,&finish->wall,&value->wall) &&
        ns(&begin->cpu,&finish->cpu,&value->cpu);
}
static int accumulate(elapsed_pair *total,const elapsed_pair *part)
{
 if(part->wall>UINT64_MAX-total->wall || part->cpu>UINT64_MAX-total->cpu)return 0;
 total->wall+=part->wall;total->cpu+=part->cpu;return 1;
}
static void vector(const elapsed_pair *values,int cpu)
{
 printf("[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]",
        cpu?values[0].cpu:values[0].wall,cpu?values[1].cpu:values[1].wall,
        cpu?values[2].cpu:values[2].wall);
}
static void matrix(const elapsed_pair values[3][3],int cpu)
{
 printf("[");for(int i=0;i<3;i++){if(i)printf(",");vector(values[i],cpu);}printf("]");
}
int main(int argc,char **argv)
{
 uint32_t w,h;int status=1;
 if(yb_scaled_surface_abi_version()!=1 ||
    yb_scaled_surface_sizeof_descriptor()!=sizeof(yb_scaled_surface) ||
    yb_decoder_frame_bridge_abi_version()!=1 ||
    yb_decoder_frame_bridge_sizeof_instructions()!=sizeof(yb_dovi_integer_instructions) ||
    sizeof(yb_dovi_integer_instructions)!=9216 || yb_integration_abi_version()!=1 ||
    yb_integration_sizeof_descriptor()!=sizeof(yb_integration_descriptor) ||
    yb_integration_sizeof_context()!=sizeof(yb_integration_context) ||
    yb_integration_sizeof_completion()!=sizeof(yb_integration_completion) ||
    yb_abi_version()!=1 || yb_sizeof_mapping_config()!=sizeof(struct yb_mapping_config) ||
    yb_sizeof_nlq_config()!=sizeof(struct yb_nlq_config) ||
    yb_sizeof_component_mapping()!=sizeof(struct yb_component_mapping) ||
    yb_sizeof_segment()!=sizeof(struct yb_segment))return 1;
 if(argc!=9||!number(argv[1],&w)||!number(argv[2],&h)||h>2160){
  fprintf(stderr,"usage: profile width height instructions BL-Y BL-Cb BL-Cr guide P010\n");return 1;
 }
 size_t ycount=(size_t)w*h,ccount=ycount/4;
 if(ycount*9U+9216U>128U*1024U*1024U)return 1;
 void *blob=load(argv[3],9216);
 uint16_t *bl[4]={load(argv[4],ycount*2),load(argv[5],ccount*2),
                 load(argv[6],ccount*2),load(argv[7],ccount*2)};
 unsigned char *pixels=load(argv[8],ycount*3);
 uint16_t *el=malloc(CHUNK*sizeof(*el)),*mapped=malloc(CHUNK*sizeof(*mapped)),
          *out=malloc(CHUNK*sizeof(*out));
 int32_t *residual=malloc(CHUNK*sizeof(*residual)),*sum=malloc(CHUNK*sizeof(*sum));
 uint16_t *zero=calloc(CHUNK,sizeof(*zero));
 if(!blob||!pixels||!el||!mapped||!out||!residual||!sum||!zero)goto end;
 for(int i=0;i<4;i++)if(!bl[i]||!whole(bl[i],i==0?ycount:ccount))goto end;
 yb_dovi_integer_instructions instructions;
 if(sizeof(instructions)!=9216)goto end;
 memcpy(&instructions,blob,sizeof(instructions));
 if(instructions.residual_enabled!=1||instructions.mapping.bit_depth!=10||
    instructions.version!=1)goto end;
 for(int i=0;i<3;i++)if(instructions.nlq[i].bit_depth!=10)goto end;
 if(yb_validate_mapping(&instructions.mapping))goto end;
 for(int i=0;i<instructions.mapping.components[0].pivot_count-1;i++)
  if(instructions.mapping.components[0].segments[i].method!=YB_POLYNOMIAL)goto end;
 yb_integration_descriptor d={0};d.version=1;d.input_kind=YB_INPUT_WHOLE_CODES;
 d.width=w;d.height=h;d.output_depth=instructions.output_depth;d.enhancement_enabled=1;
 d.frame_id[0]=1;d.provenance_id[0]=2;
 uint8_t frame[32]={1},provenance[32]={2};
 yb_scaled_surface surface={0};surface.version=1;surface.format=YB_SURFACE_NATIVE10_Q6;
 surface.width=w;surface.height=h;surface.coherent_ready=1;surface.allocation=pixels;
 surface.allocation_bytes=ycount*3;surface.uv_offset=ycount*2;
 surface.y_stride=(uint64_t)w*2;surface.uv_stride=(uint64_t)w*2;
 memcpy(surface.frame_id,frame,32);memcpy(surface.provenance_id,provenance,32);
 uint64_t counts[3]={ycount,ccount,ccount};
 elapsed_pair full[3]={{0}},initialization[3]={{0}},completion[3]={{0}};
 elapsed_pair extraction[3][3]={{{0}}},reconstruction[3][3]={{{0}}};
 uint64_t calls[3]={0};
 for(uint32_t c=0;c<3;c++)for(uint64_t start=0;start<counts[c];start+=CHUNK){
  uint32_t count=(uint32_t)(counts[c]-start);if(count>CHUNK)count=CHUNK;
  if(yb_scaled_surface_extract(&surface,frame,provenance,c,start,count,
                              YB_SURFACE_EXACT_WHOLE_CODES,el))goto end;
 }
 for(int repeat=0;repeat<4;repeat++){
  yb_integration_context context={0};yb_integration_completion complete={0};
  clock_pair begin,finish,a,b;elapsed_pair part;
  elapsed_pair extracts[3]={{0}},reconstructs[3]={{0}};
  uint64_t actual_calls[3]={0};
  if(!clocks(&begin) || !clocks(&a))goto end;
  if(yb_decoder_frame_bridge_init(&context,&d,blob,9216) || !clocks(&b) ||
     !elapsed(&a,&b,&part))goto end;
  if(repeat)initialization[repeat-1]=part;
  for(uint32_t c=0;c<3;c++)for(uint64_t first=0;first<counts[c];first+=CHUNK){
   uint32_t count=(uint32_t)(counts[c]-first);if(count>CHUNK)count=CHUNK;
   if(!clocks(&a) ||
      yb_scaled_surface_extract(&surface,frame,provenance,c,first,count,
         YB_SURFACE_EXACT_WHOLE_CODES,el) ||
      !clocks(&b) || !elapsed(&a,&b,&part) || !accumulate(&extracts[c],&part))goto end;
   if(!clocks(&a) ||
      yb_integration_integer(&context,frame,(int32_t)c,first,
         c?bl[3]+(size_t)first:bl[0]+(size_t)first,
         c?bl[1]+(size_t)first:zero,c?bl[2]+(size_t)first:zero,
         el,count,mapped,residual,sum,out) ||
      !clocks(&b) || !elapsed(&a,&b,&part) || !accumulate(&reconstructs[c],&part))goto end;
   actual_calls[c]++;
  }
  if(!clocks(&a) || yb_integration_finish(&context,&complete) || !clocks(&b) ||
     !elapsed(&a,&b,&part) || complete.kind!=YB_ARITHMETIC_FRAME_COMPLETE ||
     complete.diagnostic_queries)goto end;
  for(int c=0;c<3;c++){
   uint64_t expected=(counts[c]+CHUNK-1U)/CHUNK;
   if(complete.counts[c]!=counts[c] || actual_calls[c]!=expected)goto end;
   if(repeat){extraction[repeat-1][c]=extracts[c];
    reconstruction[repeat-1][c]=reconstructs[c];calls[c]=actual_calls[c];}
  }
  if(repeat)completion[repeat-1]=part;
  if(!clocks(&finish) || !elapsed(&begin,&finish,&part))goto end;
  if(repeat)full[repeat-1]=part;
  yb_integration_reset(&context);
 }
 printf("{\"schema\":\"yblod.native-scaled-frame-profile.v1\",\"status\":\"complete\","
        "\"diagnostic_only\":true,\"baseline_modified\":false,\"warmup\":1,\"repeats\":3,"
        "\"clock_wall\":\"CLOCK_MONOTONIC\",\"clock_cpu\":\"CLOCK_PROCESS_CPUTIME_ID\","
        "\"counts\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],"
        "\"chunk_calls_per_run\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],"
        "\"all_frame_completions_verified\":true,\"stage_sum_equals_end_to_end_claim\":false,"
        "\"nanoseconds\":",counts[0],counts[1],counts[2],calls[0],calls[1],calls[2]);
 vector(full,0);printf(",\"process_cpu_nanoseconds\":");vector(full,1);
 printf(",\"initialization_wall_ns\":");vector(initialization,0);
 printf(",\"initialization_cpu_ns\":");vector(initialization,1);
 printf(",\"completion_wall_ns\":");vector(completion,0);
 printf(",\"completion_cpu_ns\":");vector(completion,1);
 printf(",\"extraction_wall_ns_by_run_component\":");matrix(extraction,0);
 printf(",\"extraction_cpu_ns_by_run_component\":");matrix(extraction,1);
 printf(",\"reconstruction_wall_ns_by_run_component\":");matrix(reconstruction,0);
 printf(",\"reconstruction_cpu_ns_by_run_component\":");matrix(reconstruction,1);
 printf("}\n");status=0;
end:
 if(status)fprintf(stderr,"benchmark rejected\n");
 free(blob);free(pixels);for(int i=0;i<4;i++)free(bl[i]);
 free(el);free(mapped);free(out);free(residual);free(sum);free(zero);return status;
}
