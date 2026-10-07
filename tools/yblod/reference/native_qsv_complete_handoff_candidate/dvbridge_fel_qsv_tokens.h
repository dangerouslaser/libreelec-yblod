/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef DVBRIDGE_FEL_QSV_TOKENS_H
#define DVBRIDGE_FEL_QSV_TOKENS_H
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define DVBRIDGE_QSV_TOKEN_MAX 64
static inline bool dvbridge_qsv_option(const char *value, bool *enabled)
{
    if (value && strcmp(value, "0") && strcmp(value, "1"))
        return false;
    *enabled = value && !strcmp(value, "1");
    return true;
}
struct dvbridge_qsv_properties {
    int width, height, format, chroma_location;
    int color_range, color_primaries, color_trc, colorspace;
    int sar_num, sar_den;
};
struct dvbridge_qsv_timestamp {
    int64_t token, pts, duration;
    struct dvbridge_qsv_properties properties;
    bool properties_valid;
};
struct dvbridge_qsv_tokens {
    struct dvbridge_qsv_timestamp entries[DVBRIDGE_QSV_TOKEN_MAX];
    unsigned count;
    int64_t next;
};
/* Token units are exactly one 90kHz tick. Do not rescale source PTS. */
static inline bool dvbridge_qsv_token_peek(const struct dvbridge_qsv_tokens *map,
                                          int64_t pts, int64_t *token)
{
    if (map->count >= DVBRIDGE_QSV_TOKEN_MAX || map->next == INT64_MAX)
        return false;
    for (unsigned i = 0; i < map->count; ++i)
        if (map->entries[i].pts == pts)
            return false;
    *token = map->next + 1;
    return true;
}
/* Commit only after send_packet succeeds; EAGAIN reuses the same token. */
static inline bool dvbridge_qsv_token_commit(struct dvbridge_qsv_tokens *map,
                                            int64_t token, int64_t pts, int64_t duration)
{
    int64_t expected;
    if (!dvbridge_qsv_token_peek(map, pts, &expected) || token != expected)
        return false;
    map->entries[map->count++] = (struct dvbridge_qsv_timestamp){
        .token=token, .pts=pts, .duration=duration};
    map->next = token;
    return true;
}
static inline bool dvbridge_qsv_token_commit_properties(struct dvbridge_qsv_tokens *map,
        int64_t token, int64_t pts, int64_t duration,
        const struct dvbridge_qsv_properties *properties)
{
    if (!properties || properties->width <= 0 || properties->height <= 0 ||
        !dvbridge_qsv_token_commit(map, token, pts, duration))
        return false;
    map->entries[map->count-1].properties = *properties;
    map->entries[map->count-1].properties_valid = true;
    return true;
}
static inline bool dvbridge_qsv_token_take(struct dvbridge_qsv_tokens *map,
                                          int64_t token, struct dvbridge_qsv_timestamp *result)
{
    for (unsigned i = 0; i < map->count; ++i) {
        if (map->entries[i].token != token)
            continue;
        *result = map->entries[i];
        --map->count;
        memmove(map->entries + i, map->entries + i + 1,
                (map->count - i) * sizeof(*map->entries));
        return true;
    }
    return false;
}
/* Keep token generation monotonic across flushes, so stale output fails. */
static inline void dvbridge_qsv_tokens_reset(struct dvbridge_qsv_tokens *map)
{
    map->count = 0;
}
#endif
