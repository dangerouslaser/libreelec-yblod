/* Real libva declarations; deterministic replacement function bodies only.
 * This tests helper control flow, NOT a driver, hardware or scheduler. */
#include "native_vaapi_el_scaler.h"
#include <va/va_vpp.h>
#include <stdio.h>
#include <string.h>
static int fail_render,fail_end,fail_sync,fail_destroy,calls,destroy_calls;
static VAProcPipelineParameterBuffer observed;
#define OK VA_STATUS_SUCCESS
#define FAIL VA_STATUS_ERROR_OPERATION_FAILED
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"failed line %d\n",__LINE__); return 1; } } while (0)
/* The unused arguments are intentional: mocks preserve exact public signatures. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
VAStatus vaCreateConfig(VADisplay d,VAProfile p,VAEntrypoint e,VAConfigAttrib *a,int n,VAConfigID *o)
{ calls++; *o=10; return OK; }
VAStatus vaQuerySurfaceAttributes(VADisplay d,VAConfigID c,VASurfaceAttrib *a,unsigned *n)
{
    calls++;
    if (!a) { *n=1; return OK; }
    *n=1; memset(a,0,sizeof(*a)); a->type=VASurfaceAttribPixelFormat;
    a->flags=VA_SURFACE_ATTRIB_SETTABLE; a->value.type=VAGenericValueTypeInteger;
    a->value.value.i=(int)VA_FOURCC_P010; return OK;
}
VAStatus vaCreateSurfaces(VADisplay d,unsigned f,unsigned w,unsigned h,VASurfaceID *o,unsigned n,VASurfaceAttrib *a,unsigned na)
{ calls++; *o=20; return OK; }
VAStatus vaCreateContext(VADisplay d,VAConfigID c,int w,int h,int flags,VASurfaceID *r,int n,VAContextID *o)
{ calls++; *o=30; return OK; }
VAStatus vaQueryVideoProcPipelineCaps(VADisplay d,VAContextID c,VABufferID *f,unsigned n,VAProcPipelineCaps *o)
{
    calls++; o->pipeline_flags=VA_PROC_PIPELINE_FAST; o->filter_flags=0xabcdef;
    o->input_color_standards[0]=VAProcColorStandardBT2020;
    o->output_color_standards[0]=VAProcColorStandardBT2020;
    o->num_input_color_standards=o->num_output_color_standards=1;
    return OK;
}
VAStatus vaCreateBuffer(VADisplay d,VAContextID c,VABufferType t,unsigned size,unsigned n,void *data,VABufferID *o)
{ calls++; observed=*(VAProcPipelineParameterBuffer *)data; *o=40; return OK; }
VAStatus vaBeginPicture(VADisplay d,VAContextID c,VASurfaceID s)
{ calls++; return OK; }
VAStatus vaRenderPicture(VADisplay d,VAContextID c,VABufferID *b,int n)
{ calls++; return fail_render ? FAIL : OK; }
VAStatus vaEndPicture(VADisplay d,VAContextID c)
{ calls++; return fail_end ? FAIL : OK; }
VAStatus vaSyncSurface2(VADisplay d,VASurfaceID s,uint64_t timeout)
{ calls++; return fail_sync==2 ? FAIL : fail_sync ? VA_STATUS_ERROR_TIMEDOUT : OK; }
VAStatus vaDestroyBuffer(VADisplay d,VABufferID b)
{ calls++; destroy_calls++; return fail_destroy ? FAIL : OK; }
VAStatus vaDestroyContext(VADisplay d,VAContextID c)
{ calls++; destroy_calls++; return OK; }
VAStatus vaDestroySurfaces(VADisplay d,VASurfaceID *s,int n)
{ calls++; destroy_calls++; return OK; }
VAStatus vaDestroyConfig(VADisplay d,VAConfigID c)
{ calls++; destroy_calls++; return OK; }
#pragma GCC diagnostic pop
int main(void)
{
    int display_cookie=1;
    VADisplay display=&display_cookie;
    struct yb_vaapi_el_scale_config config={1920,1080,3840,2160,
        YB_VPP_BILINEAR,1,VA_SOURCE_RANGE_FULL,
        VA_CHROMA_SITING_VERTICAL_TOP|VA_CHROMA_SITING_HORIZONTAL_LEFT,
        VA_CHROMA_SITING_VERTICAL_CENTER|VA_CHROMA_SITING_HORIZONTAL_LEFT};
    struct yb_vaapi_el_scaler *s=NULL;
    VASurfaceID out=99;
    CHECK(yb_vaapi_el_scaler_create(display,&config,&s)==0);
    CHECK(yb_vaapi_el_scaler_filter_caps(s)==0xabcdef);
    CHECK(yb_vaapi_el_scaler_submit(s,21,1)==0);
    CHECK(observed.surface==21 && observed.filter_flags==VA_FILTER_INTERPOLATION_BILINEAR);
    CHECK(observed.pipeline_flags==VA_PROC_PIPELINE_FAST &&
          observed.input_color_properties.chroma_sample_location==config.input_chroma &&
          observed.output_color_properties.chroma_sample_location==config.output_chroma);
    CHECK(yb_vaapi_el_scaler_submit(s,21,1)==YB_VPP_PENDING);
    CHECK(yb_vaapi_el_scaler_destroy(&s)==YB_VPP_PENDING);
    fail_sync=1;
    CHECK(yb_vaapi_el_scaler_finish(s,1,&out)==YB_VPP_PENDING && out==99);
    fail_sync=0;
    CHECK(yb_vaapi_el_scaler_finish(s,1,&out)==0 && out==20);
    CHECK(yb_vaapi_el_scaler_finish(s,1,&out)==YB_VPP_INVALID);
    fail_destroy=1;
    CHECK(yb_vaapi_el_scaler_destroy(&s)==YB_VPP_DRIVER && s!=NULL);
    CHECK(yb_vaapi_el_scaler_submit(s,21,1)==YB_VPP_INVALID);
    fail_destroy=0;
    CHECK(yb_vaapi_el_scaler_destroy(&s)==0 && s==NULL);
    for (int mode=0;mode<3;mode++) {
        CHECK(yb_vaapi_el_scaler_create(display,&config,&s)==0);
        fail_render=mode==0; fail_end=mode==1;
        if (mode==2) {
            CHECK(yb_vaapi_el_scaler_submit(s,21,1)==0);
            fail_sync=2;
            CHECK(yb_vaapi_el_scaler_finish(s,1,&out)==YB_VPP_QUARANTINED);
            fail_sync=0;
        } else CHECK(yb_vaapi_el_scaler_submit(s,21,1)==YB_VPP_QUARANTINED);
        int before=calls,deleted=destroy_calls;
        out=99;
        CHECK(yb_vaapi_el_scaler_finish(s,1,&out)==YB_VPP_QUARANTINED && out==99);
        CHECK(yb_vaapi_el_scaler_submit(s,21,1)==YB_VPP_QUARANTINED);
        CHECK(yb_vaapi_el_scaler_destroy(&s)==YB_VPP_QUARANTINED && s!=NULL);
        CHECK(yb_vaapi_el_scaler_abandon_after_display_teardown(&s,0)==YB_VPP_INVALID && s!=NULL);
        CHECK(calls==before && destroy_calls==deleted);
        /* Mock fixture teardown is external; abandon only frees host state. */
        CHECK(yb_vaapi_el_scaler_abandon_after_display_teardown(&s,1)==0 && s==NULL);
        CHECK(calls==before);
        fail_render=fail_end=0;
    }
    puts("{\"fault_scenarios\":6,\"passed\":true,\"hardware_test\":false}");
    return 0;
}
