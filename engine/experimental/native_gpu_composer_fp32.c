#include "native_gpu_composer_fp32.h"
#include "native_libplacebo_reshape.h"
#include <stdlib.h>
#include <string.h>

/* Compile reviewed experimental hybrid backend with these symbol prefixes. */
int yb_fp_backend_create(const yb_gpu_backend_create_info *,yb_gpu_composer_backend **);
int yb_fp_backend_submit(yb_gpu_composer_backend *,const yb_gpu_backend_plan *);
int yb_fp_backend_finish(yb_gpu_composer_backend *,uint64_t,yb_gpu_backend_output *);
int yb_fp_backend_destroy(yb_gpu_composer_backend **);
int yb_fp_backend_abandon_destroyed_context(yb_gpu_composer_backend **,uint32_t);

struct topology { int32_t count[3],method[3][8],order[3][8]; };
struct entry { struct topology key; yb_gpu_composer_backend *backend; };
struct yb_gpu_fp32 {
    yb_gpu_backend_create_info owner;
    char *canonical;
    struct entry entries[2];
    yb_gpu_composer_backend *integer;
    yb_gpu_composer_backend *staged;
    int active,pending,failed,closing;
    unsigned next;
    yb_gpu_fp32_stats stats;
};
static void increment(uint64_t *value){if(*value!=UINT64_MAX)(*value)++;}
static struct topology topology(const yb_gpu_backend_plan *p)
{
    struct topology t;memset(&t,0,sizeof(t));
    for(int c=0;c<3;c++) {
        t.count[c]=p->mapping.components[c].pivot_count;
        for(int s=0;s<t.count[c]-1;s++) {
            t.method[c][s]=p->mapping.components[c].segments[s].method;
            t.order[c][s]=p->mapping.components[c].segments[s].order;
        }
    }
    return t;
}
static int shader(yb_gpu_fp32 *b,const yb_gpu_backend_plan *p,char **out,size_t *size)
{
    int64_t m[3][419];
    for(uint32_t c=0;c<3;c++)if(yb_gpu_backend_pack_metadata(p,c,m[c]))return 0;
    char *fragment=NULL;size_t n=0;
    if(yb_libplacebo_reshape_fragment(m,&fragment,&n))return 0;
    const char *begin=strstr(b->canonical,"    int64_t total=int64_t(0);\n");
    const char *end=begin?strstr(begin,"    int64_t residual=int64_t(0);\n"):NULL;
    const char *main=strstr(b->canonical,"void main()\n");
    const char *mapped=begin?strstr(begin,"int64_t mapped=bound(floor_power_two(total,int(m[5])+4)"):NULL;
    const char *replacement="    int64_t mapped=int64_t(clamp(floor(\n        yb_libplacebo_reshape(sample_value.xyz,component)*65536.0),\n        0.0,65535.0));\n";
    if(!begin||!end||!main||!mapped||mapped>=end||main>=begin||strstr(begin+1,"    int64_t total=int64_t(0);\n")||
       strstr(end+1,"    int64_t residual=int64_t(0);\n")||strstr(main+1,"void main()\n")) {
        free(fragment);return 0;
    }
    size_t a=(size_t)(main-b->canonical),r=strlen(replacement),z=(size_t)(begin-main);
    size_t tail=strlen(end),length=a+n+1+z+r+tail;
    if(length>1048576U){free(fragment);return 0;}
    char *text=malloc(length+1);if(!text){free(fragment);return 0;}
    memcpy(text,b->canonical,a);memcpy(text+a,fragment,n);text[a+n]='\n';
    memcpy(text+a+n+1,main,z);memcpy(text+a+n+1+z,replacement,r);
    memcpy(text+a+n+1+z+r,end,tail+1);
    free(fragment);*out=text;*size=length;return 1;
}
int yb_gpu_fp32_create(const yb_gpu_backend_create_info *i,yb_gpu_fp32 **out)
{
    if(!i||!out||*out||!i->shader_source||!i->shader_bytes||i->shader_bytes>1048576U||
       memchr(i->shader_source,0,i->shader_bytes))return YB_GPU_BACKEND_ARGUMENT;
    yb_gpu_fp32 *b=calloc(1,sizeof(*b));if(!b)return YB_GPU_BACKEND_GL_FAILURE;
    b->canonical=malloc(i->shader_bytes+1);
    if(!b->canonical){free(b);return YB_GPU_BACKEND_GL_FAILURE;}
    memcpy(b->canonical,i->shader_source,i->shader_bytes);b->canonical[i->shader_bytes]=0;
    b->owner=*i;b->owner.shader_source=b->canonical;b->active=-1;
    int status=yb_gpu_backend_create(&b->owner,&b->integer);
    if(status) {
        if(b->integer){b->failed=1;*out=b;return status;}
        free(b->canonical);free(b);return status;
    }
    *out=b;return 0;
}
int yb_gpu_fp32_submit(yb_gpu_fp32 *b,const yb_gpu_backend_plan *p)
{
    if(!b||b->failed||b->closing)return YB_GPU_BACKEND_ARGUMENT;
    if(b->pending)return YB_GPU_BACKEND_BUSY;
    int status=yb_gpu_backend_validate_plan(p);if(status)return status;
    struct topology t=topology(p);int index=-1;
    for(int j=0;j<2;j++)if(b->entries[j].backend&&!memcmp(&t,&b->entries[j].key,sizeof(t)))index=j;
    if(index<0)increment(&b->stats.cache_misses);else increment(&b->stats.cache_hits);
    if(index<0) {
        char *source=NULL;size_t bytes=0;
        if(shader(b,p,&source,&bytes)) {
            index=(int)(b->next%2U);
            yb_gpu_backend_create_info info=b->owner;info.shader_source=source;info.shader_bytes=bytes;
            status=yb_fp_backend_create(&info,&b->staged);free(source);
            if(status) {
                increment(&b->stats.shader_compile_failed);
                if(b->staged){b->failed=1;return status;}
                index=-1;
            } else {
                if(b->entries[index].backend&&yb_fp_backend_destroy(&b->entries[index].backend)) {
                    b->failed=1;return YB_GPU_BACKEND_GL_FAILURE;
                }
                b->entries[index].backend=b->staged;b->staged=NULL;
                b->entries[index].key=t;b->next++;
            }
        } else increment(&b->stats.generate_failed);
    }
    status=index<0?yb_gpu_backend_submit(b->integer,p):yb_fp_backend_submit(b->entries[index].backend,p);
    /* GL failure may leave queued work; never switch backend or destroy it. */
    if(status!=YB_GPU_BACKEND_OK){if(status==YB_GPU_BACKEND_GL_FAILURE)b->failed=1;return status;}
    b->active=index;b->pending=1;
    increment(index<0?&b->stats.accepted_integer:&b->stats.accepted_fp32);return 0;
}
int yb_gpu_fp32_finish(yb_gpu_fp32 *b,uint64_t timeout,yb_gpu_backend_output *out)
{
    if(!b||b->failed||b->closing)return YB_GPU_BACKEND_ARGUMENT;
    int status=b->active<0?yb_gpu_backend_finish(b->integer,timeout,out):
        yb_fp_backend_finish(b->entries[b->active].backend,timeout,out);
    if(status!=YB_GPU_BACKEND_PENDING&&status!=YB_GPU_BACKEND_ARGUMENT)b->pending=0;
    if(status==YB_GPU_BACKEND_GL_FAILURE)b->failed=1;
    return status;
}
int yb_gpu_fp32_destroy(yb_gpu_fp32 **out)
{
    if(!out||!*out)return YB_GPU_BACKEND_ARGUMENT;
    yb_gpu_fp32 *b=*out;if(b->pending)return YB_GPU_BACKEND_BUSY;b->closing=1;
    if(b->staged&&yb_fp_backend_destroy(&b->staged))return YB_GPU_BACKEND_GL_FAILURE;
    for(int j=0;j<2;j++)if(b->entries[j].backend&&yb_fp_backend_destroy(&b->entries[j].backend))return YB_GPU_BACKEND_GL_FAILURE;
    if(b->integer&&yb_gpu_backend_destroy(&b->integer))return YB_GPU_BACKEND_GL_FAILURE;
    free(b->canonical);free(b);*out=NULL;return 0;
}
int yb_gpu_fp32_abandon_destroyed_context(yb_gpu_fp32 **out,uint32_t destroyed)
{
    if(!out||!*out||destroyed!=1)return YB_GPU_BACKEND_ARGUMENT;
    yb_gpu_fp32 *b=*out;
    if(b->staged&&yb_fp_backend_abandon_destroyed_context(&b->staged,1))return YB_GPU_BACKEND_ARGUMENT;
    for(int j=0;j<2;j++)if(b->entries[j].backend&&yb_fp_backend_abandon_destroyed_context(&b->entries[j].backend,1))return YB_GPU_BACKEND_ARGUMENT;
    if(b->integer&&yb_gpu_backend_abandon_destroyed_context(&b->integer,1))return YB_GPU_BACKEND_ARGUMENT;
    free(b->canonical);free(b);*out=NULL;return 0;
}
int yb_gpu_fp32_selected(const yb_gpu_fp32 *b){return b&&b->active>=0;}
int yb_gpu_fp32_get_stats(const yb_gpu_fp32 *b,yb_gpu_fp32_stats *out)
{
    if(!b||!out)return YB_GPU_BACKEND_ARGUMENT;
    *out=b->stats;return 0;
}
