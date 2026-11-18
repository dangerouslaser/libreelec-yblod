/* A display's LLDV target from its Dolby Vision vendor-specific video data
 * block (include/dv_engine_vk.h dvvk_lldv_display_from_vsvdb), for the
 * players (Kodi, mpv) to hand DVVK_OUTPUT_LLDV.
 *
 * Ported from CroqueMr's CB1 Kodi patches at
 * b5149a09d759ab2cc1dd8c0b6d156da67d70cae6 (projects/Generic/patches/kodi):
 * the block's checks of dvbridge_parse_edid (xbmc/utils/DVBridgeEdid.h, MIT,
 * after kodi-9992-cb1-display, -lldv-format and -lldv-signal-formats) and
 * ReadLldvDisplay, ValidLldvPrimaries and FitLldvPrimaries
 * (xbmc/utils/DVBridgeLldv.h, GPL-2.0-or-later, after
 * kodi-9999-...-lldv-edid-target), C instead of C++ and a block instead of
 * a whole EDID (the caller finds the block), the arithmetic and decisions
 * unchanged. CB1's notices: SPDX-License-Identifier: MIT (DVBridgeEdid.h),
 * GPL-2.0-or-later (DVBridgeLldv.h).
 * SPDX-License-Identifier: GPL-2.0-or-later */
#include "dv_engine_vk.h"
#include <math.h>
#include <string.h>

/* LldvPqNits */
static double pq_nits(unsigned code)
{
    const double value = pow(code / 4095.0, 32.0 / 2523);
    return 10000 * pow(fmax(0, value - 3424.0 / 4096) / (2413.0 / 128 - (2392.0 / 128) * value), 16384.0 / 2610);
}

/* LldvEdge */
static double edge(double x, double y, const double *a, const double *b)
{
    return (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]);
}

/* ValidLldvPrimaries */
static int valid_primaries(const double primaries[6])
{
    for (int i = 0; i < 3; ++i)
        if (primaries[i * 2] <= 0 || primaries[i * 2 + 1] <= 0 || primaries[i * 2] + primaries[i * 2 + 1] > 1.0 ||
            edge(.3127, .3290, &primaries[i * 2], &primaries[((i + 1) % 3) * 2]) <= 0.000001)
            return 0;
    return 1;
}

/* FitLldvPrimaries: a primary outside BT.2020 by up to one 1/256 step of
 * each axis (the block's quantisation) is moved onto its nearest edge */
static int fit_primaries(double primaries[6])
{
    static const double bt2020[][2] = {{.708, .292}, {.170, .797}, {.131, .046}};
    for (int i = 0; i < 6; i += 2) {
        double *x = &primaries[i], *y = &primaries[i + 1];
        double nearest_distance = 1, nearest_x = *x, nearest_y = *y;
        int outside = 0;
        for (int j = 0; j < 3; ++j) {
            const double *a = bt2020[j], *b = bt2020[(j + 1) % 3];
            outside |= edge(*x, *y, a, b) < 0;
            const double dx = b[0] - a[0], dy = b[1] - a[1];
            const double t = fmax(0, fmin(1, ((*x - a[0]) * dx + (*y - a[1]) * dy) / (dx * dx + dy * dy)));
            const double px = a[0] + t * dx, py = a[1] + t * dy;
            const double distance = hypot(*x - px, *y - py);
            if (distance < nearest_distance) {
                nearest_distance = distance;
                nearest_x = px;
                nearest_y = py;
            }
        }
        if (outside) {
            if (nearest_distance > sqrt(2.0) / 256)
                return 0;
            *x = nearest_x;
            *y = nearest_y;
        }
    }
    return valid_primaries(primaries);
}

