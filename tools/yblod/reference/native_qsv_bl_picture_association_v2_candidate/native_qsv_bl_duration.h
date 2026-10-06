/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef YB_BL_DURATION_H
#define YB_BL_DURATION_H
#include <stdint.h>
#include <libavutil/rational.h>
/* Positive nearest rounding, ties away from zero, into Kodi microseconds. */
static int yb_duration_microseconds(int64_t duration, AVRational source, int64_t *out)
{
    if (!out || duration < 0 || source.num <= 0 || source.den <= 0)
        return 0;
    if (!duration) {
        *out = 0;
        return 1;
    }
    __int128 numerator = (__int128)duration * source.num * 1000000;
    __int128 result = (numerator + source.den / 2) / source.den;
    if (result <= 0 || result > INT64_MAX)
        return 0;
    *out = (int64_t)result;
    return 1;
}
#endif
