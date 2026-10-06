#include "native_gpu_diag_timer.h"
#include <inttypes.h>
#include <stdio.h>
static uint64_t records[2][YB_DIAG_TIMER_RECORDS];
static unsigned counts[2];
static int overflow;
int yb_gpu_diag_timer_record(unsigned stage,uint64_t elapsed_ns)
{
    if(stage<1||stage>2||!elapsed_ns||elapsed_ns>UINT64_C(5000000000))return 0;
    unsigned index=stage-1;
    if(counts[index]>=YB_DIAG_TIMER_RECORDS){overflow=1;return 0;}
    records[index][counts[index]++]=elapsed_ns;return 1;
}
int yb_gpu_diag_timer_validate(unsigned stage,unsigned warmups,unsigned samples)
{
    const char *requested=getenv("YB_GPU_DIAG_TIMER");
    int enabled=requested&&!strcmp(requested,"1");
    if(!enabled)return 1;
    if(stage<1||stage>2||warmups>32||samples>32||!samples||overflow||
       counts[stage-1]!=1U+warmups+samples)return 0;
    return 1;
}
/* Standalone diagnostics only; append fields to the caller's JSON object. */
int yb_gpu_diag_timer_report(unsigned stage,unsigned warmups,unsigned samples)
{
    const char *requested=getenv("YB_GPU_DIAG_TIMER");
    int enabled=requested&&!strcmp(requested,"1");
    printf(",\"gpu_timer_query_requested\":%s",enabled?"true":"false");
    if(!yb_gpu_diag_timer_validate(stage,warmups,samples))return 0;
    if(!enabled)return 1;
    printf(",\"gpu_timer_query_method\":\"GL_TIME_ELAPSED\",\"gpu_timer_scope\":\"dispatch command interval through memory barrier, before existing producer fence; excludes existing completion wait, error/image readback and input texture upload; not exclusive kernel cycles\",\"gpu_timer_query_objects_per_backend_max\":1,\"gpu_timer_extra_fences\":0,\"gpu_timer_extra_waits\":0,\"gpu_elapsed_ns\":[");
    for(unsigned i=0;i<samples;i++)printf("%s%" PRIu64,i?",":"",records[stage-1][1U+warmups+i]);
    printf("]");return 1;
}
