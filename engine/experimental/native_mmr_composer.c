#include "native_mmr_composer.h"
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#if !defined(__SIZEOF_INT128__) || __SIZEOF_INT128__ < 16
#error "native_mmr_composer requires signed 128-bit fallback arithmetic"
#endif
typedef __int128 mmr_wide;
typedef unsigned __int128 mmr_unsigned;
/* Terms are nonnegative Q20 values bounded by 2^20. A segment uses signed
 * 64-bit accumulation only when the sum of absolute product bounds proves
 * every intermediate safe. Otherwise the exact wide arithmetic is retained. */
struct mmr_segment_plan {
    int64_t coefficients[21];
    uint8_t indices[21], count, order, narrow;
};
#define PLAN_MAGIC UINT32_C(0x59424d50)
#define FRAME_MAGIC UINT32_C(0x59424d46)
struct yb_mmr_plan {
    uint32_t magic;
    int32_t enabled,output_depth;
    struct yb_mapping_config mapping;
    struct yb_nlq_config nlq[3];
    uint8_t cached[3];
    struct mmr_segment_plan segments[3][YB_MAX_SEGMENTS];
    uint16_t mapped[3][1024];
    int32_t residual[3][1024];
};
struct yb_mmr_frame {
    uint32_t magic;
    yb_mmr_plan *plan;
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
static int plan_valid(const yb_mmr_plan *p,struct cache_span *s)
{ return span(p,sizeof(*p),_Alignof(yb_mmr_plan),s) && p->magic==PLAN_MAGIC; }

static uint64_t magnitude(int64_t v)
{ return v>=0 ? (uint64_t)v : (uint64_t)(-(v+1))+1U; }
static void prepare_segment(struct mmr_segment_plan *p,const struct yb_segment *s)
{
    mmr_unsigned bound=(mmr_unsigned)magnitude(s->constant)*((mmr_unsigned)1<<20);
    for(int32_t row=0;row<s->order;row++)for(unsigned t=0;t<7;t++) {
        int64_t coefficient=s->coefficients[row][t];
        if(coefficient) {
            unsigned n=p->count++;
            p->coefficients[n]=coefficient;
            p->indices[n]=(uint8_t)((unsigned)row*7U+t);
            p->order=(uint8_t)((unsigned)row+1U);
            bound+=(mmr_unsigned)magnitude(coefficient)*((mmr_unsigned)1<<20);
        }
    }
    p->narrow=(uint8_t)(bound<=(mmr_unsigned)INT64_MAX);
}
static mmr_wide wide_floor(mmr_wide v,unsigned shift)
{ return v>=0 ? v>>shift : -1-((-(v+1))>>shift); }
static int64_t narrow_floor(int64_t v,unsigned shift)
{ return v>=0 ? v>>shift : -1-((-(v+1))>>shift); }
static uint16_t map_mmr(const yb_mmr_plan *p,int32_t c,const uint16_t input[3])
{
    const struct yb_component_mapping *curve=&p->mapping.components[c];
    int32_t index=0;
    /* Segment selection uses original code, not the endpoint-clamped code. */
    while(index<curve->pivot_count-2 && input[c]>=curve->pivots[index+1])index++;
    const struct yb_segment *s=&curve->segments[index];
    uint64_t codes[3];
    for(unsigned i=0;i<3;i++) {
        const struct yb_component_mapping *v=&p->mapping.components[i];
        uint16_t low=(uint16_t)v->pivots[0],high=(uint16_t)v->pivots[v->pivot_count-1];
        codes[i]=input[i]<low ? low : input[i]>high ? high : input[i];
    }
    mmr_wide total;
    if(s->method==YB_POLYNOMIAL) {
        /* Mixed polynomial/MMR components retain the exact polynomial equation. */
        total=0;mmr_wide power=1;
        for(int32_t degree=0;degree<=s->order;degree++) {
            total+=(mmr_wide)s->coefficients[0][degree]*power*
                   ((mmr_wide)1<<(20-p->mapping.bit_depth*degree));
            power*=codes[c];
        }
    } else {
        const struct mmr_segment_plan *plan=&p->segments[c][index];
        uint64_t terms[21]={0};
        unsigned depth=(unsigned)p->mapping.bit_depth;
        if(plan->order) {
            for(unsigned i=0;i<3;i++)terms[i]=codes[i]<<(20-depth);
            terms[3]=(codes[0]*codes[1])<<(20-2*depth);
            terms[4]=(codes[0]*codes[2])<<(20-2*depth);
            terms[5]=(codes[1]*codes[2])<<(20-2*depth);
            terms[6]=(terms[3]*terms[2])>>20;
            if(plan->order>1)for(unsigned i=0;i<7;i++)
                terms[7+i]=(terms[i]*terms[i])>>20;
            if(plan->order>2)for(unsigned i=0;i<7;i++)
                terms[14+i]=(terms[i]*terms[7+i])>>20;
        }
        if(plan->narrow) {
            int64_t sum=s->constant*(INT64_C(1)<<20);
            for(unsigned i=0;i<plan->count;i++)
                sum+=plan->coefficients[i]*(int64_t)terms[plan->indices[i]];
            /* Bound proves all products and partial sums are representable. */
            int64_t value=narrow_floor(sum,(unsigned)p->mapping.denominator+4);
            return (uint16_t)(value<0 ? 0 : value>65535 ? 65535 : value);
        }
        total=(mmr_wide)s->constant*((mmr_wide)1<<20);
        for(unsigned i=0;i<plan->count;i++)
            total+=(mmr_wide)plan->coefficients[i]*terms[plan->indices[i]];
    }
    mmr_wide value=wide_floor(total,(unsigned)p->mapping.denominator+4);
    return (uint16_t)(value<0 ? 0 : value>65535 ? 65535 : value);
}

uint32_t yb_mmr_abi_version(void) { return 1; }
uint64_t yb_mmr_sizeof_plan(void) { return sizeof(yb_mmr_plan); }
uint64_t yb_mmr_sizeof_frame(void) { return sizeof(yb_mmr_frame); }
int yb_mmr_create(const struct yb_mapping_config *map,
    const struct yb_nlq_config *nlq,int32_t enabled,int32_t depth,yb_mmr_plan **out)
{
    struct cache_span m,n,o;
    if ((enabled!=0 && enabled!=1) || (!enabled && nlq) ||
        !span(map,sizeof(*map),_Alignof(struct yb_mapping_config),&m) ||
        !span(out,sizeof(*out),_Alignof(yb_mmr_plan *),&o) || overlap(m,o) ||
        (enabled && (!span(nlq,sizeof(*nlq)*3,_Alignof(struct yb_nlq_config),&n) ||
                     overlap(n,o)))) return YB_INVALID_ARGUMENT;
    if (depth!=10 && depth!=12) return YB_INVALID_SAMPLE;
    yb_mmr_plan *p=calloc(1,sizeof(*p));
    if (!p) return YB_MMR_NO_MEMORY;
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
        for(int32_t i=0;i<p->mapping.components[c].pivot_count-1;i++)
            if(p->mapping.components[c].segments[i].method==YB_MMR)
                prepare_segment(&p->segments[c][i],&p->mapping.components[c].segments[i]);
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
void yb_mmr_destroy(yb_mmr_plan *p) { free(p); }
int yb_mmr_component_route(const yb_mmr_plan *p,int32_t c)
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
int yb_mmr_process_chunk(const yb_mmr_plan *p,int32_t c,
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
    uint16_t bmax=(uint16_t)((1<<p->mapping.bit_depth)-1);
    uint16_t emax=(uint16_t)(p->enabled ? (1<<p->nlq[c].bit_depth)-1 : 0);
    for(uint32_t i=0;i<count;i++)
        if (y[i]>bmax || cb[i]>bmax || cr[i]>bmax || (p->enabled && el[i]>emax))
            return YB_INVALID_SAMPLE;
    const uint16_t *selected=c==0 ? y : c==1 ? cb : cr;
    for(uint32_t i=0;i<count;i++) {
        uint16_t input[3]={y[i],cb[i],cr[i]};
        uint16_t base=p->cached[c] ? p->mapped[c][selected[i]] : map_mmr(p,c,input);
        int32_t correction=p->enabled ? p->residual[c][el[i]] : 0;
        mapped[i]=base;residual[i]=correction;
        sum[i]=(int32_t)base+correction;
        result[i]=compose(base,correction,p->output_depth);
    }
    return YB_OK;
}
int yb_mmr_frame_create(const yb_integration_descriptor *d,
    const struct yb_mapping_config *m,const struct yb_nlq_config *n,yb_mmr_frame **out)
{
    struct cache_span ds,ms,ns,os;
    if (!span(d,sizeof(*d),_Alignof(yb_integration_descriptor),&ds) ||
        !span(m,sizeof(*m),_Alignof(struct yb_mapping_config),&ms) ||
        !span(out,sizeof(*out),_Alignof(yb_mmr_frame *),&os) ||
        overlap(ds,os) || overlap(ms,os) ||
        (n && (!span(n,sizeof(*n)*3,_Alignof(struct yb_nlq_config),&ns) || overlap(ns,os))))
        return YB_INTEGRATION_INVALID;
    if (d->input_kind!=YB_INPUT_WHOLE_CODES) return YB_INTEGRATION_ROUTE;
    yb_mmr_frame *f=calloc(1,sizeof(*f));
    if (!f) return YB_INTEGRATION_STAGE;
    int status=yb_integration_init(&f->context,d,m,n,NULL);
    if (status!=YB_INTEGRATION_OK) { free(f);return status; }
    status=yb_mmr_create(&f->context.mapping,
        f->context.descriptor.enhancement_enabled ? f->context.nlq : NULL,
        f->context.descriptor.enhancement_enabled,f->context.descriptor.output_depth,&f->plan);
    if (status!=YB_OK) { free(f);return YB_INTEGRATION_STAGE; }
    f->magic=FRAME_MAGIC;*out=f;return YB_INTEGRATION_OK;
}
void yb_mmr_frame_destroy(yb_mmr_frame *f)
{ if (f) { yb_mmr_destroy(f->plan);free(f); } }
static int frame_ready(const yb_mmr_frame *f,struct cache_span *s)
{
    if (!span(f,sizeof(*f),_Alignof(yb_mmr_frame),s) || f->magic!=FRAME_MAGIC)
        return YB_INTEGRATION_INVALID;
    return f->context.finalized ? YB_INTEGRATION_FINALIZED : YB_INTEGRATION_OK;
}
int yb_mmr_frame_component_route(const yb_mmr_frame *f,int32_t c)
{
    struct cache_span s;
    return frame_ready(f,&s)!=YB_INTEGRATION_OK ? -1 : yb_mmr_component_route(f->plan,c);
}
int yb_mmr_frame_process(yb_mmr_frame *f,const uint8_t id[32],int32_t c,
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
    status=yb_mmr_process_chunk(f->plan,c,y,cb,cr,el,count,mapped,residual,sum,result);
    if (status!=YB_OK) return YB_INTEGRATION_STAGE;
    f->context.consumed[c]+=count;return YB_INTEGRATION_OK;
}
int yb_mmr_frame_finish(yb_mmr_frame *f,yb_integration_completion *out)
{
    struct cache_span fs,ps,os;
    int status=frame_ready(f,&fs);
    if (status!=YB_INTEGRATION_OK) return status;
    if (!span(out,sizeof(*out),_Alignof(yb_integration_completion),&os) ||
        !plan_valid(f->plan,&ps)) return YB_INTEGRATION_INVALID;
    if (overlap(os,fs)||overlap(os,ps)) return YB_INTEGRATION_ALIAS;
    return yb_integration_finish(&f->context,out);
}

int yb_mmr_segment_bits(const yb_mmr_plan *p,int32_t c,int32_t i)
{
    struct cache_span s;
    if(!plan_valid(p,&s)||c<0||c>2||i<0||
       i>=p->mapping.components[c].pivot_count-1)return -1;
    if(p->mapping.components[c].segments[i].method!=YB_MMR)return 0;
    return p->segments[c][i].narrow ? 64 : 128;
}
int yb_mmr_frame_segment_bits(const yb_mmr_frame *f,int32_t c,int32_t i)
{
    struct cache_span s;
    if(frame_ready(f,&s)!=YB_INTEGRATION_OK)return -1;
    return yb_mmr_segment_bits(f->plan,c,i);
}

