#include "native_playback_context.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static unsigned context_calls;
static uintptr_t no_context(void *unused){(void)unused;context_calls++;return 0;}
static yb_gpu_proc no_proc(const char *name,void *unused){(void)name;(void)unused;return NULL;}
int main(void)
{
    yb_gpu_fp32_options fp={1,0,{0,0}};
    yb_native_playback_options native={1,0,{0,0}};
    assert(yb_gpu_fp32_options_validate(&fp)==YB_GPU_BACKEND_OK);
    fp.flags=YB_GPU_FP32_NLQ_LUT;
    assert(yb_gpu_fp32_options_validate(&fp)==YB_GPU_BACKEND_OK);
    yb_gpu_backend_create_info info={1,no_proc,no_context,NULL,"void main()\n{}",14};
    yb_gpu_fp32 *composer=NULL;
    for(unsigned issue=0;issue<4;issue++){
        yb_gpu_fp32_options invalid=fp;
        if(issue==0)invalid.version=0;
        if(issue==1)invalid.flags=2;
        if(issue==2)invalid.reserved[0]=1;
        if(issue==3)invalid.reserved[1]=1;
        unsigned before=context_calls;
        assert(yb_gpu_fp32_create_ex(&info,&invalid,&composer)==YB_GPU_BACKEND_ARGUMENT&&!composer&&context_calls==before);
    }
    assert(yb_gpu_fp32_create_ex(&info,NULL,&composer)==YB_GPU_BACKEND_ARGUMENT&&!composer&&!context_calls);
    assert(yb_gpu_fp32_create_ex(&info,&fp,&composer)==YB_GPU_BACKEND_ARGUMENT&&!composer&&context_calls==1);
    assert(yb_gpu_fp32_create(&info,&composer)==YB_GPU_BACKEND_ARGUMENT&&!composer&&context_calls==2);
    for(uint32_t flags=0;flags<8;flags++){
        native.flags=flags;
        int valid=flags==0||flags==YB_NATIVE_PLAYBACK_FP32||flags==(YB_NATIVE_PLAYBACK_FP32|YB_NATIVE_PLAYBACK_NLQ_LUT)||
            flags==(YB_NATIVE_PLAYBACK_FP32|YB_NATIVE_PLAYBACK_PLANAR_OUTPUT)||
            flags==(YB_NATIVE_PLAYBACK_FP32|YB_NATIVE_PLAYBACK_NLQ_LUT|YB_NATIVE_PLAYBACK_PLANAR_OUTPUT);
        assert((yb_native_playback_options_validate(&native)==YB_NATIVE_PLAYBACK_OK)==valid);
    }
    native.flags=YB_NATIVE_PLAYBACK_FP32|YB_NATIVE_PLAYBACK_NLQ_LUT;
    for(unsigned issue=0;issue<3;issue++){
        yb_native_playback_options invalid=native;
        if(issue==0)invalid.version=0;
        if(issue==1)invalid.reserved[0]=1;
        if(issue==2)invalid.reserved[1]=1;
        yb_native_playback_context *context=NULL;
        assert(yb_native_playback_create_ex(NULL,&invalid,&context)==YB_NATIVE_PLAYBACK_ARGUMENT&&!context);
    }
    yb_gpu_nlq_lut_stats stats={1,7,8,9,10,11,12},saved=stats;
    assert(yb_gpu_fp32_get_nlq_lut_stats(NULL,&stats,sizeof(stats))==YB_GPU_BACKEND_ARGUMENT);
    assert(!memcmp(&stats,&saved,sizeof(stats)));
    assert(yb_gpu_fp32_get_nlq_lut_stats((yb_gpu_fp32 *)(uintptr_t)1,(yb_gpu_nlq_lut_stats *)(uintptr_t)1,0)==YB_GPU_BACKEND_ARGUMENT);
    assert(yb_native_playback_nlq_lut_get_stats((yb_native_playback_context *)(uintptr_t)1,(yb_gpu_nlq_lut_stats *)(uintptr_t)1,0)==YB_NATIVE_PLAYBACK_ARGUMENT);
    puts("Explicit options validation, legacy constructor preflight, size-safe atomic getters PASS (no GPU/VA execution)");
    return 0;
}