int dvvk_lldv_vsvdb(const uint8_t *block, size_t size, dvvk_lldv_display *out)
{
    if (!block || !out)
        return -1;
    memset(out, 0, sizeof(*out));
    out->status = DVVK_VSVDB_INVALID;
    if (!size)
        return -2;
    /* dvbridge_parse_edid's test of a data block: tag 7 (extended), at least
     * the extended tag and the OUI, extended tag 1 (VSVDB), OUI 00-D0-46 */
    const unsigned len = block[0] & 31;
    const uint8_t *data = block + 1;
    if ((block[0] >> 5) != 7 || len < 4 || size < (size_t)len + 1 || data[0] != 1 || data[1] != 0x46 ||
        data[2] != 0xd0 || data[3] != 0)
        return -2;
    /* (its DV_EDID_LENGTH and DV_EDID_VERSION) */
    out->status = DVVK_VSVDB_UNSUPPORTED;
    if (len < 5)
        return -2;
    const unsigned version = data[4] >> 5;
    out->version = version;
    int lldv_422 = 0;
    switch (version) {
    case 0:
        if (len != 21)
            return -2;
        break;
    case 1:
        if (len != 11 && len != 14)
            return -2;
        /* Long V1 and short V1 without LL use HDMI-1.4b signaling, not the
         * modern Dolby-OUI packet. */
        lldv_422 = len == 11 && (data[7] & 1);
        break;
    case 2:
        if (len < 11)
            return -2;
        /* V2 includes LL 4:2:2. Its 4:4:4 variant also needs the Low
         * Latency HDMI interface bit and a defined depth. */
        lldv_422 = 1;
        if (data[6] & 1) {
            const unsigned depth = ((data[7] & 1) << 1) | (data[8] & 1);
            out->flags |= depth == 1 ? DVVK_VSVDB_444_10 : depth == 2 ? DVVK_VSVDB_444_12 : 0u;
        }
        break;
    default:
        return -2;
    }
    if (data[4] & 1)
        out->flags |= DVVK_VSVDB_422_12;
    if (!(version == 2 && (data[6] & 3) < 2))
        out->flags |= DVVK_VSVDB_STANDARD;
    /* ReadLldvDisplay: the low-latency 4:2:2 interface, then the target */
    const uint8_t *p = data + 4;
    out->status = DVVK_VSVDB_NO_LOW_LATENCY;
    if (!lldv_422 || (version == 1 && (p[3] & 3) != 1))
        return -2;
    double reported[6];
    if (version == 2) {
        out->min_nits = pq_nits(20 * (p[1] >> 3));
        out->peak_nits = pq_nits(2055 + 65 * (p[2] >> 3));
        const double r[6] = {.625 + (p[5] >> 3) / 256.0, .25 + (p[6] >> 3) / 256.0,    (p[3] >> 1) / 256.0,
                             .5 + (p[4] >> 1) / 256.0,   .125 + (p[5] & 7) / 256.0, .03125 + (p[6] & 7) / 256.0};
        memcpy(reported, r, sizeof(r));
    } else {
        const double black = (p[2] >> 1) / 127.0;
        out->min_nits = black * black;
        out->peak_nits = 100 + 50 * (p[1] >> 1);
        const double r[6] = {.625 + (p[6] >> 3) / 256.0,
                             .25 + (((p[6] & 7) << 2) | ((p[5] & 1) << 1) | (p[4] & 1)) / 256.0,
                             (p[4] >> 1) / 256.0,
                             .5 + (p[5] >> 1) / 256.0,
                             .125 + (p[3] >> 5) / 256.0,
                             .03125 + ((p[3] >> 2) & 7) / 256.0};
        memcpy(reported, r, sizeof(r));
    }
    double primaries[6];
    memcpy(primaries, reported, sizeof(primaries));
    memcpy(out->reported, reported, sizeof(reported));
    if (out->min_nits >= out->peak_nits || out->peak_nits > 10000)
        out->status = DVVK_VSVDB_INVALID_LUMINANCE;
    else if (!valid_primaries(reported))
        out->status = DVVK_VSVDB_INVALID_PRIMARIES;
    else if (!fit_primaries(primaries))
        out->status = DVVK_VSVDB_OUTSIDE_BT2020;
    else
        out->status = DVVK_VSVDB_READY;
    memcpy(out->primaries, primaries, sizeof(primaries));
    return out->status == DVVK_VSVDB_READY ? 0 : -2;
}
