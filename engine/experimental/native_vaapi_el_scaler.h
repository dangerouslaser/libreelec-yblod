#ifndef YB_NATIVE_VAAPI_EL_SCALER_H
#define YB_NATIVE_VAAPI_EL_SCALER_H
#include <stdint.h>
#include <va/va.h>
#ifdef __cplusplus
extern "C" {
#endif
struct yb_vaapi_el_scaler;
enum { YB_VPP_OK=0, YB_VPP_INVALID=1, YB_VPP_UNSUPPORTED=2,
       YB_VPP_DRIVER=3, YB_VPP_PENDING=4, YB_VPP_QUARANTINED=5 };
enum { YB_VPP_FAST=1, YB_VPP_BILINEAR=2 };
struct yb_vaapi_el_scale_config {
    uint32_t input_width, input_height, output_width, output_height;
    uint32_t filter, pipeline_fast, colour_range;
    uint32_t input_chroma, output_chroma;
};
/* All fields explicit. Only top-left -> left P010, matching BT2020 and
 * identical full/reduced ranges. No Annex-B equivalence or whole-code promise.
 * display is borrowed; input dimensions/format are caller-established facts.
 * Caller initializes *output=NULL; no ownership is silently overwritten. */
int yb_vaapi_el_scale_validate(const struct yb_vaapi_el_scale_config *config);
int yb_vaapi_el_scaler_create(VADisplay display,
    const struct yb_vaapi_el_scale_config *config,
    struct yb_vaapi_el_scaler **output);
/* Raw advertised extra filter flags, not proof a requested selector is honored.
 * Scaling/interpolation selectors are encoded values, not independent bits. */
uint32_t yb_vaapi_el_scaler_filter_caps(const struct yb_vaapi_el_scaler *scaler);
/* Each wait <=5 seconds. Input must remain owned until successful finish.
 * Caller must complete prior external consumers before submitting/releasing.
 * No CPU upload, download, mapping, EGL import or borrowed display termination. */
int yb_vaapi_el_scaler_submit(struct yb_vaapi_el_scaler *scaler,
    VASurfaceID input, uint64_t producer_timeout_ns);
int yb_vaapi_el_scaler_finish(struct yb_vaapi_el_scaler *scaler,
    uint64_t timeout_ns, VASurfaceID *output);
/* Pending successful submissions are retained, not destroyed: retry finish.
 * Any RenderPicture/EndPicture failure quarantines the entire object. Surface
 * synchronization does NOT establish that a failed context is quiescent.
 * submit/finish/destroy then return QUARANTINED without making further VA calls.
 * Keep borrowed input and associated storage alive until display owner performs
 * complete display/device teardown. Do not recycle input or output surfaces. */
int yb_vaapi_el_scaler_destroy(struct yb_vaapi_el_scaler **scaler);
/* Only after caller has completed whole borrowed-display/device teardown and
 * invalidated ALL its objects; acknowledgement must equal 1. Frees host memory
 * only, never VA resources. This is an explicit caller assertion, not proof. */
int yb_vaapi_el_scaler_abandon_after_display_teardown(
    struct yb_vaapi_el_scaler **scaler, uint32_t teardown_complete);
#ifdef __cplusplus
}
#endif
#endif
