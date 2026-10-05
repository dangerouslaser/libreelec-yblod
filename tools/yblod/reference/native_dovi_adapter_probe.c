/* Public synthetic fixtures, allocated by the REAL matching FFmpeg library.
 * No raw RPU parsing, media, decoder, GPU, display or playback operations.
 */
#include "native_dovi_adapter.h"
#include <libavutil/dovi_meta.h>
#include <libavutil/mem.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *const cases[] = {
    "baseline", "negative-coefficient", "cumulative-pivots", "mmr1", "mmr2", "mmr3",
    "poisoned-inactive", "disabled-poisoned-nlq", "disabled-denominator13", "depth8", "spatial-flags", "empty-ext-at-end",
    "float-coefficients", "explicit-chroma-filter", "invalid-chroma-flag", "unknown-header",
    "unsupported-depth", "multiple-partitions", "unknown-method", "mmr-luma", "bad-nlq-method",
    "wrong-nlq-pivots", "late-offset-overflow", "late-coefficient-overflow", "duplicate-pivots",
    "truncated", "offset-wrap", "overlap-regions", "overlap-prefix", "overlap-ext",
    "bad-ext-stride", "negative-ext-count", "output-alias", "address-wrap",
    "null-input", "null-output", "misaligned-input", "misaligned-output", "wrapping-output", "oversized-bytes"
};

static int selected(const char *name, const char *expected) { return strcmp(name, expected) == 0; }

static void populate(AVDOVIMetadata *metadata, const char *name)
{
    AVDOVIRpuDataHeader *h = av_dovi_get_header(metadata);
    AVDOVIDataMapping *m = av_dovi_get_mapping(metadata);
    unsigned depth = selected(name, "depth8") ? 8U : 10U;
    unsigned maximum = (1U<<depth)-1U;
    h->rpu_type=2; h->rpu_format=18; h->vdr_rpu_profile=1;
    h->coef_data_type=0; h->coef_log2_denom=23; h->vdr_rpu_normalized_idc=1;
    h->bl_bit_depth=(uint8_t)depth; h->el_bit_depth=(uint8_t)depth; h->vdr_bit_depth=12;
    m->num_x_partitions=1; m->num_y_partitions=1;
    m->nlq_method_idc=AV_DOVI_NLQ_LINEAR_DZ;
    m->nlq_pivots[0]=0; m->nlq_pivots[1]=(uint16_t)maximum;
    for (unsigned c=0; c<3U; ++c) {
        AVDOVIReshapingCurve *curve=&m->curves[c];
        if (selected(name, "poisoned-inactive")) {
            memset(curve, 0x5a, sizeof(*curve));
        }
        curve->num_pivots=2; curve->pivots[0]=0; curve->pivots[1]=(uint16_t)maximum;
        curve->mapping_idc[0]=AV_DOVI_MAPPING_POLYNOMIAL;
        curve->poly_order[0]=1; curve->poly_coef[0][0]=0; curve->poly_coef[0][1]=INT64_C(1)<<23;
        m->nlq[c].nlq_offset=(uint16_t)(1U<<(depth-1U));
        m->nlq[c].linear_deadzone_slope=2048; m->nlq[c].linear_deadzone_threshold=0;
        m->nlq[c].vdr_in_max=1025;
        if (selected(name, "negative-coefficient")) curve->poly_coef[0][0]=-8185;
        if (selected(name, "cumulative-pivots")) {
            curve->num_pivots=3; curve->pivots[1]=400; curve->pivots[2]=1023;
            curve->mapping_idc[1]=AV_DOVI_MAPPING_POLYNOMIAL;
            curve->poly_order[1]=2;
            curve->poly_coef[1][0]=7; curve->poly_coef[1][1]=INT64_C(1)<<22;
            curve->poly_coef[1][2]=INT64_C(1)<<21;
        }
        if (c != 0U && (selected(name, "mmr1") || selected(name, "mmr2") || selected(name, "mmr3"))) {
            unsigned order=(unsigned)(name[3]-'0');
            /* Poison inactive polynomial slots and unselected higher MMR rows. */
            memset(curve->poly_coef, 0x5a, sizeof(curve->poly_coef));
            memset(curve->mmr_coef, 0x5a, sizeof(curve->mmr_coef));
            curve->mapping_idc[0]=AV_DOVI_MAPPING_MMR;
            curve->mmr_order[0]=(uint8_t)order; curve->mmr_constant[0]=INT64_C(1)<<21;
            for (unsigned row=0; row<order; ++row) {
                for (unsigned term=0; term<7U; ++term) {
                    curve->mmr_coef[0][row][term]=(int64_t)(term+1U)*8192*(row%2U != 0U ? -1 : 1);
                }
            }
        }
    }
    if (selected(name, "disabled-poisoned-nlq") || selected(name, "disabled-denominator13")) {
        h->disable_residual_flag=1;
        m->nlq_method_idc=(enum AVDOVINLQMethod)99;
        memset(m->nlq, 0xff, sizeof(m->nlq)); memset(m->nlq_pivots, 0xff, sizeof(m->nlq_pivots));
    }
    if (selected(name, "disabled-denominator13")) {
        h->coef_log2_denom=13;
        for (unsigned c=0;c<3U;++c) m->curves[c].poly_coef[0][1]=INT64_C(1)<<13;
    }
    if (selected(name, "spatial-flags")) {
        h->spatial_resampling_filter_flag=1; h->el_spatial_resampling_filter_flag=1;
    }
    if (selected(name, "float-coefficients")) h->coef_data_type=1;
    if (selected(name, "explicit-chroma-filter")) h->chroma_resampling_explicit_filter_flag=1;
    if (selected(name, "invalid-chroma-flag")) h->chroma_resampling_explicit_filter_flag=2;
    if (selected(name, "unknown-header")) h->ext_mapping_idc_5_7=1;
    if (selected(name, "unsupported-depth")) h->el_bit_depth=12;
    if (selected(name, "multiple-partitions")) m->num_x_partitions=2;
    if (selected(name, "unknown-method")) m->curves[2].mapping_idc[0]=(enum AVDOVIMappingMethod)2;
    if (selected(name, "mmr-luma")) {
        m->curves[0].mapping_idc[0]=AV_DOVI_MAPPING_MMR; m->curves[0].mmr_order[0]=1;
    }
    if (selected(name, "bad-nlq-method")) m->nlq_method_idc=(enum AVDOVINLQMethod)1;
    if (selected(name, "wrong-nlq-pivots")) m->nlq_pivots[0]=1;
    if (selected(name, "late-offset-overflow")) m->nlq[2].nlq_offset=1024;
    if (selected(name, "late-coefficient-overflow")) m->curves[2].poly_coef[0][1]=INT64_MAX;
    if (selected(name, "duplicate-pivots")) m->curves[2].pivots[1]=0;
}

