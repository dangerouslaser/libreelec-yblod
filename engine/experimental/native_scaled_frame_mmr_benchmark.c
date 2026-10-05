#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#include "native_scaled_surface.h"
#include "native_decoder_frame_bridge.h"
#include "native_mmr_composer.h"
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
struct stages { uint16_t *mapped,*out;int32_t *residual,*sum; };
struct workload {
 yb_integration_descriptor descriptor;
 yb_scaled_surface surface;
 void *blob;uint16_t *bl[4],*zero,*el;
 uint8_t frame[32],provenance[32];uint64_t counts[3];
};
struct measurement { uint64_t wall,cpu,preparation_wall,preparation_cpu; };
static int allocate_stages(struct stages *s)
{
 s->mapped=malloc(CHUNK*sizeof(*s->mapped));s->out=malloc(CHUNK*sizeof(*s->out));
 s->residual=malloc(CHUNK*sizeof(*s->residual));s->sum=malloc(CHUNK*sizeof(*s->sum));
 return s->mapped&&s->out&&s->residual&&s->sum;
}
static void free_stages(struct stages *s)
{ free(s->mapped);free(s->out);free(s->residual);free(s->sum); }
static int same_stages(const struct stages *a,const struct stages *b,uint32_t n)
{
 return !memcmp(a->mapped,b->mapped,(size_t)n*2) &&
        !memcmp(a->residual,b->residual,(size_t)n*4) &&
        !memcmp(a->sum,b->sum,(size_t)n*4) && !memcmp(a->out,b->out,(size_t)n*2);
}
static void save_stages(struct stages *a,const struct stages *b,uint32_t n)
{
 memcpy(a->mapped,b->mapped,(size_t)n*2);memcpy(a->residual,b->residual,(size_t)n*4);
 memcpy(a->sum,b->sum,(size_t)n*4);memcpy(a->out,b->out,(size_t)n*2);
}
static int completed(const yb_integration_completion *c,const struct workload *w)
{
 return c->kind==YB_ARITHMETIC_FRAME_COMPLETE && !c->diagnostic_queries &&
        c->counts[0]==w->counts[0] && c->counts[1]==w->counts[1] && c->counts[2]==w->counts[2];
}
static int create_mmr(yb_mmr_frame **mmr,const yb_integration_context *reference)
{
 return yb_mmr_frame_create(&reference->descriptor,&reference->mapping,
     reference->descriptor.enhancement_enabled ? reference->nlq : NULL,mmr);
}
static int dispatch(const struct workload *w,uint32_t c,uint64_t start,uint32_t count,
                    yb_integration_context *reference,yb_mmr_frame *mmr,struct stages *s)
{
 const uint16_t *y=c ? w->bl[3]+(size_t)start : w->bl[0]+(size_t)start;
 const uint16_t *cb=c ? w->bl[1]+(size_t)start : w->zero;
 const uint16_t *cr=c ? w->bl[2]+(size_t)start : w->zero;
 if(mmr)return yb_mmr_frame_process(mmr,w->frame,(int32_t)c,start,y,cb,cr,
     w->el,count,s->mapped,s->residual,s->sum,s->out);
 return yb_integration_integer(reference,w->frame,(int32_t)c,start,y,cb,cr,
     w->el,count,s->mapped,s->residual,s->sum,s->out);
}
static int verify_frame(const struct workload *w,struct stages *a,struct stages *b,
                        struct stages *golden,uint64_t *dispatches,uint32_t *last_count,
                        int routes[3],unsigned widths[2])
{
 yb_integration_context reference={0};yb_mmr_frame *mmr=NULL;
 yb_integration_completion rc={0},cc={0};int okay=0;
 if(yb_decoder_frame_bridge_init(&reference,&w->descriptor,w->blob,9216)||
    create_mmr(&mmr,&reference))goto end;
 for(int32_t c=0;c<3;c++){
  routes[c]=yb_mmr_frame_component_route(mmr,c);
  if(routes[c]!=0&&routes[c]!=1)goto end;
 }
 for(int32_t c=0;c<3;c++)for(int32_t i=0;i<YB_MAX_SEGMENTS;i++){
  int bits=yb_mmr_frame_segment_bits(mmr,c,i);
  if(bits<0)break;
  if(bits==64)widths[0]++;
  else if(bits==128)widths[1]++;
 }
 *dispatches=0;
 for(uint32_t c=0;c<3;c++)for(uint64_t start=0;start<w->counts[c];start+=CHUNK){
  uint32_t n=(uint32_t)(w->counts[c]-start);if(n>CHUNK)n=CHUNK;
  if(yb_scaled_surface_extract(&w->surface,w->frame,w->provenance,c,start,n,
       YB_SURFACE_EXACT_WHOLE_CODES,w->el)||dispatch(w,c,start,n,&reference,NULL,a)||
     dispatch(w,c,start,n,NULL,mmr,b)||!same_stages(a,b,n))goto end;
  ++*dispatches;*last_count=n;
 }
 if(yb_integration_finish(&reference,&rc)||yb_mmr_frame_finish(mmr,&cc)||
    !completed(&rc,w)||!completed(&cc,w))goto end;
 save_stages(golden,a,*last_count);okay=1;
end:yb_mmr_frame_destroy(mmr);yb_integration_reset(&reference);return okay;
}
static int timed_frame(const struct workload *w,int use_cache,struct stages *s,
                       const struct stages *golden,uint32_t last_count,struct measurement *m)
{
 yb_integration_context reference={0};yb_mmr_frame *mmr=NULL;
 yb_integration_completion complete={0};
 struct timespec begin,begin_cpu,prepared,prepared_cpu,finish,finish_cpu;
 if(clock_gettime(CLOCK_MONOTONIC,&begin)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&begin_cpu))goto end;
 if(yb_decoder_frame_bridge_init(&reference,&w->descriptor,w->blob,9216)||
    (use_cache&&create_mmr(&mmr,&reference)))goto end;
 if(clock_gettime(CLOCK_MONOTONIC,&prepared)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&prepared_cpu))goto end;
 for(uint32_t c=0;c<3;c++)for(uint64_t start=0;start<w->counts[c];start+=CHUNK){
  uint32_t n=(uint32_t)(w->counts[c]-start);if(n>CHUNK)n=CHUNK;
  if(yb_scaled_surface_extract(&w->surface,w->frame,w->provenance,c,start,n,
       YB_SURFACE_EXACT_WHOLE_CODES,w->el)||dispatch(w,c,start,n,&reference,mmr,s))goto end;
 }
 if((use_cache ? yb_mmr_frame_finish(mmr,&complete) : yb_integration_finish(&reference,&complete))||
    !completed(&complete,w))goto end;
 /* Equal lifetime policy: owned-plan teardown AND bridge reset inside totals. */
 yb_mmr_frame_destroy(mmr);mmr=NULL;yb_integration_reset(&reference);
 if(clock_gettime(CLOCK_MONOTONIC,&finish)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&finish_cpu)||
    !ns(&begin,&finish,&m->wall)||!ns(&begin_cpu,&finish_cpu,&m->cpu)||
    !ns(&begin,&prepared,&m->preparation_wall)||!ns(&begin_cpu,&prepared_cpu,&m->preparation_cpu))goto end;
 /* Untimed last-chunk observability crosscheck. Full-frame equivalence was
  * required before ANY timing. Compile external kernels separately, no LTO. */
 if(!same_stages(s,golden,last_count))goto end;
 return 1;
