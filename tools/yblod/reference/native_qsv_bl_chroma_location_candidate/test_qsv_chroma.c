#include "qsv_dovi.h"
#undef NDEBUG
#include <assert.h>
#include <stdio.h>

int main(void)
{
    QSVDOVIContext s = {0};
    HEVCPPS pps = {0};
    HEVCSPS sps = {0};
    enum AVChromaLocation location;
    /* first_slice=1, PPS ue(0)=1, then a distinct rbsp_stop_one_bit=1. */
    uint8_t data[] = {0, 0, 1, 2, 1, 0xe0};
    AVPacket packet = {.data=data, .size=sizeof(data), .pts=100, .duration=41};
    uint64_t first, second;
    AVFrame *frame = av_frame_alloc();
    assert(frame);
    s.chroma_enabled = 1;
    s.chroma_ps.pps_list[0] = &pps;
    pps.sps = &sps;
    sps.chroma_format_idc = 1;
    assert(!qsv_dovi_prepare(&s, &packet, 0));
    assert(s.pending.chroma_location == AVCHROMA_LOC_LEFT);
    first = s.pending.token;
    assert(!qsv_dovi_consume(&s, packet.size));
    sps.vui.common.chroma_loc_info_present_flag = 1;
    sps.vui.common.chroma_sample_loc_type_top_field = 2;
    packet.pts = 200;
    assert(!qsv_dovi_prepare(&s, &packet, 0));
    assert(s.pending.chroma_location == AVCHROMA_LOC_TOPLEFT);
    second = s.pending.token;
    assert(!qsv_dovi_consume(&s, packet.size));
    assert(!qsv_dovi_output(&s, second, frame));
    assert(frame->chroma_location == AVCHROMA_LOC_TOPLEFT && frame->pts == 200);
    assert(!qsv_dovi_output(&s, first, frame));
    assert(frame->chroma_location == AVCHROMA_LOC_LEFT && frame->pts == 100);
    for (unsigned i=0; i<6; i++) {
        sps.vui.common.chroma_sample_loc_type_top_field = i;
        assert(!qsv_dovi_picture_chroma(&s, &location));
        assert(location == (enum AVChromaLocation)(i+1));
    }
    sps.vui.common.chroma_sample_loc_type_top_field = 6;
    assert(qsv_dovi_picture_chroma(&s, &location) == AVERROR_INVALIDDATA);
    sps.vui.common.chroma_sample_loc_type_top_field = 0;
    sps.chroma_format_idc = 2;
    assert(qsv_dovi_picture_chroma(&s, &location) == AVERROR_INVALIDDATA);
    sps.chroma_format_idc = 1;
    s.chroma_ps.pps_list[0] = NULL;
    assert(qsv_dovi_picture_chroma(&s, &location) == AVERROR_INVALIDDATA);
    qsv_dovi_flush(&s);
    assert(!s.count && !s.pending.token);
    qsv_dovi_uninit(&s);
    av_frame_free(&frame);
    puts("PASS: HEVC default, six explicit locations, reordered picture tokens, invalid location/format/PPS, flush");
    return 0;
}
