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

/* Caller externally pins files, executable, libraries and cgroup. Offline CPU
 * diagnostic, not playback FPS. No metadata JSON or fractional rounding. */
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
  fprintf(stderr,"usage: benchmark width height instructions BL-Y BL-Cb BL-Cr guide P010\n");return 1;
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
 uint64_t counts[3]={ycount,ccount,ccount},timings[3]={0};
 for(uint32_t c=0;c<3;c++)for(uint64_t start=0;start<counts[c];start+=CHUNK){
  uint32_t count=(uint32_t)(counts[c]-start);if(count>CHUNK)count=CHUNK;
  if(yb_scaled_surface_extract(&surface,frame,provenance,c,start,count,
                              YB_SURFACE_EXACT_WHOLE_CODES,el))goto end;
 }
 for(int repeat=0;repeat<4;repeat++){
  yb_integration_context context={0};yb_integration_completion complete={0};
  if(yb_decoder_frame_bridge_init(&context,&d,blob,9216))goto end;
  struct timespec begin,finish;
  if(clock_gettime(CLOCK_MONOTONIC,&begin))goto end;
  for(uint32_t c=0;c<3;c++)for(uint64_t start=0;start<counts[c];start+=CHUNK){
   uint32_t count=(uint32_t)(counts[c]-start);if(count>CHUNK)count=CHUNK;
   if(yb_scaled_surface_extract(&surface,frame,provenance,c,start,count,
         YB_SURFACE_EXACT_WHOLE_CODES,el)||
      yb_integration_integer(&context,frame,(int32_t)c,start,
         c?bl[3]+(size_t)start:bl[0]+(size_t)start,
         c?bl[1]+(size_t)start:zero,c?bl[2]+(size_t)start:zero,
         el,count,mapped,residual,sum,out))goto end;
  }
  if(yb_integration_finish(&context,&complete)||clock_gettime(CLOCK_MONOTONIC,&finish)||
     complete.kind!=YB_ARITHMETIC_FRAME_COMPLETE||complete.diagnostic_queries)goto end;
  for(int c=0;c<3;c++)if(complete.counts[c]!=counts[c])goto end;
  if(repeat&&!ns(&begin,&finish,&timings[repeat-1]))goto end;
  yb_integration_reset(&context);
 }
 printf("{\"status\":\"complete\",\"warmup\":1,\"repeats\":3,\"nanoseconds\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],\"counts\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]}\n",
 timings[0],timings[1],timings[2],counts[0],counts[1],counts[2]);status=0;
end:
 if(status)fprintf(stderr,"benchmark rejected\n");
 free(blob);free(pixels);for(int i=0;i<4;i++)free(bl[i]);
 free(el);free(mapped);free(out);free(residual);free(sum);free(zero);return status;
}
