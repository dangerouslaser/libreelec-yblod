#include "native_decoder_frame_bridge.h"
#include <string.h>

static int span(const void *p, size_t n, size_t alignment)
{
    return p && (uintptr_t)p % alignment == 0U && n <= UINTPTR_MAX-(uintptr_t)p;
}
static int overlap(const void *a,size_t an,const void *b,size_t bn)
{
    return (uintptr_t)a < (uintptr_t)b+bn && (uintptr_t)b < (uintptr_t)a+an;
}
uint32_t yb_decoder_frame_bridge_abi_version(void) { return 1U; }
uint64_t yb_decoder_frame_bridge_sizeof_instructions(void)
{ return (uint64_t)sizeof(yb_dovi_integer_instructions); }

int yb_decoder_frame_bridge_init(yb_integration_context *context,
    const yb_integration_descriptor *descriptor,const void *blob,size_t bytes)
{
    yb_dovi_integer_instructions owned;
    if(bytes!=sizeof(owned) || !span(blob,bytes,1U) ||
       !span(context,sizeof(*context),_Alignof(yb_integration_context)) ||
       !span(descriptor,sizeof(*descriptor),_Alignof(yb_integration_descriptor)))
        return YB_INTEGRATION_INVALID;
    if(overlap(context,sizeof(*context),blob,bytes) ||
       overlap(context,sizeof(*context),descriptor,sizeof(*descriptor)) ||
       overlap(blob,bytes,descriptor,sizeof(*descriptor)))
        return YB_INTEGRATION_ALIAS;
    memcpy(&owned,blob,sizeof(owned));
    if(owned.version!=1U || (owned.residual_enabled!=0 && owned.residual_enabled!=1) ||
       (owned.output_depth!=10 && owned.output_depth!=12) ||
       owned.spatial_resampling_filter_flag>1U || owned.el_spatial_resampling_filter_flag>1U ||
       owned.chroma_resampling_explicit_filter_flag!=0U || owned.bl_video_full_range_flag>1U ||
       owned.source_rpu_profile>15U || owned.source_rpu_level>15U ||
       (owned.mapping.bit_depth!=8 && owned.mapping.bit_depth!=10) ||
       owned.mapping.denominator<13 || owned.mapping.denominator>32 ||
       descriptor->input_kind!=YB_INPUT_WHOLE_CODES ||
       descriptor->output_depth!=owned.output_depth ||
       descriptor->enhancement_enabled!=owned.residual_enabled)
        return YB_INTEGRATION_INVALID;
    if(!owned.residual_enabled) {
        for(unsigned i=0;i<3U;++i) {
            const struct yb_nlq_config *n=&owned.nlq[i];
            if(n->bit_depth || n->denominator || n->offset || n->slope ||
               n->threshold || n->maximum) return YB_INTEGRATION_INVALID;
        }
    }
    return yb_integration_init(context,descriptor,&owned.mapping,
                              owned.residual_enabled?owned.nlq:NULL,NULL);
}
