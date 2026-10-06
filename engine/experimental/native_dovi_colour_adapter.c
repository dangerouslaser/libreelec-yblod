#include "native_dovi_colour_adapter.h"
#include <libavutil/dovi_meta.h>
#include <limits.h>
#include <string.h>
typedef struct {size_t offset,length;} colour_region;
static int colour_address(const void *p,size_t bytes,size_t alignment)
{
    return p&&(uintptr_t)p%alignment==0&&bytes<=UINTPTR_MAX-(uintptr_t)p;
}
static int colour_overlap(uintptr_t a,size_t an,uintptr_t b,size_t bn)
{
    return an&&bn&&a<b+bn&&b<a+an;
}
static int colour_layout(const void *data,size_t bytes)
{
    const AVDOVIMetadata *m=data;
    if(m->num_ext_blocks<0||m->num_ext_blocks>AV_DOVI_MAX_EXT_BLOCKS||
        m->ext_block_size<sizeof(AVDOVIDmData)||m->ext_block_size%_Alignof(AVDOVIDmData)) return 0;
    size_t n=(size_t)m->num_ext_blocks;
    if(n&&m->ext_block_size>SIZE_MAX/n) return 0;
    const colour_region r[4]={{m->header_offset,sizeof(AVDOVIRpuDataHeader)},
        {m->mapping_offset,sizeof(AVDOVIDataMapping)}, {m->color_offset,sizeof(AVDOVIColorMetadata)},
        {m->ext_block_offset,n*m->ext_block_size}};
    const size_t alignment[4]={_Alignof(AVDOVIRpuDataHeader),_Alignof(AVDOVIDataMapping),
        _Alignof(AVDOVIColorMetadata),_Alignof(AVDOVIDmData)};
    for(unsigned i=0;i<4;++i) {
        if(r[i].offset<sizeof(*m)||r[i].offset>bytes||r[i].length>bytes-r[i].offset||
            ((uintptr_t)data+r[i].offset)%alignment[i]) return 0;
        for(unsigned j=0;j<i;++j) if(colour_overlap((uintptr_t)data+r[i].offset,r[i].length,
            (uintptr_t)data+r[j].offset,r[j].length)) return 0;
    }
    return 1;
}
/* Validate dyadic fixed syntax range after FFmpeg rational normalization. The
 * product fits int64: int32 numerator times maximum2^28 scale is below2^59.
 * Decoder-side lossy raw-offset reduction cannot be undone here. */
static int colour_rational(AVRational value,int64_t scale,int64_t minimum,int64_t maximum,double *out)
{
    if(value.den<=0) return 0;
    int64_t product=(int64_t)value.num*scale;
    if(product%value.den) return 0;
    int64_t coefficient=product/value.den;
    if(coefficient<minimum||coefficient>maximum) return 0;
    *out=(double)value.num/(double)value.den;
    return 1;
}
uint32_t yb_dovi_colour_adapter_abi_version(void) {return 1;}
int yb_dovi_to_colour_config(const void *data,size_t bytes,int32_t uncompressed,
                             const struct yb_dovi_colour_target *target,
                             struct yb_colour_config *output)
{
    if(bytes<sizeof(AVDOVIMetadata)||bytes>1024u*1024u||
        !colour_address(data,bytes,_Alignof(AVDOVIMetadata))||
        !colour_address(target,sizeof(*target),_Alignof(struct yb_dovi_colour_target))||
        !colour_address(output,sizeof(*output),_Alignof(struct yb_colour_config))) return YB_DOVI_COLOUR_ARGUMENT;
    if(colour_overlap((uintptr_t)data,bytes,(uintptr_t)output,sizeof(*output))||
        colour_overlap((uintptr_t)target,sizeof(*target),(uintptr_t)output,sizeof(*output))) return YB_DOVI_COLOUR_ALIAS;
    if(!colour_layout(data,bytes)) return YB_DOVI_COLOUR_LAYOUT;
    const AVDOVIMetadata *metadata=data;
    const AVDOVIRpuDataHeader *header=av_dovi_get_header(metadata);
    const AVDOVIColorMetadata *dm=av_dovi_get_color(metadata);
    if(uncompressed!=1||header->rpu_type!=2||header->rpu_format!=18||
        header->vdr_rpu_normalized_idc!=1||header->vdr_bit_depth!=12||
        dm->signal_eotf!=65535||dm->signal_eotf_param0||dm->signal_eotf_param1||dm->signal_eotf_param2||
        dm->signal_bit_depth!=12||dm->signal_color_space||dm->signal_chroma_format||dm->signal_full_range_flag!=1)
        return YB_DOVI_COLOUR_UNSUPPORTED;
    struct yb_colour_parameters p;memset(&p,0,sizeof(p));
    for(unsigned i=0;i<9;++i) {
        if(!colour_rational(dm->ycc_to_rgb_matrix[i],8192,INT16_MIN,INT16_MAX,&p.source_ycc[i])||
            !colour_rational(dm->rgb_to_lms_matrix[i],16384,INT16_MIN,INT16_MAX,&p.source_lms[i])) return YB_DOVI_COLOUR_SOURCE_SCALE;
    }
    for(unsigned i=0;i<3;++i) if(!colour_rational(dm->ycc_to_rgb_offset[i],INT64_C(1)<<28,0,UINT32_MAX,&p.source_offset[i])) return YB_DOVI_COLOUR_SOURCE_SCALE;
    memcpy(p.target_ycc,target->ycc,sizeof(p.target_ycc));
    memcpy(p.target_offset,target->offset,sizeof(p.target_offset));
    memcpy(p.target_lms,target->lms,sizeof(p.target_lms));
    p.pq_policy=target->pq_policy;p.code_scale=target->code_scale;
    struct yb_colour_config candidate;
    if(yb_colour_init(&p,&candidate)!=YB_COLOUR_OK) return YB_DOVI_COLOUR_TARGET;
    memcpy(output,&candidate,sizeof(candidate));return YB_DOVI_COLOUR_OK;
}
