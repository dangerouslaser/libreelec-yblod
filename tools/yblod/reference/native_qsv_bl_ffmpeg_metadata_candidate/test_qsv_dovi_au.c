/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "qsv_dovi.h"
#include "libavcodec/defs.h"
#include <assert.h>
#include <stdio.h>

static unsigned admissions, transactions, errors, comparisons;
static const uint8_t first[] = {0,0,1,2,1,0xc0};
static const uint8_t continuation[] = {0,0,1,2,1,0x40};
static const uint8_t el[] = {0,0,1,126,1,0x80};
static const uint8_t eos[] = {0,0,1,72,1,0x80};

static AVPacket packet(const uint8_t *data, int size, int64_t pts)
{
    return (AVPacket){.data = (uint8_t *)data, .size = size, .pts = pts, .duration = 41708};
}
static void same(const DOVIContext *a, const DOVIContext *b)
{
    assert(a->enable == b->enable && a->logctx == b->logctx);
    assert(!memcmp(&a->cfg, &b->cfg, sizeof(a->cfg)));
    assert(!memcmp(&a->header, &b->header, sizeof(a->header)));
    for (int i = 0; i <= DOVI_MAX_DM_ID; i++) {
        assert(!!a->vdr[i] == !!b->vdr[i]);
        if (a->vdr[i]) assert(!memcmp(a->vdr[i], b->vdr[i], sizeof(*a->vdr[i])));
        assert((a->mapping == a->vdr[i] && a->mapping) ==
               (b->mapping == b->vdr[i] && b->mapping));
    }
    assert(!!a->dm == !!b->dm && !!a->ext_blocks == !!b->ext_blocks);
    if (a->dm) assert(!memcmp(a->dm,b->dm,sizeof(*a->dm)));
    if (a->ext_blocks) assert(!memcmp(a->ext_blocks,b->ext_blocks,sizeof(*a->ext_blocks)));
    assert(!!a->mapping == !!b->mapping && !!a->color == !!b->color);
    assert((a->color == &ff_dovi_color_default) == (b->color == &ff_dovi_color_default));
    assert((a->color == a->dm && a->color) == (b->color == b->dm && b->color));
    ++comparisons;
}
static void admit(QSVDOVIContext *s, const uint8_t *bytes, int size, int success)
{
    AVPacket pkt = packet(bytes, size, 0); H2645NAL *rpu;
    int ret = qsv_dovi_admit(s, &pkt, &rpu);
    if ((ret == 0) != success) {
        fprintf(stderr, "admission_case=%u return=%d expected_success=%d\n", admissions, ret, success);
        fprintf(stderr, "admission_shape_raw=%d parsed=%d\n", qsv_dovi_annexb_headers(bytes,size), s->nals.nb_nals);
        for (int i=0;i<s->nals.nb_nals;i++)
            fprintf(stderr,"admission_shape_nal=%d type=%d layer=%d temporal=%d sizebits=%d\n",
                    i,s->nals.nals[i].type,s->nals.nals[i].nuh_layer_id,
                    s->nals.nals[i].temporal_id,s->nals.nals[i].size_bits);
        abort();
    }
    ++admissions;
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    FILE *f = fopen(argv[1], "rb"); assert(f);
    assert(!fseek(f,0,SEEK_END)); long bytes = ftell(f);
    assert(bytes > 7 && bytes <= 65536 && !fseek(f,0,SEEK_SET));
    uint8_t *au = av_mallocz(bytes + 32 + AV_INPUT_BUFFER_PADDING_SIZE); assert(au);
    memcpy(au,first,sizeof(first)); memcpy(au + sizeof(first),el,sizeof(el));
    int prefix = sizeof(first) + sizeof(el);
    au[prefix + 2] = 1;
    assert(fread(au + prefix + 3,1,bytes,f) == (size_t)bytes); fclose(f);
    int size = prefix + 3 + bytes;
    QSVDOVIContext s = {0}; DOVIContext native = {0}, before = {0};
    s.active.cfg.dv_profile = native.cfg.dv_profile = 7;
    AVPacket empty_metadata=packet(first,sizeof(first),-3);
    assert(!qsv_dovi_prepare(&s,&empty_metadata,0));
    assert(!qsv_dovi_consume(&s,empty_metadata.size));
    AVFrame *stale=av_frame_alloc(); assert(stale);
    assert(av_frame_new_side_data(stale,AV_FRAME_DATA_DOVI_METADATA,4));
    assert(av_frame_new_side_data(stale,AV_FRAME_DATA_DOVI_RPU_BUFFER,4));
    assert(!qsv_dovi_output(&s,s.next,stale) && stale->pts==-3);
    assert(!av_frame_get_side_data(stale,AV_FRAME_DATA_DOVI_METADATA) &&
           !av_frame_get_side_data(stale,AV_FRAME_DATA_DOVI_RPU_BUFFER));
    av_frame_free(&stale); ++transactions;
    admit(&s,first,sizeof(first),1);
    uint8_t multi[sizeof(first)*2 + sizeof(continuation)] = {0};
    memcpy(multi,first,sizeof(first)); memcpy(multi+sizeof(first),continuation,sizeof(continuation));
    admit(&s,multi,sizeof(first)+sizeof(continuation),1);
    memcpy(multi+sizeof(first),first,sizeof(first));
    admit(&s,multi,sizeof(first)*2,0);
    admit(&s,continuation,sizeof(continuation),0);
    admit(&s,au,size,1); admit(&s,au+prefix,3+bytes,0);
    uint8_t malformed[sizeof(first)]; memcpy(malformed,first,sizeof(first));
    malformed[3] |= 0x80; admit(&s,malformed,sizeof(malformed),0);
    memcpy(malformed,first,sizeof(first)); malformed[4]=0; admit(&s,malformed,sizeof(malformed),0);
    memcpy(malformed,first,sizeof(first)); malformed[4]=9; admit(&s,malformed,sizeof(malformed),0);
    uint8_t trailer[sizeof(first)*2 + sizeof(eos)];
    memcpy(trailer,first,sizeof(first)); memcpy(trailer+sizeof(first),eos,sizeof(eos));
    memcpy(trailer+sizeof(first)+sizeof(eos),continuation,sizeof(continuation));
    admit(&s,trailer,sizeof(trailer),0);
    uint64_t token[3]; AVDOVIMetadata *expected[3] = {0}; int expected_size[3];
    const int64_t source_pts[]={-17,AV_NOPTS_VALUE,-17};
    for (int i = 0; i < 3; i++) {
        AVPacket pkt = packet(i == 1 ? first : au,i == 1 ? (int)sizeof(first) : size,
                              source_pts[i]);
        assert(!qsv_dovi_clone(&s.active,&before));
        assert(!qsv_dovi_prepare(&s,&pkt,0)); token[i]=s.pending.token;
        same(&s.active,&before);
        assert(!qsv_dovi_prepare(&s,&pkt,0)); /* no reparse on zero-consume retry */
        assert(!qsv_dovi_consume(&s,2)); same(&s.active,&before);
        pkt.data += 2; pkt.size -= 2;
        assert(!qsv_dovi_prepare(&s,&pkt,0) && s.pending.token == token[i]);
        assert(!qsv_dovi_consume(&s,pkt.size));
        H2645NAL *rpu=NULL;
        if (i != 1) {
            AVPacket whole=packet(au,size,0);
            assert(!qsv_dovi_admit(&s,&whole,&rpu) && rpu);
            assert(!ff_dovi_rpu_parse(&native,rpu->data+2,rpu->size-2,0));
        }
        same(&native,&s.active);
        expected_size[i]=ff_dovi_get_metadata(&native,&expected[i]); assert(expected_size[i]>0);
        ff_dovi_ctx_unref(&before); ++transactions;
    }
    AVPacket allocation_packet=packet(au,size,0);
    assert(!qsv_dovi_clone(&s.active,&before)); uint64_t prior_next=s.next;
    av_max_alloc(1);
    assert(qsv_dovi_prepare(&s,&allocation_packet,0)==AVERROR(ENOMEM));
    av_max_alloc(SIZE_MAX);
    assert(!s.pending.token && s.next==prior_next); same(&s.active,&before); ff_dovi_ctx_unref(&before);
    AVFrame *allocation_frame=av_frame_alloc(); assert(allocation_frame); allocation_frame->pts=99;
    av_max_alloc(1);
    assert(qsv_dovi_output(&s,token[2],allocation_frame)==AVERROR(ENOMEM));
    av_max_alloc(SIZE_MAX);
    assert(s.count==3 && allocation_frame->pts==99);
    av_frame_free(&allocation_frame);
    const unsigned order[]={2,0,1};
    for (unsigned i=0;i<3;i++) {
        unsigned n=order[i]; AVFrame *frame=av_frame_alloc(); assert(frame);
        assert(!qsv_dovi_output(&s,token[n],frame));
        AVFrameSideData *sd=av_frame_get_side_data(frame,AV_FRAME_DATA_DOVI_METADATA);
        assert(sd && sd->size==(size_t)expected_size[n] && !memcmp(sd->data,expected[n],sd->size));
        assert(frame->pts==source_pts[n] && frame->duration==41708);
        assert(!!av_frame_get_side_data(frame,AV_FRAME_DATA_DOVI_RPU_BUFFER)==(n!=1));
        av_free(expected[n]); av_frame_free(&frame);
    }
    /* Real invalid-RPU behavior, including native mutations on parse failure. */
    for (int length=1;length<bytes-2;length++) {
        qsv_dovi_flush(&s); ff_dovi_ctx_flush(&native);
        AVPacket pkt=packet(au,size,4); H2645NAL *rpu=NULL;
        assert(!qsv_dovi_prepare(&s,&pkt,0)); assert(!qsv_dovi_consume(&s,pkt.size));
        assert(!qsv_dovi_admit(&s,&pkt,&rpu) && rpu);
        assert(!ff_dovi_rpu_parse(&native,rpu->data+2,rpu->size-2,0));
        AVFrame *frame=av_frame_alloc(); assert(frame);
        assert(!qsv_dovi_output(&s,s.next,frame)); av_frame_unref(frame);
        AVPacket truncated=packet(au,prefix+3+2+length,5);
        if (!qsv_dovi_prepare(&s,&truncated,0)) {
            int result=ff_dovi_rpu_parse(&native,rpu->data+2,length,0);
            if (result<0) ++errors;
            assert(!qsv_dovi_consume(&s,truncated.size)); same(&native,&s.active);
            AVDOVIMetadata *snapshot=NULL; int n=ff_dovi_get_metadata(&native,&snapshot);
            assert(n>=0 && !qsv_dovi_output(&s,s.next,frame));
            AVFrameSideData *sd=av_frame_get_side_data(frame,AV_FRAME_DATA_DOVI_METADATA);
            assert(n ? sd && sd->size==(size_t)n && !memcmp(sd->data,snapshot,n) : !sd);
            av_free(snapshot); ++transactions;
        }
        av_frame_free(&frame);
    }
    qsv_dovi_flush(&s); uint64_t previous=s.next;
    AVPacket pkt=packet(first,sizeof(first),9);
    assert(!qsv_dovi_prepare(&s,&pkt,0) && s.pending.token>previous);
    AVFrame *frame=av_frame_alloc(); assert(frame);
    assert(qsv_dovi_output(&s,s.pending.token,frame)==AVERROR_INVALIDDATA && s.failed);
    qsv_dovi_flush(&s); av_frame_free(&frame);
    for (unsigned i=0;i<QSV_DOVI_MAX;i++) {
        assert(!qsv_dovi_prepare(&s,&pkt,0)); assert(!qsv_dovi_consume(&s,pkt.size));
    }
    assert(qsv_dovi_prepare(&s,&pkt,0)==AVERROR(ENOSPC) && !s.pending.token);
    qsv_dovi_flush(&s); s.next=INT64_MAX-1;
    assert(!qsv_dovi_prepare(&s,&pkt,0) && s.pending.token==INT64_MAX);
    assert(!qsv_dovi_consume(&s,pkt.size));
    assert(qsv_dovi_prepare(&s,&pkt,0)==AVERROR(ENOSPC));
    qsv_dovi_uninit(&s); ff_dovi_ctx_unref(&native); av_free(au);
    printf("{\"schema\":\"yblod.qsv-dovi-au-transactions.v1\",\"admission_checks\":%u,"
           "\"transactions\":%u,\"state_comparisons\":%u,\"parse_error_cases\":%u,"
           "\"reordered_snapshots\":3,\"all_passed\":true,\"hardware_qualified\":false}\n",
           admissions,transactions,comparisons,errors);
    return 0;
}
