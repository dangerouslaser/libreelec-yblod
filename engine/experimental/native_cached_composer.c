#include "native_cached_composer.h"
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#define PLAN_MAGIC UINT32_C(0x59424350)
#define FRAME_MAGIC UINT32_C(0x59424346)
struct yb_cached_plan {
    uint32_t magic;
    int32_t enabled,output_depth;
    struct yb_mapping_config mapping;
    struct yb_nlq_config nlq[3];
    uint8_t cached[3];
    uint16_t mapped[3][1024];
    int32_t residual[3][1024];
};
struct yb_cached_frame {
    uint32_t magic;
    yb_cached_plan *plan;
    yb_integration_context context;
};
struct cache_span { uintptr_t low,high; };
static int span(const void *p,uint64_t bytes,uintptr_t alignment,struct cache_span *s)
{
    uintptr_t v=(uintptr_t)p;
    if (!p || v%alignment || !bytes || bytes>UINTPTR_MAX ||
        v>UINTPTR_MAX-(uintptr_t)bytes) return 0;
    s->low=v;s->high=v+(uintptr_t)bytes;return 1;
}
static int overlap(struct cache_span a,struct cache_span b)
{ return a.low<b.high && b.low<a.high; }
static int plan_valid(const yb_cached_plan *p,struct cache_span *s)
{ return span(p,sizeof(*p),_Alignof(yb_cached_plan),s) && p->magic==PLAN_MAGIC; }
uint32_t yb_cached_abi_version(void) { return 1; }
uint64_t yb_cached_sizeof_plan(void) { return sizeof(yb_cached_plan); }
uint64_t yb_cached_sizeof_frame(void) { return sizeof(yb_cached_frame); }
int yb_cached_create(const struct yb_mapping_config *map,
    const struct yb_nlq_config *nlq,int32_t enabled,int32_t depth,yb_cached_plan **out)
{
    struct cache_span m,n,o;
    if ((enabled!=0 && enabled!=1) || (!enabled && nlq) ||
        !span(map,sizeof(*map),_Alignof(struct yb_mapping_config),&m) ||
        !span(out,sizeof(*out),_Alignof(yb_cached_plan *),&o) || overlap(m,o) ||
        (enabled && (!span(nlq,sizeof(*nlq)*3,_Alignof(struct yb_nlq_config),&n) ||
                     overlap(n,o)))) return YB_INVALID_ARGUMENT;
    if (depth!=10 && depth!=12) return YB_INVALID_SAMPLE;
    yb_cached_plan *p=calloc(1,sizeof(*p));
    if (!p) return YB_CACHE_NO_MEMORY;
    p->mapping=*map;p->enabled=enabled;p->output_depth=depth;
    if (enabled) memcpy(p->nlq,nlq,sizeof(p->nlq));
    int status=yb_validate_mapping(&p->mapping);
    if (status!=YB_OK) { free(p);return status; }
    for(int32_t c=0;c<3;c++) {
        if (enabled) {
            status=yb_validate_nlq(&p->nlq[c]);
            if (status!=YB_OK || p->mapping.denominator!=p->nlq[c].denominator) {
                free(p);return status==YB_OK ? YB_INVALID_CONFIG : status;
            }
        }
        p->cached[c]=1;
        for(int32_t i=0;i<p->mapping.components[c].pivot_count-1;i++)
            if (p->mapping.components[c].segments[i].method!=YB_POLYNOMIAL)
                p->cached[c]=0;
        if (p->cached[c]) {
            int64_t samples[3]={0,0,0};
            for(int32_t code=0;code<(1<<p->mapping.bit_depth);code++) {
                samples[c]=code;
                status=yb_map_sample(&p->mapping,c,samples,&p->mapped[c][code]);
                if (status!=YB_OK) { free(p);return status; }
            }
        }
        if (enabled) {
            for(int32_t code=0;code<(1<<p->nlq[c].bit_depth);code++) {
                int64_t correction;
                status=yb_nlq(&p->nlq[c],code,&correction);
                if (status!=YB_OK || correction<INT32_MIN || correction>INT32_MAX) {
                    free(p);return status==YB_OK ? YB_INVALID_CONFIG : status;
                }
                p->residual[c][code]=(int32_t)correction;
            }
        }
    }
    p->magic=PLAN_MAGIC;*out=p;return YB_OK;
}
void yb_cached_destroy(yb_cached_plan *p) { free(p); }
int yb_cached_component_route(const yb_cached_plan *p,int32_t c)
{
    struct cache_span s;
    return !plan_valid(p,&s) || c<0 || c>2 ? -1 : p->cached[c];
}
static uint16_t compose(uint16_t base,int32_t residual,int32_t depth)
{
    unsigned shift=(unsigned)(16-depth);
    int64_t total=(int64_t)base+residual+(INT64_C(1)<<(shift-1));
    int64_t result=total>=0 ? total>>shift : -1-((-(total+1))>>shift);
    int64_t max=(INT64_C(1)<<depth)-1;
    return (uint16_t)(result<0 ? 0 : result>max ? max : result);
}
int yb_cached_process_chunk(const yb_cached_plan *p,int32_t c,
    const uint16_t *y,const uint16_t *cb,const uint16_t *cr,const uint16_t *el,
    uint32_t count,uint16_t *mapped,int32_t *residual,int32_t *sum,uint16_t *result)
{
    struct cache_span ps,inputs[4],outputs[4];
    if (!plan_valid(p,&ps) || !count || count>65536 || (!p->enabled && el))
        return YB_INVALID_ARGUMENT;
    if (c<0 || c>2) return YB_INVALID_SAMPLE;
    if (!span(y,(uint64_t)count*2,_Alignof(uint16_t),&inputs[0]) ||
        !span(cb,(uint64_t)count*2,_Alignof(uint16_t),&inputs[1]) ||
        !span(cr,(uint64_t)count*2,_Alignof(uint16_t),&inputs[2]) ||
        (p->enabled && !span(el,(uint64_t)count*2,_Alignof(uint16_t),&inputs[3])) ||
        !span(mapped,(uint64_t)count*2,_Alignof(uint16_t),&outputs[0]) ||
        !span(residual,(uint64_t)count*4,_Alignof(int32_t),&outputs[1]) ||
        !span(sum,(uint64_t)count*4,_Alignof(int32_t),&outputs[2]) ||
        !span(result,(uint64_t)count*2,_Alignof(uint16_t),&outputs[3])) return YB_INVALID_ARGUMENT;
    unsigned nin=p->enabled ? 4U : 3U;
    for(unsigned i=0;i<nin;i++) if (overlap(inputs[i],ps)) return YB_INVALID_ARGUMENT;
    for(unsigned i=0;i<4;i++) {
        if (overlap(outputs[i],ps)) return YB_INVALID_ARGUMENT;
        for(unsigned j=0;j<i;j++) if (overlap(outputs[i],outputs[j])) return YB_INVALID_ARGUMENT;
        for(unsigned j=0;j<nin;j++) if (overlap(outputs[i],inputs[j])) return YB_INVALID_ARGUMENT;
    }
    /* MMR fallback is an unchanged BATCH call, not scalar map revalidation. */
    if (!p->cached[c])
        return yb_process_chunk(&p->mapping,p->enabled ? &p->nlq[c] : NULL,c,
            y,cb,cr,el,count,p->enabled,p->output_depth,mapped,residual,sum,result);
    uint16_t bmax=(uint16_t)((1<<p->mapping.bit_depth)-1);
    uint16_t emax=(uint16_t)(p->enabled ? (1<<p->nlq[c].bit_depth)-1 : 0);
    for(uint32_t i=0;i<count;i++)
        if (y[i]>bmax || cb[i]>bmax || cr[i]>bmax || (p->enabled && el[i]>emax))
            return YB_INVALID_SAMPLE;
    const uint16_t *selected=c==0 ? y : c==1 ? cb : cr;
    for(uint32_t i=0;i<count;i++) {
        uint16_t base=p->mapped[c][selected[i]];
        int32_t correction=p->enabled ? p->residual[c][el[i]] : 0;
        mapped[i]=base;residual[i]=correction;
        sum[i]=(int32_t)base+correction;
        result[i]=compose(base,correction,p->output_depth);
    }
    return YB_OK;
}
int yb_cached_frame_create(const yb_integration_descriptor *d,
    const struct yb_mapping_config *m,const struct yb_nlq_config *n,yb_cached_frame **out)
{
    struct cache_span ds,ms,ns,os;
    if (!span(d,sizeof(*d),_Alignof(yb_integration_descriptor),&ds) ||
        !span(m,sizeof(*m),_Alignof(struct yb_mapping_config),&ms) ||
        !span(out,sizeof(*out),_Alignof(yb_cached_frame *),&os) ||
        overlap(ds,os) || overlap(ms,os) ||
        (n && (!span(n,sizeof(*n)*3,_Alignof(struct yb_nlq_config),&ns) || overlap(ns,os))))
        return YB_INTEGRATION_INVALID;
    if (d->input_kind!=YB_INPUT_WHOLE_CODES) return YB_INTEGRATION_ROUTE;
    yb_cached_frame *f=calloc(1,sizeof(*f));
    if (!f) return YB_INTEGRATION_STAGE;
    int status=yb_integration_init(&f->context,d,m,n,NULL);
    if (status!=YB_INTEGRATION_OK) { free(f);return status; }
    status=yb_cached_create(&f->context.mapping,
        f->context.descriptor.enhancement_enabled ? f->context.nlq : NULL,
        f->context.descriptor.enhancement_enabled,f->context.descriptor.output_depth,&f->plan);
    if (status!=YB_OK) { free(f);return YB_INTEGRATION_STAGE; }
    f->magic=FRAME_MAGIC;*out=f;return YB_INTEGRATION_OK;
}
void yb_cached_frame_destroy(yb_cached_frame *f)
{ if (f) { yb_cached_destroy(f->plan);free(f); } }
static int frame_ready(const yb_cached_frame *f,struct cache_span *s)
{
    if (!span(f,sizeof(*f),_Alignof(yb_cached_frame),s) || f->magic!=FRAME_MAGIC)
        return YB_INTEGRATION_INVALID;
    return f->context.finalized ? YB_INTEGRATION_FINALIZED : YB_INTEGRATION_OK;
}
int yb_cached_frame_component_route(const yb_cached_frame *f,int32_t c)
{
    struct cache_span s;
    return frame_ready(f,&s)!=YB_INTEGRATION_OK ? -1 : yb_cached_component_route(f->plan,c);
}
int yb_cached_frame_process(yb_cached_frame *f,const uint8_t id[32],int32_t c,
    uint64_t start,const uint16_t *y,const uint16_t *cb,const uint16_t *cr,const uint16_t *el,
    uint32_t count,uint16_t *mapped,int32_t *residual,int32_t *sum,uint16_t *result)
{
    struct cache_span fs,ids,inputs[4],outputs[4];
    int status=frame_ready(f,&fs);
    if (status!=YB_INTEGRATION_OK) return status;
    if (!span(id,32,1,&ids)) return YB_INTEGRATION_ASSOCIATION;
    if (memcmp(id,f->context.descriptor.frame_id,32)) return YB_INTEGRATION_ASSOCIATION;
    if (c<0 || c>2 || !count || count>65536) return YB_INTEGRATION_INVALID;
    uint64_t total=(uint64_t)f->context.descriptor.width*f->context.descriptor.height/(c ? 4U : 1U);
    if (start!=f->context.consumed[c] || start>total || count>total-start)
        return YB_INTEGRATION_COUNTS;
    if (!span(y,(uint64_t)count*2,_Alignof(uint16_t),&inputs[0]) ||
        !span(cb,(uint64_t)count*2,_Alignof(uint16_t),&inputs[1]) ||
        !span(cr,(uint64_t)count*2,_Alignof(uint16_t),&inputs[2]) ||
        (el && !span(el,(uint64_t)count*2,_Alignof(uint16_t),&inputs[3])) ||
        !span(mapped,(uint64_t)count*2,_Alignof(uint16_t),&outputs[0]) ||
        !span(residual,(uint64_t)count*4,_Alignof(int32_t),&outputs[1]) ||
        !span(sum,(uint64_t)count*4,_Alignof(int32_t),&outputs[2]) ||
        !span(result,(uint64_t)count*2,_Alignof(uint16_t),&outputs[3])) return YB_INTEGRATION_STAGE;
    for(unsigned i=0;i<(el ? 4U : 3U);i++)
        if (overlap(inputs[i],fs)) return YB_INTEGRATION_ALIAS;
    for(unsigned i=0;i<4;i++)
        if (overlap(outputs[i],fs)||overlap(outputs[i],ids)) return YB_INTEGRATION_ALIAS;
    status=yb_cached_process_chunk(f->plan,c,y,cb,cr,el,count,mapped,residual,sum,result);
    if (status!=YB_OK) return YB_INTEGRATION_STAGE;
    f->context.consumed[c]+=count;return YB_INTEGRATION_OK;
}
int yb_cached_frame_finish(yb_cached_frame *f,yb_integration_completion *out)
{
    struct cache_span fs,ps,os;
    int status=frame_ready(f,&fs);
    if (status!=YB_INTEGRATION_OK) return status;
    if (!span(out,sizeof(*out),_Alignof(yb_integration_completion),&os) ||
        !plan_valid(f->plan,&ps)) return YB_INTEGRATION_INVALID;
    if (overlap(os,fs)||overlap(os,ps)) return YB_INTEGRATION_ALIAS;
    return yb_integration_finish(&f->context,out);
}
