#define _POSIX_C_SOURCE 200809L
#include "native_gpu_diag_timer.h"
#include <assert.h>
#include <stdio.h>
static unsigned calls,generated,deleted,results,recorded;
static GLint counter_bits=64,current_query,ready=1;
static GLuint64 elapsed=123456;
static void APIENTRY gen(GLsizei n,GLuint *ids){assert(n==1);calls++;generated++;*ids=17;}
static void APIENTRY del(GLsizei n,const GLuint *ids){assert(n==1&&*ids==17);calls++;deleted++;}
static void APIENTRY query(GLenum target,GLenum name,GLint *out){assert(target==GL_TIME_ELAPSED);calls++;*out=name==GL_QUERY_COUNTER_BITS?counter_bits:current_query;}
static void APIENTRY begin(GLenum target,GLuint id){assert(target==GL_TIME_ELAPSED&&id==17);calls++;current_query=17;}
static void APIENTRY end(GLenum target){assert(target==GL_TIME_ELAPSED);calls++;current_query=0;}
static void APIENTRY available(GLuint id,GLenum name,GLint *out){assert(id==17&&name==GL_QUERY_RESULT_AVAILABLE);calls++;*out=ready;}
static void APIENTRY result(GLuint id,GLenum name,GLuint64 *out){assert(id==17&&name==GL_QUERY_RESULT);calls++;results++;*out=elapsed;}
static GLenum APIENTRY error(void){return GL_NO_ERROR;}
int yb_gpu_diag_timer_record(unsigned stage,uint64_t value){assert(stage==1&&value==elapsed);recorded++;return 1;}
static yb_gpu_proc resolve(const char *name,void *opaque)
{
 (void)opaque;
#define MAP(n,f) if(!strcmp(name,"gl" n))return (yb_gpu_proc)f
 MAP("GenQueries",gen);MAP("DeleteQueries",del);MAP("GetQueryiv",query);
 MAP("BeginQuery",begin);MAP("EndQuery",end);MAP("GetQueryObjectiv",available);
 MAP("GetQueryObjectui64v",result);MAP("GetError",error);
#undef MAP
 return NULL;
}
int main(void)
{
 yb_diag_timer off={0};assert(!unsetenv("YB_GPU_DIAG_TIMER"));
 assert(yb_diag_timer_begin(&off,resolve,NULL,1)&&yb_diag_timer_end(&off)&&yb_diag_timer_collect(&off)&&yb_diag_timer_destroy(&off));assert(!calls);
 assert(!setenv("YB_GPU_DIAG_TIMER","garbage",1));yb_diag_timer bad={0};assert(!yb_diag_timer_begin(&bad,resolve,NULL,1));assert(!calls);
 assert(!setenv("YB_GPU_DIAG_TIMER","1",1));yb_diag_timer timer={0};
 counter_bits=32;assert(!yb_diag_timer_begin(&timer,resolve,NULL,1));assert(!generated);
 counter_bits=64;current_query=21;assert(!yb_diag_timer_begin(&timer,resolve,NULL,1));assert(!generated);
 current_query=0;assert(yb_diag_timer_begin(&timer,resolve,NULL,1));assert(generated==1);
 assert(!yb_diag_timer_begin(&timer,resolve,NULL,1));assert(yb_diag_timer_end(&timer));
 assert(!yb_diag_timer_begin(&timer,resolve,NULL,1));ready=0;assert(!yb_diag_timer_collect(&timer));assert(!results);
 ready=1;assert(yb_diag_timer_collect(&timer));assert(recorded==1&&results==1);
 assert(yb_diag_timer_begin(&timer,resolve,NULL,1)&&yb_diag_timer_end(&timer));elapsed=0;assert(!yb_diag_timer_collect(&timer));assert(recorded==1);
 elapsed=UINT64_C(5000000001);assert(!yb_diag_timer_collect(&timer));assert(recorded==1);
 assert(yb_diag_timer_destroy(&timer));assert(deleted==1&&generated==1&&!timer.name);
 puts("timer lifecycle mock: disabled, malformed, counter-width, nested, unavailable, reuse, bounds and cleanup PASS");return 0;
}
