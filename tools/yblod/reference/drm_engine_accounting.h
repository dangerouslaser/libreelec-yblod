#ifndef YBLOD_DRM_ENGINE_ACCOUNTING_H
#define YBLOD_DRM_ENGINE_ACCOUNTING_H

/* Pure fdinfo parsing: no DRM calls, files, allocation or GPU work. */
#include <errno.h>
#include <stdlib.h>
#include <string.h>

static const char *const engine_names[4] = {
    "render", "copy", "video", "video-enhance"
};

typedef struct {
    unsigned long long ns[4];
    int present[4];
    unsigned long long client_id;
    int client_present;
    char pci_device[32];
    unsigned private_seen;
} EngineSample;

static int engine_space(char c)
{
    return c == ' ' || c == '\t' || c == '\r' || c == '\n'
        || c == '\v' || c == '\f';
}

static const char *engine_skip_space(const char *p)
{
    while (engine_space(*p)) ++p;
    return p;
}

static int engine_unsigned(const char *text, int unit_ns,
                           unsigned long long *value)
{
    const char *p = engine_skip_space(text);
    char *end;
    unsigned long long parsed;
    if (*p < '0' || *p > '9') return 0;
    errno = 0;
    parsed = strtoull(p, &end, 10);
    if (errno || end == p) return 0;
    if (unit_ns) {
        /* Require a separate unit token, not e.g. 12ns or 12 nanoseconds. */
        if (!engine_space(*end)) return 0;
        p = engine_skip_space(end);
        if (p[0] != 'n' || p[1] != 's') return 0;
        p += 2;
    } else {
        p = end;
    }
    if (*engine_skip_space(p)) return 0;
    *value = parsed;
    return 1;
}

/* Return zero for a malformed or duplicate recognized field. A caller must
 * discard the entire snapshot on zero; unknown fdinfo fields are harmless.
 * Input is one complete NUL-terminated line, not a truncated fgets fragment. */
static int engine_parse_line(EngineSample *sample, const char *line)
{
    static const char *const keys[6] = {
        "drm-engine-render", "drm-engine-copy", "drm-engine-video",
        "drm-engine-video-enhance", "drm-client-id", "drm-pdev"
    };
    unsigned field;
    size_t length = 0;
    for (field = 0; field < 6; ++field) {
        length = strlen(keys[field]);
        if (!strncmp(line, keys[field], length)
                && (line[length] == ':' || !line[length]
                    || engine_space(line[length]))) break;
    }
    if (field == 6) return 1;
    unsigned bit = 1u << field;
    int duplicate = (sample->private_seen & bit) != 0;
    sample->private_seen |= bit;
    if (field < 4) sample->present[field] = 0;
    else if (field == 4) sample->client_present = 0;
    else sample->pci_device[0] = '\0';
    if (duplicate || line[length] != ':') return 0;
    const char *value = line + length + 1;
    if (field < 4) {
        if (!engine_unsigned(value, 1, &sample->ns[field])) return 0;
        sample->present[field] = 1;
    } else if (field == 4) {
        if (!engine_unsigned(value, 0, &sample->client_id)) return 0;
        sample->client_present = 1;
    } else {
        const char *p = engine_skip_space(value), *start = p;
        int has_hex = 0;
        while (*p && !engine_space(*p)) {
            int hex = (*p >= '0' && *p <= '9')
                || (*p >= 'a' && *p <= 'f') || (*p >= 'A' && *p <= 'F');
            if (!hex && *p != ':' && *p != '.') return 0;
            has_hex |= hex;
            ++p;
        }
        size_t count = (size_t)(p - start);
        if (!has_hex || count >= sizeof(sample->pci_device)
                || *engine_skip_space(p)) return 0;
        memcpy(sample->pci_device, start, count);
        sample->pci_device[count] = '\0';
    }
    return 1;
}

/* Missing fields and counter regressions remain unavailable, never zero.
 * Engine times are per-client accounting, not proof of the SFC sub-block. */
static EngineSample engine_delta(EngineSample before, EngineSample after)
{
    EngineSample delta = {0};
    if (!before.client_present || !after.client_present
            || !before.pci_device[0]
            || before.client_id != after.client_id
            || strcmp(before.pci_device, after.pci_device)) return delta;
    delta.client_present = 1;
    delta.client_id = before.client_id;
    memcpy(delta.pci_device, before.pci_device, sizeof(delta.pci_device));
    for (unsigned i = 0; i < 4; ++i) {
        if (before.present[i] && after.present[i]
                && after.ns[i] >= before.ns[i]) {
            delta.present[i] = 1;
            delta.ns[i] = after.ns[i] - before.ns[i];
        }
    }
    return delta;
}

#endif
