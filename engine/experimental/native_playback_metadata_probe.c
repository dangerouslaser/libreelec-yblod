/* Actual patched FFmpeg layout, public synthetic fields; no GPU/media. */
#include "native_playback_metadata.h"
#include <libavutil/dovi_meta.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct {AVDOVIMetadata meta;AVDOVIRpuDataHeader header;AVDOVIDataMapping mapping;
    AVDOVIColorMetadata colour;AVDOVIDmData ext;} Fixture;
int main(int argc,char **argv)
{
    if(argc!=2)return 2;
    char *end=NULL;long which=strtol(argv[1],&end,10);if(!*argv[1]||*end||which<0||which>21)return 2;
    Fixture f;memset(&f,0,sizeof(f));
    f.meta.header_offset=offsetof(Fixture,header);f.meta.mapping_offset=offsetof(Fixture,mapping);
    f.meta.color_offset=offsetof(Fixture,colour);f.meta.ext_block_offset=offsetof(Fixture,ext);f.meta.ext_block_size=sizeof(f.ext);
    f.header.rpu_type=2;f.header.rpu_format=18;f.header.vdr_rpu_profile=1;f.header.coef_log2_denom=23;
    f.header.vdr_rpu_normalized_idc=1;f.header.bl_bit_depth=10;f.header.el_bit_depth=10;f.header.vdr_bit_depth=12;
    f.mapping.num_x_partitions=f.mapping.num_y_partitions=1;f.mapping.nlq_method_idc=AV_DOVI_NLQ_LINEAR_DZ;f.mapping.nlq_pivots[1]=1023;
    for(unsigned c=0;c<3;++c) {
        AVDOVIReshapingCurve *curve=&f.mapping.curves[c];curve->num_pivots=2;curve->pivots[1]=1023;
        curve->mapping_idc[0]=AV_DOVI_MAPPING_POLYNOMIAL;curve->poly_order[0]=1;curve->poly_coef[0][1]=INT64_C(1)<<23;
        f.mapping.nlq[c].nlq_offset=512;f.mapping.nlq[c].linear_deadzone_slope=2048;f.mapping.nlq[c].vdr_in_max=1025;
        f.colour.ycc_to_rgb_offset[c]=(AVRational){0,1<<28};
    }
    f.colour.signal_eotf=65535;f.colour.signal_bit_depth=12;f.colour.signal_full_range_flag=1;
    struct yb_dovi_colour_target target;memset(&target,0,sizeof(target));target.code_scale=4096;target.pq_policy=1;
    for(unsigned i=0;i<9;++i) {
        f.colour.ycc_to_rgb_matrix[i]=(AVRational){i%4?0:8192,8192};
        f.colour.rgb_to_lms_matrix[i]=(AVRational){i%4?0:16384,16384};
        target.ycc[i]=target.lms[i]=i%4?0:1;
    }
    yb_playback_frame_descriptor d;memset(&d,0,sizeof(d));d.version=1;d.width=d.el_scaled_width=4;d.height=d.el_scaled_height=4;d.guide_width=d.guide_height=2;
    d.bl_pts=100;d.el_pts=200;d.bl_timebase_num=d.el_timebase_num=1;d.bl_timebase_den=25;d.el_timebase_den=50;
    memset(d.frame_id,1,32);memcpy(d.metadata_frame_id,d.frame_id,32);memcpy(d.el_frame_id,d.frame_id,32);memcpy(d.guide_frame_id,d.frame_id,32);
    memset(d.preparation_id,2,32);memcpy(d.guide_preparation_id,d.preparation_id,32);memset(d.enhancement_scale_id,3,32);d.input_native_depth=10;d.source_dm_uncompressed=1;d.colour_route=YB_PLAYBACK_COLOUR_NATIVE;
    const struct yb_dovi_colour_target *tp=&target;
    const void *data=&f;size_t bytes=sizeof(f);yb_playback_metadata output;memset(&output,0xa5,sizeof(output));
    switch(which) {
    case 1:d.metadata_frame_id[31]^=1;break;case 2:d.el_frame_id[0]^=1;break;case 3:d.guide_preparation_id[3]^=1;break;
    case 4:d.el_pts++;break;case 5:d.bl_pts=INT64_MIN;d.el_pts=INT64_MIN;break;case 6:d.width=3;break;
    case 7:d.input_fractional_bits=6;break;case 8:f.header.disable_residual_flag=1;break;
    case 9:f.meta.color_offset=SIZE_MAX;break;case 10:target.code_scale=4095;break;case 11:d.source_dm_uncompressed=0;break;
    case 12:f.mapping.curves[0].mapping_idc[0]=AV_DOVI_MAPPING_MMR;f.mapping.curves[0].mmr_order[0]=1;break;
    case 13:f.header.coef_log2_denom=32;for(unsigned c=0;c<3;++c)f.mapping.curves[c].poly_coef[0][1]=INT64_C(1)<<32;
        f.mapping.curves[1].mapping_idc[0]=AV_DOVI_MAPPING_MMR;f.mapping.curves[1].mmr_order[0]=1;f.mapping.curves[1].mmr_constant[0]=INT64_C(1)<<44;break;
    case 14:d.spatial_filter_flag=1;break;case 15:bytes=1;break;case 16:d.bl_timebase_den=0;break;
    case 17:d.colour_route=YB_PLAYBACK_COLOUR_INHERITED;d.source_dm_uncompressed=0;tp=NULL;break;
    case 18:d.colour_route=YB_PLAYBACK_COLOUR_INHERITED;d.source_dm_uncompressed=0;break;
    case 19:d.colour_route=0;break;case 20:tp=NULL;break;
    case 21:d.colour_route=YB_PLAYBACK_COLOUR_INHERITED;tp=NULL;break;
    }
    yb_playback_metadata previous=output;
    int status=yb_playback_metadata_init(&d,data,bytes,tp,&output);
    int atomic=!memcmp(&previous,&output,sizeof(output));int owned=0;
    if(!status) {
        memset(&f,0,sizeof(f));memset(&target,0,sizeof(target));memset(&d,0,sizeof(d));
        int64_t samples[3]={512,512,512};uint16_t mapped=0;
        double colour_input[3]={2048,1024,3072};struct yb_colour_result result;
        struct yb_colour_config zero;memset(&zero,0,sizeof(zero));
        int colour_ok=output.has_native_colour ? yb_colour_sample(&output.colour,colour_input,&result)==YB_COLOUR_OK :
            !memcmp(&output.colour,&zero,sizeof(zero));
        owned=yb_map_sample(&output.integer.mapping,0,samples,&mapped)==YB_OK && colour_ok && output.frame.width==4;
    }
    printf("{\"case\":%ld,\"status\":%d,\"failure_atomic\":%s,\"owned_configs_after_input_release\":%s,\"has_native_colour\":%u}\n",which,status,status&&atomic?"true":"false",owned?"true":"false",status?0:output.has_native_colour);
    return 0;
}
