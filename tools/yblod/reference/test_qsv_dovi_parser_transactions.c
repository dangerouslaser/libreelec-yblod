/* SPDX-License-Identifier: GPL-3.0-or-later */
/* User-supplied private HEVC RPU NAL; output contains scalar results only. */
#include "qsv_dovi_context_clone.h"
#include "qsv_dovi_association.h"
#include "libavcodec/h2645_parse.h"
#include "libavcodec/defs.h"
#include "libavutil/mem.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
static void equal_state(const DOVIContext *a, const DOVIContext *b)
{
    assert(a->enable == b->enable && a->logctx == b->logctx);
    assert(!memcmp(&a->cfg, &b->cfg, sizeof(a->cfg)));
    assert(!memcmp(&a->header, &b->header, sizeof(a->header)));
    for (int i = 0; i <= DOVI_MAX_DM_ID; ++i) {
        assert(!!a->vdr[i] == !!b->vdr[i]);
        if (a->vdr[i]) assert(!memcmp(a->vdr[i], b->vdr[i], sizeof(*a->vdr[i])));
    }
    assert(!!a->dm == !!b->dm && !!a->ext_blocks == !!b->ext_blocks);
    if (a->dm) assert(!memcmp(a->dm, b->dm, sizeof(*a->dm)));
    if (a->ext_blocks) assert(!memcmp(a->ext_blocks, b->ext_blocks, sizeof(*a->ext_blocks)));
    assert(!!a->mapping == !!b->mapping && !!a->color == !!b->color);
    for (int i = 0; i <= DOVI_MAX_DM_ID; ++i)
        assert((a->mapping && a->mapping == a->vdr[i]) ==
               (b->mapping && b->mapping == b->vdr[i]));
    assert((a->color && a->color == a->dm) == (b->color && b->color == b->dm));
    assert((a->color == &ff_dovi_color_default) == (b->color == &ff_dovi_color_default));
    if (a->mapping) assert(!memcmp(a->mapping, b->mapping, sizeof(*a->mapping)));
    if (a->color) assert(!memcmp(a->color, b->color, sizeof(*a->color)));
}
static unsigned comparisons, errors, metadata_checks;
static struct qda_table table;
static AVDOVIMetadata *expected[3];
static int expected_size[3];
static uint64_t identities[3];
static unsigned recording, released;
static void snapshot_release(void *p) { ++released; av_free(p); }
static void step(DOVIContext *native, DOVIContext *committed,
                 const uint8_t *rpu, int size)
{
    DOVIContext candidate = {0}, before = {0};
    assert(!qda_context_clone(committed, &candidate));
    assert(!qda_context_clone(committed, &before));
    int rc = rpu ? ff_dovi_rpu_parse(&candidate, rpu, size, 0) : 0;
    equal_state(committed, &before); /* Retry/cancel cannot alter live state. */
    int nr = rpu ? ff_dovi_rpu_parse(native, rpu, size, 0) : 0;
    assert(rc == nr); if (rc < 0) ++errors;
    equal_state(native, &candidate);
    AVDOVIMetadata *a = NULL, *b = NULL;
    int as = ff_dovi_get_metadata(native, &a), bs = ff_dovi_get_metadata(&candidate, &b);
    assert(as == bs && as >= 0);
    if (as) assert(!memcmp(a, b, as));
    if (recording < 3) {
        expected[recording] = a; expected_size[recording] = as;
        assert(qda_prepare(&table, recording, 1, b, &identities[recording]));
        assert(qda_commit(&table, identities[recording]));
        ++recording;
    } else { av_free(a); av_free(b); }
    ++metadata_checks;
    ff_dovi_ctx_replace(committed, &candidate);
    ff_dovi_ctx_unref(&candidate); ff_dovi_ctx_unref(&before);
    equal_state(native, committed); ++comparisons;
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    FILE *f = fopen(argv[1], "rb"); assert(f);
    assert(!fseek(f, 0, SEEK_END)); long size = ftell(f);
    assert(size > 0 && size <= 65536 && !fseek(f, 0, SEEK_SET));
    uint8_t *data = av_mallocz(size + 4 + AV_INPUT_BUFFER_PADDING_SIZE); assert(data);
    data[3] = 1;
    assert(fread(data + 4, 1, size, f) == (size_t)size); fclose(f);
    H2645Packet packet = {0};
    assert(!ff_h2645_packet_split(&packet, data, size + 4, NULL, 0, AV_CODEC_ID_HEVC, 0));
    H2645NAL *nal = NULL;
    for (int i = 0; i < packet.nb_nals; ++i)
        if (packet.nals[i].type == 62) { assert(!nal); nal = &packet.nals[i]; }
    assert(nal && nal->size > 7 && !nal->nuh_layer_id && !nal->temporal_id);
    DOVIContext native = {0}, committed = {0};
    native.cfg.dv_profile = committed.cfg.dv_profile = 7;
    table.release = snapshot_release;
    const uint8_t *rpu = nal->data + 2; int bytes = nal->size - 2;
    step(&native, &committed, rpu, bytes);
    assert(!errors && native.mapping && native.color);
    step(&native, &committed, NULL, 0);
    step(&native, &committed, rpu, bytes);
    /* Live parser writes and flushes cannot alter previously owned snapshots. */
    ff_dovi_ctx_flush(&native); ff_dovi_ctx_flush(&committed);
    const unsigned order[] = {2, 0, 1};
    for (unsigned i = 0; i < 3; ++i) {
        unsigned index = order[i]; struct qda_entry entry = {0};
        assert(qda_take(&table, identities[index], &entry));
        assert(entry.pts == (int64_t)index);
        assert(expected_size[index] > 0 && entry.snapshot);
        assert(!memcmp(expected[index], entry.snapshot, expected_size[index]));
        snapshot_release(entry.snapshot); av_free(expected[index]);
        assert(!qda_take(&table, identities[index], &entry));
    }
    assert(released == 3 && !table.count);
    /* Every truncation is interpreted by the real native parser, not guessed. */
    for (int n = 0; n < bytes; ++n) {
        ff_dovi_ctx_flush(&native); ff_dovi_ctx_flush(&committed);
        step(&native, &committed, rpu, bytes);
        step(&native, &committed, rpu, n);
        step(&native, &committed, NULL, 0);
    }
    ff_dovi_ctx_unref(&native); ff_dovi_ctx_unref(&committed);
    ff_h2645_packet_uninit(&packet); av_free(data);
    printf("{\"schema\":\"yblod.qsv-dovi-parser-transactions.v1\",\"comparisons\":%u,"
           "\"metadata_checks\":%u,\"parse_error_cases\":%u,\"all_passed\":true,"
           "\"previous_rpu_reference_qualified\":false,\"reordered_association_qualified\":true,"
           "\"immutable_snapshots_checked\":3,\"snapshot_releases\":3}\n",
           comparisons, metadata_checks, errors);
    return 0;
}
