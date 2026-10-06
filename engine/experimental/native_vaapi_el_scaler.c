#include "native_vaapi_el_scaler.h"
#include <stdlib.h>
#include <va/va_vpp.h>
#define WAIT_MAX UINT64_C(5000000000)
struct yb_vaapi_el_scaler {
    VADisplay display;
    VAConfigID config;
    VAContextID context;
    VASurfaceID surface;
    VABufferID buffer;
    struct yb_vaapi_el_scale_config settings;
    uint32_t filter_caps;
    int pending, failed, poisoned, closing;
};
static int overlaps(const void *a,size_t an,const void *b,size_t bn)
{
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x<=y ? y-x<an : x-y<bn;
}
int yb_vaapi_el_scale_validate(const struct yb_vaapi_el_scale_config *c)
{
    if (!c || !c->input_width || !c->input_height ||
        c->input_width > 3840 || c->input_height > 2160 ||
        c->output_width > 3840 || c->output_height > 2160 ||
        c->output_width != c->input_width * 2 ||
        c->output_height != c->input_height * 2 ||
        ((c->input_width | c->input_height) & 1U) ||
        (c->filter != YB_VPP_FAST && c->filter != YB_VPP_BILINEAR) ||
        c->pipeline_fast > 1 ||
        (c->colour_range != VA_SOURCE_RANGE_FULL &&
         c->colour_range != VA_SOURCE_RANGE_REDUCED) ||
        c->input_chroma != (VA_CHROMA_SITING_VERTICAL_TOP | VA_CHROMA_SITING_HORIZONTAL_LEFT) ||
        c->output_chroma != (VA_CHROMA_SITING_VERTICAL_CENTER | VA_CHROMA_SITING_HORIZONTAL_LEFT))
        return YB_VPP_INVALID;
    return YB_VPP_OK;
}
static int capabilities(struct yb_vaapi_el_scaler *s)
{
    unsigned count=0;
    if (vaQuerySurfaceAttributes(s->display,s->config,NULL,&count)!=VA_STATUS_SUCCESS ||
        !count || count>4096) return YB_VPP_UNSUPPORTED;
    unsigned capacity=count;
    VASurfaceAttrib *a=calloc(count,sizeof(*a));
    if (!a) return YB_VPP_DRIVER;
    VAStatus status=vaQuerySurfaceAttributes(s->display,s->config,a,&count);
    int available=0;
    if (status==VA_STATUS_SUCCESS && count<=capacity) {
        for (unsigned i=0;i<count;i++)
            if (a[i].type==VASurfaceAttribPixelFormat &&
                a[i].value.type==VAGenericValueTypeInteger &&
                (unsigned)a[i].value.value.i==VA_FOURCC_P010 &&
                (a[i].flags & VA_SURFACE_ATTRIB_SETTABLE)) available=1;
    }
    free(a);
    return available ? YB_VPP_OK : YB_VPP_UNSUPPORTED;
}
static int pipeline_caps(struct yb_vaapi_el_scaler *s)
{
    VAProcColorStandardType input[64]={0},output[64]={0};
    VAProcPipelineCaps c={0};
    c.input_color_standards=input; c.num_input_color_standards=64;
    c.output_color_standards=output; c.num_output_color_standards=64;
    if (vaQueryVideoProcPipelineCaps(s->display,s->context,NULL,0,&c)!=VA_STATUS_SUCCESS)
        return YB_VPP_UNSUPPORTED;
    s->filter_caps=c.filter_flags;
    if (c.num_input_color_standards>64 || c.num_output_color_standards>64 ||
        c.num_input_pixel_formats>64 || c.num_output_pixel_formats>64 ||
        (c.num_input_color_standards && !c.input_color_standards) ||
        (c.num_output_color_standards && !c.output_color_standards) ||
        (c.num_input_pixel_formats && !c.input_pixel_format) ||
        (c.num_output_pixel_formats && !c.output_pixel_format)) return YB_VPP_UNSUPPORTED;
    int ib=0,ob=0,ip=!c.num_input_pixel_formats,op=!c.num_output_pixel_formats;
    for (unsigned i=0;i<c.num_input_color_standards;i++)
        ib |= c.input_color_standards[i]==VAProcColorStandardBT2020;
    for (unsigned i=0;i<c.num_output_color_standards;i++)
        ob |= c.output_color_standards[i]==VAProcColorStandardBT2020;
    for (unsigned i=0;i<c.num_input_pixel_formats;i++) ip |= c.input_pixel_format[i]==VA_FOURCC_P010;
    for (unsigned i=0;i<c.num_output_pixel_formats;i++) op |= c.output_pixel_format[i]==VA_FOURCC_P010;
    const struct yb_vaapi_el_scale_config *v=&s->settings;
    if (!ib || !ob || !ip || !op ||
        (v->pipeline_fast && !(c.pipeline_flags & VA_PROC_PIPELINE_FAST)) ||
        v->input_width<c.min_input_width || v->input_height<c.min_input_height ||
        (c.max_input_width && v->input_width>c.max_input_width) ||
        (c.max_input_height && v->input_height>c.max_input_height) ||
        v->output_width<c.min_output_width || v->output_height<c.min_output_height ||
        (c.max_output_width && v->output_width>c.max_output_width) ||
        (c.max_output_height && v->output_height>c.max_output_height)) return YB_VPP_UNSUPPORTED;
    return YB_VPP_OK;
}
uint32_t yb_vaapi_el_scaler_filter_caps(const struct yb_vaapi_el_scaler *s)
{
    return s ? s->filter_caps : 0;
}
int yb_vaapi_el_scaler_destroy(struct yb_vaapi_el_scaler **handle)
{
    if (!handle) return YB_VPP_INVALID;
    struct yb_vaapi_el_scaler *s=*handle;
    if (!s) return YB_VPP_OK;
    if (overlaps(handle,sizeof(*handle),s,sizeof(*s))) return YB_VPP_INVALID;
    if (s->poisoned) return YB_VPP_QUARANTINED;
    if (s->pending) return YB_VPP_PENDING;
    s->closing=1;
    /* Clear each successfully destroyed name; a failure remains retryable. */
    if (s->buffer!=VA_INVALID_ID) {
        if (vaDestroyBuffer(s->display,s->buffer)!=VA_STATUS_SUCCESS) return YB_VPP_DRIVER;
        s->buffer=VA_INVALID_ID;
    }
    if (s->context!=VA_INVALID_ID) {
        if (vaDestroyContext(s->display,s->context)!=VA_STATUS_SUCCESS) return YB_VPP_DRIVER;
        s->context=VA_INVALID_ID;
    }
    if (s->surface!=VA_INVALID_ID) {
        if (vaDestroySurfaces(s->display,&s->surface,1)!=VA_STATUS_SUCCESS) return YB_VPP_DRIVER;
        s->surface=VA_INVALID_ID;
    }
    if (s->config!=VA_INVALID_ID) {
        if (vaDestroyConfig(s->display,s->config)!=VA_STATUS_SUCCESS) return YB_VPP_DRIVER;
        s->config=VA_INVALID_ID;
    }
    free(s); *handle=NULL; return YB_VPP_OK;
}
int yb_vaapi_el_scaler_abandon_after_display_teardown(
    struct yb_vaapi_el_scaler **handle,uint32_t complete)
{
    if (!handle || complete!=1) return YB_VPP_INVALID;
    if (*handle && overlaps(handle,sizeof(*handle),*handle,sizeof(**handle))) return YB_VPP_INVALID;
    free(*handle); *handle=NULL;
    return YB_VPP_OK;
}
int yb_vaapi_el_scaler_create(VADisplay d,const struct yb_vaapi_el_scale_config *c,
    struct yb_vaapi_el_scaler **out)
{
    if (!d || !out || !c || overlaps(out,sizeof(*out),c,sizeof(*c)) ||
        *out || yb_vaapi_el_scale_validate(c)) return YB_VPP_INVALID;
    struct yb_vaapi_el_scaler *s=calloc(1,sizeof(*s));
    if (!s) return YB_VPP_DRIVER;
    s->display=d; s->settings=*c;
    s->config=s->context=s->surface=s->buffer=VA_INVALID_ID;
    int result=YB_VPP_DRIVER;
    if (vaCreateConfig(d,VAProfileNone,VAEntrypointVideoProc,NULL,0,&s->config)!=VA_STATUS_SUCCESS) goto fail;
    result=capabilities(s); if (result) goto fail;
    result=YB_VPP_DRIVER;
    VASurfaceAttrib attr={0}; attr.type=VASurfaceAttribPixelFormat;
    attr.flags=VA_SURFACE_ATTRIB_SETTABLE; attr.value.type=VAGenericValueTypeInteger;
    attr.value.value.i=(int)VA_FOURCC_P010;
    if (vaCreateSurfaces(d,VA_RT_FORMAT_YUV420_10,c->output_width,c->output_height,&s->surface,1,&attr,1)!=VA_STATUS_SUCCESS) goto fail;
    if (vaCreateContext(d,s->config,(int)c->output_width,(int)c->output_height,VA_PROGRESSIVE,&s->surface,1,&s->context)!=VA_STATUS_SUCCESS) goto fail;
    result=pipeline_caps(s); if (result) goto fail;
    *out=s; return YB_VPP_OK;
fail:
    if (yb_vaapi_el_scaler_destroy(&s)!=YB_VPP_OK) *out=s;
    return result;
}
int yb_vaapi_el_scaler_submit(struct yb_vaapi_el_scaler *s,VASurfaceID input,uint64_t timeout)
{
    if (!s || input==VA_INVALID_ID || input==s->surface || !timeout || timeout>WAIT_MAX ||
        s->context==VA_INVALID_ID || s->closing) return YB_VPP_INVALID;
    if (s->poisoned) return YB_VPP_QUARANTINED;
    if (s->pending) return YB_VPP_PENDING;
    if (vaSyncSurface2(s->display,input,timeout)!=VA_STATUS_SUCCESS) return YB_VPP_DRIVER;
    if (s->buffer!=VA_INVALID_ID) {
        if (vaDestroyBuffer(s->display,s->buffer)!=VA_STATUS_SUCCESS) return YB_VPP_DRIVER;
        s->buffer=VA_INVALID_ID;
    }
    const struct yb_vaapi_el_scale_config *c=&s->settings;
    VARectangle src={0,0,(uint16_t)c->input_width,(uint16_t)c->input_height};
    VARectangle dst={0,0,(uint16_t)c->output_width,(uint16_t)c->output_height};
    VAProcPipelineParameterBuffer p={0};
    p.surface=input; p.surface_region=&src; p.output_region=&dst;
    p.filter_flags=c->filter==YB_VPP_FAST ? VA_FILTER_SCALING_FAST : VA_FILTER_INTERPOLATION_BILINEAR;
    p.pipeline_flags=c->pipeline_fast ? VA_PROC_PIPELINE_FAST : 0;
    p.surface_color_standard=p.output_color_standard=VAProcColorStandardBT2020;
    p.input_color_properties.color_range=(uint8_t)c->colour_range;
    p.input_color_properties.chroma_sample_location=(uint8_t)c->input_chroma;
    p.output_color_properties=p.input_color_properties;
    p.output_color_properties.chroma_sample_location=(uint8_t)c->output_chroma;
    if (vaCreateBuffer(s->display,s->context,VAProcPipelineParameterBufferType,sizeof(p),1,&p,&s->buffer)!=VA_STATUS_SUCCESS)
        return YB_VPP_DRIVER;
    if (vaBeginPicture(s->display,s->context,s->surface)!=VA_STATUS_SUCCESS) return YB_VPP_DRIVER;
    s->pending=1; s->failed=0;
    if (vaRenderPicture(s->display,s->context,&s->buffer,1)!=VA_STATUS_SUCCESS) {
        s->failed=1;
        s->poisoned=1;
    }
    if (vaEndPicture(s->display,s->context)!=VA_STATUS_SUCCESS) {
        s->failed=1;
        s->poisoned=1;
    }
    return s->failed ? YB_VPP_QUARANTINED : YB_VPP_OK;
}
int yb_vaapi_el_scaler_finish(struct yb_vaapi_el_scaler *s,uint64_t timeout,VASurfaceID *out)
{
    if (!s || !out || overlaps(out,sizeof(*out),s,sizeof(*s)) ||
        !timeout || timeout>WAIT_MAX) return YB_VPP_INVALID;
    if (s->poisoned) return YB_VPP_QUARANTINED;
    if (!s->pending) return YB_VPP_INVALID;
    VAStatus status=vaSyncSurface2(s->display,s->surface,timeout);
    if (status==VA_STATUS_ERROR_TIMEDOUT) return YB_VPP_PENDING;
    if (status!=VA_STATUS_SUCCESS) {
        s->poisoned=1;
        return YB_VPP_QUARANTINED;
    }
    s->pending=0;
    if (s->failed) return YB_VPP_DRIVER;
    *out=s->surface; return YB_VPP_OK;
}
