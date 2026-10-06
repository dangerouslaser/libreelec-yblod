/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "dvbridge_fel_qsv_tokens.h"
#include <assert.h>
#include <stdio.h>
int main(void)
{
    struct dvbridge_qsv_tokens map = {0};
    struct dvbridge_qsv_timestamp out;
    int64_t token, retry;
    bool enabled = true;
    assert(dvbridge_qsv_option(NULL, &enabled) && !enabled);
    assert(dvbridge_qsv_option("0", &enabled) && !enabled);
    assert(dvbridge_qsv_option("1", &enabled) && enabled);
    const char *invalid[] = {"", "true", "false", "01", " 1", "1 ", "-1", "2"};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(*invalid); ++i)
        assert(!dvbridge_qsv_option(invalid[i], &enabled));
    assert(dvbridge_qsv_token_peek(&map, 1234567890123, &token));
    assert(token == 1 && map.count == 0 && map.next == 0);
    /* Repeated EAGAIN attempts do not consume identities. */
    assert(dvbridge_qsv_token_peek(&map, 1234567890123, &retry) && retry == token);
    assert(!dvbridge_qsv_token_commit(&map, token + 1, 1234567890123, 41708));
    assert(dvbridge_qsv_token_commit(&map, token, 1234567890123, 41708));
    assert(!dvbridge_qsv_token_peek(&map, 1234567890123, &retry));
    assert(dvbridge_qsv_token_peek(&map, -100, &token) && token == 2);
    assert(dvbridge_qsv_token_commit(&map, token, -100, 0));
    assert(dvbridge_qsv_token_peek(&map, 1234567890124, &token) && token == 3);
    assert(dvbridge_qsv_token_commit(&map, token, 1234567890124, 41709));
    /* Hardware output reordering is not packet FIFO order. */
    assert(dvbridge_qsv_token_take(&map, 3, &out));
    assert(out.pts == 1234567890124 && out.duration == 41709);
    assert(dvbridge_qsv_token_take(&map, 1, &out));
    assert(out.pts == 1234567890123 && out.duration == 41708);
    assert(!dvbridge_qsv_token_take(&map, 1, &out));
    assert(!dvbridge_qsv_token_take(&map, 999, &out));
    assert(dvbridge_qsv_token_take(&map, 2, &out) && out.pts == -100);
    assert(map.count == 0);
    for (unsigned i = 0; i < DVBRIDGE_QSV_TOKEN_MAX; ++i) {
        assert(dvbridge_qsv_token_peek(&map, i, &token));
        assert(dvbridge_qsv_token_commit(&map, token, i, 1));
    }
    assert(!dvbridge_qsv_token_peek(&map, 9999, &token));
    int64_t previous = map.next;
    dvbridge_qsv_tokens_reset(&map);
    assert(map.count == 0 && map.next == previous);
    assert(!dvbridge_qsv_token_take(&map, previous, &out));
    assert(dvbridge_qsv_token_peek(&map, 9999, &token) && token == previous + 1);
    assert(dvbridge_qsv_token_commit(&map, token, 9999, 7));
    assert(!dvbridge_qsv_token_take(&map, previous, &out));
    map.next = INT64_MAX;
    assert(!dvbridge_qsv_token_peek(&map, 1, &token));
    puts("QSV timestamp association: PASS (retry, reorder, precision, bounds, reset, unknown, duplicate, overflow)");
    return 0;
}
