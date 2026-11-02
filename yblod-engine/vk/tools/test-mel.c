#include "decode.h"
#include <assert.h>
#include <libavutil/mem.h>
#include <stdio.h>
int main(void) {
    size_t size;
    AVDOVIMetadata *md=av_dovi_metadata_alloc(&size);
    assert(md);
    AVDOVIRpuDataHeader *h=av_dovi_get_header(md);
    AVDOVIDataMapping *m=av_dovi_get_mapping(md);
    h->bl_bit_depth=10;h->el_bit_depth=10;h->vdr_bit_depth=12;
    h->coef_log2_denom=23;m->nlq_method_idc=AV_DOVI_NLQ_LINEAR_DZ;
    for(int c=0;c<3;c++)m->nlq[c].vdr_in_max=UINT64_C(1)<<23;
    assert(dv_decoder_metadata_no_residual(md));
    for(int c=0;c<3;c++) {
        m->nlq[c].nlq_offset=1;assert(!dv_decoder_metadata_no_residual(md));m->nlq[c].nlq_offset=0;
        m->nlq[c].vdr_in_max--;assert(!dv_decoder_metadata_no_residual(md));m->nlq[c].vdr_in_max++;
        m->nlq[c].linear_deadzone_slope=1;assert(!dv_decoder_metadata_no_residual(md));m->nlq[c].linear_deadzone_slope=0;
        m->nlq[c].linear_deadzone_threshold=1;assert(!dv_decoder_metadata_no_residual(md));m->nlq[c].linear_deadzone_threshold=0;
    }
    for(int denom=0;denom<=32;denom+=32) {
        h->coef_log2_denom=denom;
        for(int c=0;c<3;c++)m->nlq[c].vdr_in_max=UINT64_C(1)<<denom;
        assert(dv_decoder_metadata_no_residual(md));
    }
    h->coef_log2_denom=23;
    for(int c=0;c<3;c++)m->nlq[c].vdr_in_max=UINT64_C(1)<<23;
    h->coef_data_type=1;assert(!dv_decoder_metadata_no_residual(md));h->coef_data_type=0;
    h->coef_log2_denom=33;assert(!dv_decoder_metadata_no_residual(md));h->coef_log2_denom=23;
    h->bl_bit_depth=8;assert(!dv_decoder_metadata_no_residual(md));h->bl_bit_depth=10;
    h->el_bit_depth=8;assert(!dv_decoder_metadata_no_residual(md));h->el_bit_depth=10;
    h->vdr_bit_depth=10;assert(!dv_decoder_metadata_no_residual(md));h->vdr_bit_depth=12;
    m->nlq_method_idc=AV_DOVI_NLQ_NONE;assert(!dv_decoder_metadata_no_residual(md));
    h->disable_residual_flag=1;assert(dv_decoder_metadata_no_residual(md));
    av_free(md);puts("MEL classification: all channels, FEL deviations, invalid formats and disabled residual PASS");
}