static int canonical(const yb_dovi_integer_instructions *out)
{
    for (unsigned c=0; c<3U; ++c) {
        const struct yb_component_mapping *m=&out->mapping.components[c];
        for (unsigned i=(unsigned)m->pivot_count; i<YB_MAX_PIVOTS; ++i) if (m->pivots[i]) return 0;
        for (unsigned i=0; i<YB_MAX_SEGMENTS; ++i) {
            const struct yb_segment *s=&m->segments[i];
            if (i+1U>=(unsigned)m->pivot_count) {
                struct yb_segment zero; memset(&zero,0,sizeof(zero));
                if (memcmp(s,&zero,sizeof(zero))) return 0;
            } else {
                if (s->method == YB_POLYNOMIAL && s->constant != 0) return 0;
                for (unsigned row=0; row<3U; ++row) for (unsigned term=0; term<7U; ++term) {
                    int active=s->method == YB_POLYNOMIAL ? row==0U && term<=(unsigned)s->order : row<(unsigned)s->order;
                    if (!active && s->coefficients[row][term]) return 0;
                }
            }
        }
    }
    if (!out->residual_enabled) {
        struct yb_nlq_config zero[3]; memset(zero,0,sizeof(zero));
        if (memcmp(out->nlq,zero,sizeof(zero))) return 0;
    }
    return 1;
}

static void emit_config(const yb_dovi_integer_instructions *out)
{
    printf(",\"configuration\":{\"bit_depth\":%d,\"denominator\":%d,\"output_depth\":%d,\"enabled\":%s,"
           "\"spatial_flags\":[%u,%u],\"mappings\":[",out->mapping.bit_depth,out->mapping.denominator,
           out->output_depth,out->residual_enabled ? "true":"false",out->spatial_resampling_filter_flag,
           out->el_spatial_resampling_filter_flag);
    for (unsigned c=0;c<3U;++c) {
        const struct yb_component_mapping *mapping=&out->mapping.components[c];
        printf("%s{\"pivots\":[",c ? ",":"");
        for (int i=0;i<mapping->pivot_count;++i) printf("%s%d",i ? ",":"",mapping->pivots[i]);
        printf("],\"segments\":[");
        for (int i=0;i<mapping->pivot_count-1;++i) {
            const struct yb_segment *s=&mapping->segments[i];
            printf("%s{\"method\":\"%s\",",i ? ",":"",s->method==YB_POLYNOMIAL ? "polynomial":"mmr");
            if (s->method==YB_MMR) printf("\"constant\":%"PRId64",",s->constant);
            printf("\"coefficients\":[");
            if (s->method==YB_POLYNOMIAL) {
                for (int k=0;k<=s->order;++k) printf("%s%"PRId64,k ? ",":"",s->coefficients[0][k]);
            } else {
                for (int row=0;row<s->order;++row) {
                    printf("%s[",row ? ",":"");
                    for (unsigned k=0;k<7U;++k) printf("%s%"PRId64,k ? ",":"",s->coefficients[row][k]);
                    printf("]");
                }
            }
            printf("]}");
        }
        printf("]}");
    }
    printf("],\"nlq\":[");
    for (unsigned c=0;c<3U;++c) {
        const struct yb_nlq_config *n=&out->nlq[c];
        printf("%s{\"bit_depth\":%d,\"denominator\":%d,\"offset\":%d,\"slope\":%"PRIu64","
               "\"threshold\":%"PRIu64",\"maximum\":%"PRIu64"}",c ? ",":"",n->bit_depth,n->denominator,
               n->offset,n->slope,n->threshold,n->maximum);
    }
    printf("]}");
}

