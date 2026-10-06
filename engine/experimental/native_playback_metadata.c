#include "native_playback_metadata.h"
#include <string.h>
static int address(const void *p,size_t bytes,size_t alignment)
{
    return p && (uintptr_t)p%alignment==0 && bytes<=UINTPTR_MAX-(uintptr_t)p;
}
static int overlap(const void *a,size_t an,const void *b,size_t bn)
{
    return an && bn && (uintptr_t)a<(uintptr_t)b+bn && (uintptr_t)b<(uintptr_t)a+an;
}
static int token(const uint8_t id[32])
{
    uint8_t bits=0;for(unsigned i=0;i<32;++i)bits|=id[i];return bits!=0;
}
static int timestamp(const yb_playback_frame_descriptor *d)
{
    if(d->bl_pts==INT64_MIN||d->el_pts==INT64_MIN||d->bl_timebase_num<=0||d->bl_timebase_den<=0||d->el_timebase_num<=0||d->el_timebase_den<=0)return 0;
    /* int64 * positive int32 * positive int32 fits signed128. */
    __int128 bl=(__int128)d->bl_pts*d->bl_timebase_num*d->el_timebase_den;
    __int128 el=(__int128)d->el_pts*d->el_timebase_num*d->bl_timebase_den;
    return bl==el;
}
int yb_playback_metadata_init(const yb_playback_frame_descriptor *d,
    const void *data,size_t bytes,const struct yb_dovi_colour_target *target,
    yb_playback_metadata *output)
{
    if(!address(d,sizeof(*d),_Alignof(yb_playback_frame_descriptor))||
       !address(data,bytes,1)||!bytes||bytes>1024u*1024u||
       (target&&!address(target,sizeof(*target),_Alignof(struct yb_dovi_colour_target)))||
       !address(output,sizeof(*output),_Alignof(yb_playback_metadata)))return YB_PLAYBACK_METADATA_ARGUMENT;
    if(overlap(output,sizeof(*output),d,sizeof(*d))||overlap(output,sizeof(*output),data,bytes)||
       (target&&overlap(output,sizeof(*output),target,sizeof(*target))))return YB_PLAYBACK_METADATA_ALIAS;
    yb_playback_metadata candidate;memset(&candidate,0,sizeof(candidate));
    int status=yb_dovi_to_integer_configs(data,bytes,&candidate.integer);
    if(status!=YB_DOVI_ADAPTER_OK)return YB_PLAYBACK_METADATA_INTEGER;
    if(d->colour_route==YB_PLAYBACK_COLOUR_INHERITED) {
        if(target||d->source_dm_uncompressed!=0)return YB_PLAYBACK_METADATA_ARGUMENT;
    } else if(d->colour_route==YB_PLAYBACK_COLOUR_NATIVE) {
        if(!target)return YB_PLAYBACK_METADATA_ARGUMENT;
        status=yb_dovi_to_colour_config(data,bytes,d->source_dm_uncompressed,target,&candidate.colour);
        if(status!=YB_DOVI_COLOUR_OK)return YB_PLAYBACK_METADATA_COLOUR;
        candidate.has_native_colour=1;
    } else return YB_PLAYBACK_METADATA_UNSUPPORTED;
    if(d->version!=1||!d->width||!d->height||(d->width&1u)||(d->height&1u)||
       d->width>3840||d->height>2160||d->el_scaled_width!=d->width||
       d->el_scaled_height!=d->height||d->guide_width!=d->width/2||d->guide_height!=d->height/2)
        return YB_PLAYBACK_METADATA_UNSUPPORTED;
    if(!token(d->frame_id)||!token(d->preparation_id)||!token(d->enhancement_scale_id)||
       memcmp(d->frame_id,d->metadata_frame_id,32)||memcmp(d->frame_id,d->el_frame_id,32)||memcmp(d->frame_id,d->guide_frame_id,32)||
       memcmp(d->preparation_id,d->guide_preparation_id,32)||!timestamp(d))return YB_PLAYBACK_METADATA_ASSOCIATION;
    if(d->input_native_depth!=10||d->input_fractional_bits!=0||
       candidate.integer.mapping.bit_depth!=10||candidate.integer.residual_enabled!=1||
       candidate.integer.output_depth!=12||
       candidate.integer.spatial_resampling_filter_flag!=d->spatial_filter_flag||
       candidate.integer.el_spatial_resampling_filter_flag!=d->el_spatial_filter_flag)
        return YB_PLAYBACK_METADATA_UNSUPPORTED;
    for(unsigned c=0;c<3;++c)if(candidate.integer.nlq[c].bit_depth!=10)return YB_PLAYBACK_METADATA_UNSUPPORTED;
    for(int32_t i=0;i<candidate.integer.mapping.components[0].pivot_count-1;++i)
        if(candidate.integer.mapping.components[0].segments[i].method==YB_MMR)return YB_PLAYBACK_METADATA_UNSUPPORTED;
    status=yb_gpu_check_mapping_width(&candidate.integer.mapping,&candidate.width);
    if(status!=YB_OK)return YB_PLAYBACK_METADATA_INTEGER;
    if(!candidate.width.supported)return YB_PLAYBACK_METADATA_WIDTH;
    candidate.frame=*d;
    memcpy(output,&candidate,sizeof(candidate));return YB_PLAYBACK_METADATA_OK;
}