end:yb_mmr_frame_destroy(mmr);yb_integration_reset(&reference);return 0;
}
static void print_times(const struct measurement m[3])
{
 printf("{\"wall_ns\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],\"cpu_ns\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],\"preparation_wall_ns\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],\"preparation_cpu_ns\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]}",
  m[0].wall,m[1].wall,m[2].wall,m[0].cpu,m[1].cpu,m[2].cpu,
  m[0].preparation_wall,m[1].preparation_wall,m[2].preparation_wall,
  m[0].preparation_cpu,m[1].preparation_cpu,m[2].preparation_cpu);
}
int main(int argc,char **argv)
{
 uint32_t w,h;int status=1;
 if(yb_mmr_abi_version()!=1 || !yb_mmr_sizeof_plan() || !yb_mmr_sizeof_frame() ||
    yb_scaled_surface_abi_version()!=1 ||
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
 uint16_t *el=malloc(CHUNK*sizeof(*el));
 struct stages a={0},b={0},golden={0};
 uint16_t *zero=calloc(CHUNK,sizeof(*zero));
 if(!blob||!pixels||!el||!zero||!allocate_stages(&a)||!allocate_stages(&b)||
    !allocate_stages(&golden))goto end;
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
 for(uint32_t c=0;c<3;c++)for(uint64_t start=0;start<counts[c];start+=CHUNK){
  uint32_t count=(uint32_t)(counts[c]-start);if(count>CHUNK)count=CHUNK;
  if(yb_scaled_surface_extract(&surface,frame,provenance,c,start,count,
                              YB_SURFACE_EXACT_WHOLE_CODES,el))goto end;
 }
 struct workload work={0};work.descriptor=d;work.surface=surface;work.blob=blob;
 for(int i=0;i<4;i++)work.bl[i]=bl[i];
 work.zero=zero;work.el=el;memcpy(work.frame,frame,32);memcpy(work.provenance,provenance,32);
 memcpy(work.counts,counts,sizeof(counts));
 uint64_t dispatches=0;uint32_t last_count=0;int routes[3]={0};unsigned widths[2]={0};
 if(!verify_frame(&work,&a,&b,&golden,&dispatches,&last_count,routes,widths))goto end;
 struct measurement reference[3]={{0}},mmr[3]={{0}},warmup={0};
 if(!timed_frame(&work,0,&a,&golden,last_count,&warmup)||
    !timed_frame(&work,1,&b,&golden,last_count,&warmup))goto end;
 for(int repeat=0;repeat<3;repeat++)for(int order=0;order<2;order++){
  int use_cache=(repeat+order)&1;
  if(!timed_frame(&work,use_cache,use_cache ? &b : &a,&golden,last_count,
                  use_cache ? &mmr[repeat] : &reference[repeat]))goto end;
 }
 printf("{\"schema\":\"yblod.native-mmr-paired-benchmark.v1\",\"status\":\"complete\",\"all_four_stages_full_frame_byte_exact\":true,\"verification_scope\":\"untimed-full-frame-before-timing\",\"verified_dispatches\":%" PRIu64 ",\"verified_stage_values\":%" PRIu64 ",\"plan_bytes\":%" PRIu64 ",\"frame_bytes\":%" PRIu64 ",\"warmups_per_backend\":1,\"paired_repeats\":3,\"orders\":[\"reference,mmr\",\"mmr,reference\",\"reference,mmr\"],\"preparation_and_teardown_included\":true,\"timed_last_chunk_crosschecks\":8,\"timed_crosscheck_scope\":\"last-chunk-only-external-kernels-no-lto\",\"counts\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],\"reference\":",
 dispatches,(counts[0]+counts[1]+counts[2])*4,yb_mmr_sizeof_plan(),yb_mmr_sizeof_frame(),
 counts[0],counts[1],counts[2]);
 print_times(reference);printf(",\"mmr\":");print_times(mmr);
 printf(",\"component_routes\":[%d,%d,%d],\"mmr_segment_counts_by_64_128_bits\":[%u,%u]}\n",routes[0],routes[1],routes[2],widths[0],widths[1]);status=0;
end:
 if(status)fprintf(stderr,"benchmark rejected\n");
 free(blob);free(pixels);for(int i=0;i<4;i++)free(bl[i]);
 free(el);free_stages(&a);free_stages(&b);free_stages(&golden);free(zero);return status;
}

