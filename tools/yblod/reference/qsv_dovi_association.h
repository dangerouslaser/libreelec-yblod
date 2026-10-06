/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef QSV_DOVI_ASSOCIATION_H
#define QSV_DOVI_ASSOCIATION_H
#include <stdint.h>
#include <stddef.h>
#define QDA_MAX 64
struct qda_entry {
    uint64_t token;
    int64_t pts, duration;
    void *snapshot;
};
struct qda_table {
    struct qda_entry entries[QDA_MAX], prepared;
    unsigned count;
    uint64_t next;
    void (*release)(void *);
};
/* Initialize to zero with a nonnull release callback. Calls are serialized;
 * release must not re-enter the table. Cancel/flush require this valid table. */
/* Caller constructs a private parser-state clone and immutable metadata first.
 * Successful prepare takes snapshot ownership, without publishing parser state. */
static inline int qda_prepare(struct qda_table *t, int64_t pts, int64_t duration,
                              void *snapshot, uint64_t *token)
{
    if (!t || !token || !t->release || t->prepared.token || t->count == QDA_MAX ||
        t->next >= INT64_MAX)
        return 0;
    t->prepared = (struct qda_entry){t->next + 1, pts, duration, snapshot};
    *token = t->prepared.token;
    return 1;
}
/* The same prepared identity survives hardware retries. Commit is allocation
 * free and called only after the complete AU is accepted by the decoder. */
static inline int qda_commit(struct qda_table *t, uint64_t token)
{
    if (!t || !token || token != t->prepared.token || t->count == QDA_MAX)
        return 0;
    t->entries[t->count++] = t->prepared;
    t->next = token;
    t->prepared = (struct qda_entry){0};
    return 1;
}
static inline void qda_cancel(struct qda_table *t)
{
    if (t->prepared.token)
        t->next = t->prepared.token;
    if (t->prepared.snapshot)
        t->release(t->prepared.snapshot);
    t->prepared = (struct qda_entry){0};
}
/* Successful take transfers ownership; failures leave the caller output intact. */
static inline int qda_take(struct qda_table *t, uint64_t token, struct qda_entry *out)
{
    if (!t || !out || !token)
        return 0;
    for (unsigned i = 0; i < t->count; ++i) {
        if (t->entries[i].token != token)
            continue;
        *out = t->entries[i];
        --t->count;
        for (unsigned j = i; j < t->count; ++j)
            t->entries[j] = t->entries[j + 1];
        return 1;
    }
    return 0;
}
static inline void qda_flush(struct qda_table *t)
{
    qda_cancel(t);
    for (unsigned i = 0; i < t->count; ++i)
        if (t->entries[i].snapshot)
            t->release(t->entries[i].snapshot);
    t->count = 0;
}
#endif
