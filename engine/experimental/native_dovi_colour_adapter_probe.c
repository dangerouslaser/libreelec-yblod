/* Actual matching FFmpeg headers; synthetic owned metadata layout only.
 * No allocation/parser/decoder library execution or raw RPU provenance claim. */
#include "native_dovi_colour_adapter.h"
#include <libavutil/dovi_meta.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct fixture {AVDOVIMetadata meta;AVDOVIRpuDataHeader header;AVDOVIDataMapping mapping;
    AVDOVIColorMetadata colour;AVDOVIDmData ext;};
static void array(const double *values,unsigned count)
{
    putchar('[');for(unsigned i=0;i<count;++i) printf("%s%.17g",i?",":"",values[i]);putchar(']');
}
int main(int argc,char **argv)
{
    if(argc!=2) return 2;
    char *end=NULL;long case_id=strtol(argv[1],&end,10);
    if(!*argv[1]||*end||case_id<0||case_id>44) return 2;
    struct fixture fixture;memset(&fixture,0,sizeof(fixture));
    AVDOVIMetadata *m=&fixture.meta;AVDOVIRpuDataHeader *h=&fixture.header;AVDOVIColorMetadata *d=&fixture.colour;
    m->header_offset=offsetof(struct fixture,header);m->mapping_offset=offsetof(struct fixture,mapping);
    m->color_offset=offsetof(struct fixture,colour);m->ext_block_offset=offsetof(struct fixture,ext);
    m->ext_block_size=sizeof(fixture.ext);m->num_ext_blocks=0;
    h->rpu_type=2;h->rpu_format=18;h->vdr_rpu_normalized_idc=1;h->vdr_bit_depth=12;
    d->signal_eotf=65535;d->signal_bit_depth=12;d->signal_full_range_flag=1;
    for(unsigned i=0;i<9;++i) {
        d->ycc_to_rgb_matrix[i]=(AVRational){i%4?0:8192,8192};
        d->rgb_to_lms_matrix[i]=(AVRational){i%4?0:16384,16384};
    }
    for(unsigned i=0;i<3;++i) d->ycc_to_rgb_offset[i]=(AVRational){0,1<<28};
    struct yb_dovi_colour_target target;memset(&target,0,sizeof(target));
    for(unsigned i=0;i<9;++i) target.ycc[i]=target.lms[i]=i%4?0:1;
    target.pq_policy=YB_PQ_EXTEND_POSITIVE_NEGATIVE_TO_ZERO;target.code_scale=4096;
    struct yb_colour_config output;memset(&output,0xa5,sizeof(output));
    const void *data=&fixture;size_t bytes=sizeof(fixture);int32_t uncompressed=1;
    const struct yb_dovi_colour_target *tp=&target;struct yb_colour_config *out=&output;
    switch(case_id) {
    case 1:d->ycc_to_rgb_matrix[1]=(AVRational){-799,8192};d->rgb_to_lms_matrix[2]=(AVRational){267,16384};break;
    case 2:d->ycc_to_rgb_matrix[0]=(AVRational){1,1};d->rgb_to_lms_matrix[0]=(AVRational){1,1};d->ycc_to_rgb_offset[1]=(AVRational){1,2};break;
    case 3:d->ycc_to_rgb_offset[2]=(AVRational){INT32_MAX,1<<27};break;
    case 4:uncompressed=0;break;case 5:d->signal_eotf=0;break;
    case 6:d->signal_eotf_param0=1;break;case 7:d->signal_eotf_param1=1;break;
    case 8:d->signal_eotf_param2=1;break;case 9:d->signal_bit_depth=10;break;
    case 10:d->signal_color_space=1;break;case 11:d->signal_chroma_format=1;break;
    case 12:d->signal_full_range_flag=0;break;case 13:h->vdr_bit_depth=10;break;
    case 14:d->ycc_to_rgb_matrix[8].den=0;break;
    case 15:d->rgb_to_lms_matrix[8].den=-1;break;
    case 16:d->ycc_to_rgb_matrix[8]=(AVRational){1,3};break;
    case 17:d->ycc_to_rgb_matrix[8]=(AVRational){32768,8192};break;
    case 18:d->rgb_to_lms_matrix[8]=(AVRational){-32769,16384};break;
    case 19:d->ycc_to_rgb_offset[2]=(AVRational){-1,1<<28};break;
    case 20:d->ycc_to_rgb_offset[2]=(AVRational){16,1};break;
    case 21:target.code_scale=4095;break;case 22:target.pq_policy=99;break;
    case 23:target.ycc[8]=NAN;break;case 24:target.lms[8]=0;break;
    case 25:bytes=sizeof(AVDOVIMetadata)-1;break;case 26:m->color_offset=SIZE_MAX;break;
    case 27:m->color_offset=m->header_offset;break;case 28:m->ext_block_size=1;break;
    case 29:out=(struct yb_colour_config *)(void *)&fixture.mapping;break;
    case 30:out=(struct yb_colour_config *)(void *)&target;break;
    case 31:data=NULL;break;case 32:tp=NULL;break;case 33:out=NULL;break;
    case 34:for(unsigned i=0;i<9;++i) {target.ycc[i]=i%4?0:2;target.lms[i]=i%4?0:.5;}target.offset[0]=.1;target.offset[1]=.2;target.offset[2]=.3;break;
    case 35:target.pq_policy=YB_PQ_REJECT_OUTSIDE_UNIT;break;
    case 36:data=(const unsigned char *)&fixture+1;break;
    case 37:tp=(const struct yb_dovi_colour_target *)(const void *)((const unsigned char *)&target+1);break;
    case 38:out=(struct yb_colour_config *)(void *)((unsigned char *)&output+1);break;
    case 39:bytes=1024u*1024u+1u;break;
    case 40:data=(const void *)(UINTPTR_MAX-_Alignof(AVDOVIMetadata)+1u);break;
    case 41:out=(struct yb_colour_config *)(UINTPTR_MAX-_Alignof(struct yb_colour_config)+1u);break;
    case 42:m->num_ext_blocks=-1;break;
    case 43:m->num_ext_blocks=1;m->ext_block_offset=m->mapping_offset;break;
    case 44:d->ycc_to_rgb_offset[2]=(AVRational){1,3};break;
    }
    /* Snapshot only actual allocations: alias case30 has less destination
     * storage, but adapter must reject without dereferencing the destination. */
    unsigned char before[sizeof(fixture)],target_before[sizeof(target)],output_before[sizeof(output)];
    memcpy(before,&fixture,sizeof(fixture));memcpy(target_before,&target,sizeof(target));memcpy(output_before,&output,sizeof(output));
    int status=yb_dovi_to_colour_config(data,bytes,uncompressed,tp,out);
    int unchanged=memcmp(before,&fixture,sizeof(fixture))==0&&memcmp(target_before,&target,sizeof(target))==0;
    int atomic=memcmp(output_before,&output,sizeof(output))==0&&unchanged;
    printf("{\"schema\":\"yblod.dovi-colour-adapter-synthetic.v1\",\"case\":%ld,\"status\":%d,\"inputs_unchanged\":%s,\"failure_output_untouched\":%s",case_id,status,unchanged?"true":"false",status&&atomic?"true":"false");
    if(!status) {
        const struct yb_colour_parameters *p=&output.parameters;
        printf(",\"source_ycc\":");array(p->source_ycc,9);printf(",\"source_lms\":");array(p->source_lms,9);printf(",\"source_offset\":");array(p->source_offset,3);
        printf(",\"target_ycc\":");array(p->target_ycc,9);printf(",\"target_lms\":");array(p->target_lms,9);printf(",\"target_offset\":");array(p->target_offset,3);
        printf(",\"code_scale\":%d,\"pq_policy\":%d",p->code_scale,p->pq_policy);
        /* Destroy source/target before arithmetic to prove owned config. */
        memset(&fixture,0,sizeof(fixture));memset(&target,0,sizeof(target));
        struct yb_colour_result result;double codes[3]={2048,1024,3072};
        int sample_status=yb_colour_sample(&output,codes,&result);
        printf(",\"source_released_before_arithmetic\":true,\"sample_status\":%d",sample_status);
        if(!sample_status) {printf(",\"source_nonlinear\":");array(result.source_nonlinear,3);printf(",\"common_linear_lms\":");array(result.common_linear_lms,3);printf(",\"codes\":[%u,%u,%u]",result.codes[0],result.codes[1],result.codes[2]);}
    }
    printf("}\n");return 0;
}
