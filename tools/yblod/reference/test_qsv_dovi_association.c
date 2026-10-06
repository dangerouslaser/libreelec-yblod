/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "qsv_dovi_association.h"
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
static unsigned released;
static void drop(void *p) { ++released; free(p); }
static void *snapshot(unsigned value)
{
    unsigned *p = malloc(sizeof(*p));
    assert(p); *p = value; return p;
}
int main(void)
{
    struct qda_table t = {.release = drop};
    struct qda_entry out = {.token = 999};
    uint64_t first, second, retry = 999;
    assert(qda_prepare(&t, INT64_MIN + 1, 41708, snapshot(1), &first));
    assert(t.count == 0 && t.next == 0);
    void *rejected = snapshot(99);
    assert(!qda_prepare(&t, 0, 1, rejected, &retry) && retry == 999);
    assert(released == 0); /* Failed prepare leaves ownership with caller. */
    drop(rejected); assert(released == 1);
    assert(!qda_take(&t, first, &out) && out.token == 999);
    assert(!qda_commit(&t, first + 1));
    assert(t.prepared.token == first); /* EAGAIN changes nothing. */
    assert(qda_commit(&t, first));
    assert(!qda_commit(&t, first));
    assert(qda_prepare(&t, INT64_MAX, 41709, snapshot(2), &second));
    assert(qda_commit(&t, second));
    assert(qda_take(&t, second, &out) && *(unsigned *)out.snapshot == 2);
    assert(out.pts == INT64_MAX && out.duration == 41709); drop(out.snapshot);
    assert(qda_take(&t, first, &out) && *(unsigned *)out.snapshot == 1);
    assert(out.pts == INT64_MIN + 1 && out.duration == 41708); drop(out.snapshot);
    out.token = 999;
    assert(!qda_take(&t, first, &out) && out.token == 999);
    /* No-RPU metadata absence is distinct from an association absence. */
    assert(qda_prepare(&t, 7, 0, NULL, &first));
    assert(qda_commit(&t, first));
    assert(qda_take(&t, first, &out) && !out.snapshot);
    assert(qda_prepare(&t, 8, 1, snapshot(3), &first));
    qda_cancel(&t); assert(released == 4 && !t.prepared.token);
    assert(!qda_take(&t, first, &out));
    for (unsigned i = 0; i < QDA_MAX; ++i) {
        assert(qda_prepare(&t, 8, 1, snapshot(i), &first));
        assert(qda_commit(&t, first)); /* Duplicate source PTS are unambiguous. */
    }
    assert(!qda_prepare(&t, 8, 1, NULL, &retry));
    qda_flush(&t); assert(released == 68 && !t.count);
    assert(qda_prepare(&t, 9, 1, snapshot(4), &first));
    qda_flush(&t); assert(released == 69);
    assert(qda_prepare(&t, 9, 1, NULL, &second) && second > first);
    assert(!qda_take(&t, first, &out));
    qda_cancel(&t);
    t.next = INT64_MAX - 1;
    assert(qda_prepare(&t, 1, 1, snapshot(5), &first) && first == INT64_MAX);
    assert(qda_commit(&t, first));
    assert(!qda_prepare(&t, 1, 1, NULL, &first));
    qda_flush(&t); assert(released == 70);
    puts("QSV Dolby association foundation PASS: ownership, transactions, reorder, reset, bounds");
    return 0;
}
