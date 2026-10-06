#include "native_vaapi_el_scaler.h"
#include <va/va_vpp.h>
#include <stdio.h>
#define CHECK(x) do { if (!(x)) return 1; } while (0)
int main(void)
{
    struct yb_vaapi_el_scale_config good={1920,1080,3840,2160,
        YB_VPP_BILINEAR,1,VA_SOURCE_RANGE_FULL,
        VA_CHROMA_SITING_VERTICAL_TOP|VA_CHROMA_SITING_HORIZONTAL_LEFT,
        VA_CHROMA_SITING_VERTICAL_CENTER|VA_CHROMA_SITING_HORIZONTAL_LEFT};
    struct yb_vaapi_el_scale_config c=good;
    CHECK(yb_vaapi_el_scale_validate(&c)==0);
    c.filter=YB_VPP_FAST; c.pipeline_fast=0; c.colour_range=VA_SOURCE_RANGE_REDUCED;
    CHECK(yb_vaapi_el_scale_validate(&c)==0);
    CHECK(yb_vaapi_el_scale_validate(NULL)==YB_VPP_INVALID);
    for (unsigned i=0;i<10;i++) {
        c=good;
        switch (i) {
        case 0:c.input_width=0;break;
        case 1:c.input_height=1079;break;
        case 2:c.output_width=3838;break;
        case 3:c.output_height=2162;break;
        case 4:c.filter=0;break;
        case 5:c.pipeline_fast=2;break;
        case 6:c.colour_range=0;break;
        case 7:c.input_chroma=good.output_chroma;break;
        case 8:c.output_chroma=good.input_chroma;break;
        default:c.input_width=UINT32_MAX;break;
        }
        CHECK(yb_vaapi_el_scale_validate(&c)==YB_VPP_INVALID);
    }
    struct yb_vaapi_el_scaler *handle=NULL;
    CHECK(yb_vaapi_el_scaler_create(NULL,&good,&handle)==YB_VPP_INVALID);
    CHECK(handle==NULL);
    CHECK(yb_vaapi_el_scaler_destroy(&handle)==0);
    CHECK(yb_vaapi_el_scaler_destroy(NULL)==YB_VPP_INVALID);
    CHECK(yb_vaapi_el_scaler_submit(NULL,0,1)==YB_VPP_INVALID);
    VASurfaceID output=123;
    CHECK(yb_vaapi_el_scaler_finish(NULL,1,&output)==YB_VPP_INVALID);
    CHECK(output==123);
    puts("{\"checks\":21,\"passed\":true,\"driver_called\":false}");
    return 0;
}
