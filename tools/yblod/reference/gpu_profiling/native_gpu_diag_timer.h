#ifndef YB_NATIVE_GPU_DIAGNOSTIC_TIMER_H
#define YB_NATIVE_GPU_DIAGNOSTIC_TIMER_H
/* Private standalone diagnostic only. End the query before the existing
 * producer fence. Read only after existing finish, never add a pipeline wait.
 * GL_TIME_ELAPSED is device elapsed command-interval time, not exclusive
 * shader occupancy, kernel cycles, or end-to-end playback time. */
#include "native_gpu_composer_backend.h"
#include <GL/glcorearb.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <inttypes.h>
enum { YB_DIAG_TIMER_COMPOSER=1, YB_DIAG_TIMER_YCC=2, YB_DIAG_TIMER_RECORDS=65 };
int yb_gpu_diag_timer_record(unsigned stage,uint64_t elapsed_ns);
typedef struct {
    PFNGLGENQUERIESPROC GenQueries;
    PFNGLDELETEQUERIESPROC DeleteQueries;
    PFNGLGETQUERYIVPROC GetQueryiv;
    PFNGLBEGINQUERYPROC BeginQuery;
    PFNGLENDQUERYPROC EndQuery;
    PFNGLGETQUERYOBJECTIVPROC GetQueryObjectiv;
    PFNGLGETQUERYOBJECTUI64VPROC GetQueryObjectui64v;
    PFNGLGETERRORPROC GetError;
    GLuint name;
    int configured,enabled,active,pending;
    unsigned stage;
    unsigned collected;
} yb_diag_timer;
static inline int yb_diag_timer_reject(const yb_diag_timer *t,const char *reason,GLenum error,GLint available,GLuint64 value)
{
 fprintf(stderr,"gpu timer rejected: stage=%u collected=%u reason=%s gl_error=%u available=%d elapsed_ns=%" PRIu64 "\n",
         t?t->stage:0U,t?t->collected:0U,reason,(unsigned)error,(int)available,(uint64_t)value);
 return 0;
}

static inline int yb_diag_timer_begin(yb_diag_timer *t,yb_gpu_get_proc proc,void *opaque,unsigned stage)
{
    if(!t||!proc||stage<YB_DIAG_TIMER_COMPOSER||stage>YB_DIAG_TIMER_YCC)return 0;
    if(!t->configured){
        const char *requested=getenv("YB_GPU_DIAG_TIMER");
        if(requested&&strcmp(requested,"0")&&strcmp(requested,"1"))return 0;
        t->configured=1;t->enabled=requested&&!strcmp(requested,"1");t->stage=stage;
    }
    if(!t->enabled)return 1;
    if(t->stage!=stage||t->active||t->pending)return 0;
    if(!t->name){
#define YB_TIMER_LOAD(field,type) t->field=(type)proc("gl" #field,opaque);if(!t->field)return 0
        YB_TIMER_LOAD(GenQueries,PFNGLGENQUERIESPROC);
        YB_TIMER_LOAD(DeleteQueries,PFNGLDELETEQUERIESPROC);
        YB_TIMER_LOAD(GetQueryiv,PFNGLGETQUERYIVPROC);
        YB_TIMER_LOAD(BeginQuery,PFNGLBEGINQUERYPROC);
        YB_TIMER_LOAD(EndQuery,PFNGLENDQUERYPROC);
        YB_TIMER_LOAD(GetQueryObjectiv,PFNGLGETQUERYOBJECTIVPROC);
        YB_TIMER_LOAD(GetQueryObjectui64v,PFNGLGETQUERYOBJECTUI64VPROC);
        YB_TIMER_LOAD(GetError,PFNGLGETERRORPROC);
#undef YB_TIMER_LOAD
        GLint bits=0,current=0;
        if(t->GetError()!=GL_NO_ERROR)return 0;
        t->GetQueryiv(GL_TIME_ELAPSED,GL_QUERY_COUNTER_BITS,&bits);
        t->GetQueryiv(GL_TIME_ELAPSED,GL_CURRENT_QUERY,&current);
        /* A 33-bit nanosecond counter covers the existing five-second
         * completion bound without relying on wrapping/undefined overflow. */
        if(bits<33||bits>64||current||t->GetError()!=GL_NO_ERROR)return 0;
        t->GenQueries(1,&t->name);
        if(!t->name||t->GetError()!=GL_NO_ERROR)return 0;
    }
    GLint current=0;
    t->GetQueryiv(GL_TIME_ELAPSED,GL_CURRENT_QUERY,&current);
    if(current||t->GetError()!=GL_NO_ERROR)return 0;
    t->BeginQuery(GL_TIME_ELAPSED,t->name);
    if(t->GetError()!=GL_NO_ERROR)return 0;
    t->active=1;return 1;
}

static inline int yb_diag_timer_end(yb_diag_timer *t)
{
    if(!t)return 0;
    if(!t->enabled)return 1;
    if(!t->active||t->pending)return 0;
    t->EndQuery(GL_TIME_ELAPSED);
    if(t->GetError()!=GL_NO_ERROR)return 0;
    t->active=0;t->pending=1;return 1;
}

static inline int yb_diag_timer_collect(yb_diag_timer *t)
{
    if(!t)return 0;
    if(!t->enabled)return 1;
    if(t->active||!t->pending)return yb_diag_timer_reject(t,"invalid-collect-state",GL_NO_ERROR,0,0);
    GLint available=0;
    t->GetQueryObjectiv(t->name,GL_QUERY_RESULT_AVAILABLE,&available);
    /* The caller's existing fence was queued after EndQuery. Refuse a
     * not-ready result; do not introduce another wait or blocking poll. */
    GLenum query_error=t->GetError();
    if(query_error!=GL_NO_ERROR)return yb_diag_timer_reject(t,"availability-gl-error",query_error,available,0);
    if(!available)return yb_diag_timer_reject(t,"result-not-yet-available",GL_NO_ERROR,available,0);
    GLuint64 value=0;
    t->GetQueryObjectui64v(t->name,GL_QUERY_RESULT,&value);
    query_error=t->GetError();
    if(query_error!=GL_NO_ERROR)return yb_diag_timer_reject(t,"result-gl-error",query_error,available,value);
    if(!value)return yb_diag_timer_reject(t,"zero-result",GL_NO_ERROR,available,value);
    if(value>UINT64_C(5000000000))return yb_diag_timer_reject(t,"result-over-five-second-bound",GL_NO_ERROR,available,value);
    if(!yb_gpu_diag_timer_record(t->stage,(uint64_t)value))return yb_diag_timer_reject(t,"collector-rejected",GL_NO_ERROR,available,value);
    t->pending=0;t->collected++;return 1;
}

static inline int yb_diag_timer_destroy(yb_diag_timer *t)
{
    if(!t)return 0;
    if(!t->name)return 1;
    if(t->active){
        t->EndQuery(GL_TIME_ELAPSED);
        if(t->GetError()!=GL_NO_ERROR)return 0;
        t->active=0;
    }
    t->DeleteQueries(1,&t->name);
    if(t->GetError()!=GL_NO_ERROR)return 0;
    t->name=0;t->pending=0;return 1;
}
#endif