int main(int argc,char **argv)
{
    int known=0;
    if (argc!=2) return 2;
    for (unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);++i) if (selected(argv[1],cases[i])) known=1;
    if (!known) return 2;
    const char *name=argv[1];
    size_t bytes=0;
    AVDOVIMetadata *metadata=av_dovi_metadata_alloc(&bytes);
    if (!metadata) return 3;
    populate(metadata,name);
    size_t passed_bytes=bytes;
    if (selected(name,"truncated")) passed_bytes=sizeof(*metadata)-1U;
    if (selected(name,"oversized-bytes")) passed_bytes=1024U*1024U+1U;
    if (selected(name,"offset-wrap")) metadata->mapping_offset=SIZE_MAX;
    if (selected(name,"overlap-regions")) metadata->mapping_offset=metadata->header_offset;
    if (selected(name,"overlap-prefix")) metadata->header_offset=0;
    if (selected(name,"overlap-ext")) { metadata->num_ext_blocks=1;metadata->ext_block_offset=metadata->mapping_offset; }
    if (selected(name,"bad-ext-stride")) metadata->ext_block_size=sizeof(AVDOVIDmData)-1U;
    if (selected(name,"negative-ext-count")) metadata->num_ext_blocks=-1;
    if (selected(name,"empty-ext-at-end")) metadata->ext_block_offset=bytes;
    unsigned char *original=malloc(bytes);
    if (!original) { av_free(metadata);return 3; }
    memcpy(original,metadata,bytes);
    yb_dovi_integer_instructions output,before;
    memset(&output,0xa5,sizeof(output));memcpy(&before,&output,sizeof(output));
    const void *input=selected(name,"address-wrap") ? (const void *)(uintptr_t)(UINTPTR_MAX-7U):metadata;
    yb_dovi_integer_instructions *destination=selected(name,"output-alias") ? (void *)metadata:&output;
    if (selected(name,"null-input")) input=NULL;
    if (selected(name,"null-output")) destination=NULL;
    if (selected(name,"misaligned-input")) input=(const unsigned char *)metadata+1;
    if (selected(name,"misaligned-output")) destination=(void *)((unsigned char *)&output+1);
    if (selected(name,"wrapping-output")) destination=(void *)(uintptr_t)(UINTPTR_MAX-7U);
    int status=yb_dovi_to_integer_configs(input,passed_bytes,destination);
    int unchanged=memcmp(original,metadata,bytes)==0;
    int untouched=memcmp(&before,&output,sizeof(output))==0;
    printf("{\"schema\":\"yblod.native-dovi-adapter-case.v1\",\"case\":\"%s\",\"status\":%d,"
           "\"input_unchanged\":%s,\"failure_output_untouched\":%s,\"abi_version\":%u,\"instructions_bytes\":%"PRIu64,
           name,status,unchanged ? "true":"false",status && untouched ? "true":"false",
           yb_dovi_adapter_abi_version(),yb_dovi_adapter_sizeof_instructions());
    if (status==0) {
        int64_t samples[3]={128,64,32};
        if (output.mapping.bit_depth==10) for (unsigned c=0;c<3U;++c) samples[c]*=4;
        int64_t el=(INT64_C(1)<<(output.mapping.bit_depth-1))-2;
        printf(",\"canonical_unused\":%s",canonical(&output) ? "true":"false");
        emit_config(&output);
        /* Prove ownership after import: destroy and release the source object. */
        memset(metadata,0x33,bytes);av_free(metadata);metadata=NULL;
        printf(",\"source_released_before_arithmetic\":true,\"sample_triplet\":[%"PRId64",%"PRId64",%"PRId64"],"
               "\"el_sample\":%"PRId64",\"stages\":[",samples[0],samples[1],samples[2],el);
        for (int c=0;c<3;++c) {
            uint16_t mapped=0,reconstructed=0;int64_t residual=0;
            if (yb_map_sample(&output.mapping,c,samples,&mapped) != YB_OK ||
                (output.residual_enabled && yb_nlq(&output.nlq[c],el,&residual) != YB_OK) ||
                yb_compose_residual(mapped,residual,output.output_depth,&reconstructed) != YB_OK) {
                free(original);return 4;
            }
            printf("%s[%u,%"PRId64",%"PRId64",%u]",c ? ",":"",(unsigned)mapped,residual,(int64_t)mapped+residual,(unsigned)reconstructed);
        }
        printf("]");
    }
    printf("}\n");
    free(original);av_free(metadata);
    return unchanged && (!status || untouched) ? 0:5;
}
