/* YBLOD's tests of the LLDV display target parser (yblod/lldv_vsvdb.c, CB1's
 * Kodi ReadLldvDisplay): blocks of both versions as displays code them, and
 * what is refused. Run by `cargo test` (shims.c).
 * SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "dvvk_map.h"

/* ST 2084 of a 12-bit code, written out (not the parser's) */
static double st2084(unsigned code)
{
    const double e = pow(code / 4095.0, 1 / 78.84375);
    return 10000.0 * pow(fmax(e - 0.8359375, 0.0) / (18.8515625 - 18.6875 * e), 1 / 0.1593017578125);
}

static int near(double a, double b) { return fabs(a - b) < 1e-9; }

/* a fitted primary: as reported, or moved at most one 1/256 step of each
 * axis onto BT.2020's edge (the blue-red or the green-blue one) */
static int fitted(double x, double y, double rx, double ry)
{
    if (x == rx && y == ry)
        return 1;
    const double br = (0.708 - 0.131) * (y - 0.046) - (0.292 - 0.046) * (x - 0.131);
    const double gb = (0.131 - 0.170) * (y - 0.797) - (0.046 - 0.797) * (x - 0.170);
    return (fabs(br) < 1e-12 || fabs(gb) < 1e-12) && hypot(x - rx, y - ry) <= sqrt(2.0) / 256;
}

int yb_test_vsvdb(void)
{
    dvvk_lldv_display d;
    /* version 2, 12 bytes: black code 0, peak code 14 (2055 + 65 * 14), the
     * primaries in 1/256 steps (R .625 + 13, .25 + 18; G 65, .5 + 47; B
     * .125 + 5, .03125 + 5), TV-led Dolby Vision too (interface 2), 10-bit
     * low-latency 4:2:2, no 4:4:4 */
    const uint8_t v2[12] = {0xeb, 0x01, 0x46, 0xd0, 0x00, 0x48, 0x03, 0x76, 0x82, 0x5e, 0x6d, 0x95};
    assert(dvvk_lldv_vsvdb(v2, sizeof(v2), &d) == 0 && d.status == DVVK_VSVDB_READY && d.version == 2);
    assert(d.flags == DVVK_VSVDB_STANDARD);
    assert(near(d.peak_nits, st2084(2965)) && fabs(d.peak_nits - 774.869) < 1e-3 && d.min_nits == 0.0);
    const double p2[6] = {.625 + 13 / 256.0, .25 + 18 / 256.0, 65 / 256.0, .5 + 47 / 256.0, .125 + 5 / 256.0,
                          .03125 + 5 / 256.0};
    for (int i = 0; i < 6; i++)
        assert(d.reported[i / 2][i % 2] == p2[i]);
    /* its red and green inside BT.2020, its blue just outside: moved */
    for (int i = 0; i < 4; i++)
        assert(d.primaries[i / 2][i % 2] == p2[i]);
    assert(d.primaries[2][0] != p2[4] && fitted(d.primaries[2][0], d.primaries[2][1], p2[4], p2[5]));
    /* its black code at the top (31: PQ 620, CB1's 1.029 cd/m2 bound) */
    uint8_t b2[12];
    memcpy(b2, v2, sizeof(b2));
    b2[6] = 31 << 3 | 3;
    assert(dvvk_lldv_vsvdb(b2, sizeof(b2), &d) == 0 && near(d.min_nits, st2084(620)) && d.min_nits < 1.029);
    /* 12-bit 4:2:2 (byte 4 bit 0), and the 4:4:4 interface at 10 and 12 bits */
    b2[5] |= 1;
    b2[7] |= 1;
    b2[8] |= 1;
    assert(dvvk_lldv_vsvdb(b2, sizeof(b2), &d) == 0 && d.flags == (DVVK_VSVDB_STANDARD | DVVK_VSVDB_422_12 | DVVK_VSVDB_444_12));
    b2[8] &= ~1, b2[9] |= 1;
    assert(dvvk_lldv_vsvdb(b2, sizeof(b2), &d) == 0 && d.flags == (DVVK_VSVDB_STANDARD | DVVK_VSVDB_422_12 | DVVK_VSVDB_444_10));
    /* low latency only (interface 0 or 1): no TV-led Dolby Vision, still a target */
    memcpy(b2, v2, sizeof(b2));
    b2[7] = 0x74;
    assert(dvvk_lldv_vsvdb(b2, sizeof(b2), &d) == 0 && d.flags == 0);
    /* a longer version 2 block is taken (len 11 or more) */
    uint8_t long2[16] = {0xef};
    memcpy(long2 + 1, v2 + 1, 11);
    assert(dvvk_lldv_vsvdb(long2, sizeof(long2), &d) == 0 && d.status == DVVK_VSVDB_READY);

    /* version 1, 12 bytes with low latency: a 200 cd/m2 projector, black code
     * 28 ((28 / 127)^2), R .625 + 10, .25 + 21 (its bits across three
     * bytes), G 54, .5 + 54, B .125 + 1, .03125 + 6 */
    const uint8_t v1[12] = {0xeb, 0x01, 0x46, 0xd0, 0x00, 0x20, 0x04, 0x38, 0x39, 0x6d, 0x6c, 0x55};
    assert(dvvk_lldv_vsvdb(v1, sizeof(v1), &d) == 0 && d.status == DVVK_VSVDB_READY && d.version == 1);
    assert(d.peak_nits == 200.0 && near(d.min_nits, (28 / 127.0) * (28 / 127.0)));
    const double p1[6] = {.625 + 10 / 256.0, .25 + 21 / 256.0, 54 / 256.0, .5 + 54 / 256.0, .125 + 1 / 256.0,
                          .03125 + 6 / 256.0};
    for (int i = 0; i < 6; i++)
        assert(d.reported[i / 2][i % 2] == p1[i]);
    assert(d.flags == DVVK_VSVDB_STANDARD);
    /* the blue primary within a 1/256 step outside BT.2020: moved onto its edge */
    for (int i = 0; i < 4; i++)
        assert(d.primaries[i / 2][i % 2] == p1[i]);
    assert(d.primaries[2][0] != p1[4] && fitted(d.primaries[2][0], d.primaries[2][1], p1[4], p1[5]));
    /* no low-latency bit (byte 7 bits 0-1 must be 1), and the long (15-byte) form: HDMI 1.4b signalling */
    uint8_t b1[15];
    memcpy(b1, v1, sizeof(v1));
    b1[8] = 0x38;
    assert(dvvk_lldv_vsvdb(b1, sizeof(v1), &d) == -2 && d.status == DVVK_VSVDB_NO_LOW_LATENCY);
    b1[8] = 0x3b;
    assert(dvvk_lldv_vsvdb(b1, sizeof(v1), &d) == -2 && d.status == DVVK_VSVDB_NO_LOW_LATENCY);
    memcpy(b1, v1, sizeof(v1));
    b1[0] = 0xee, b1[12] = b1[13] = b1[14] = 0;
    assert(dvvk_lldv_vsvdb(b1, sizeof(b1), &d) == -2 && d.status == DVVK_VSVDB_NO_LOW_LATENCY);
    /* version 0 (22 bytes): no low latency */
    uint8_t v0[22] = {0xf5, 0x01, 0x46, 0xd0, 0x00, 0x00};
    assert(dvvk_lldv_vsvdb(v0, sizeof(v0), &d) == -2 && d.status == DVVK_VSVDB_NO_LOW_LATENCY && d.version == 0);

    /* refused: a version 1 or 2 block of the wrong length, versions after 2,
     * a length below 5, no Dolby OUI, another tag, a short buffer, NULL */
    uint8_t bad[12];
    memcpy(bad, v1, sizeof(bad));
    bad[0] = 0xea;
    assert(dvvk_lldv_vsvdb(bad, sizeof(bad), &d) == -2 && d.status == DVVK_VSVDB_UNSUPPORTED);
    memcpy(bad, v2, sizeof(bad));
    bad[0] = 0xea;
    assert(dvvk_lldv_vsvdb(bad, sizeof(bad), &d) == -2 && d.status == DVVK_VSVDB_UNSUPPORTED);
    memcpy(bad, v2, sizeof(bad));
    bad[5] = 0x68;
    assert(dvvk_lldv_vsvdb(bad, sizeof(bad), &d) == -2 && d.status == DVVK_VSVDB_UNSUPPORTED && d.version == 3);
    const uint8_t short4[5] = {0xe4, 0x01, 0x46, 0xd0, 0x00};
    assert(dvvk_lldv_vsvdb(short4, sizeof(short4), &d) == -2 && d.status == DVVK_VSVDB_UNSUPPORTED);
    memcpy(bad, v2, sizeof(bad));
    bad[2] = 0x47;
    assert(dvvk_lldv_vsvdb(bad, sizeof(bad), &d) == -2 && d.status == DVVK_VSVDB_INVALID);
    memcpy(bad, v2, sizeof(bad));
    bad[0] = 0x6b;
    assert(dvvk_lldv_vsvdb(bad, sizeof(bad), &d) == -2 && d.status == DVVK_VSVDB_INVALID);
    memcpy(bad, v2, sizeof(bad));
    bad[1] = 0x02;
    assert(dvvk_lldv_vsvdb(bad, sizeof(bad), &d) == -2 && d.status == DVVK_VSVDB_INVALID);
    assert(dvvk_lldv_vsvdb(v2, 11, &d) == -2 && d.status == DVVK_VSVDB_INVALID);
    assert(dvvk_lldv_vsvdb(NULL, 12, &d) == -1 && dvvk_lldv_vsvdb(v2, 12, NULL) == -1);
    /* primaries: a green at x 0, a red with x + y above 1 (none); a red far
     * outside BT.2020 (y .25 at x .676) */
    memcpy(bad, v2, sizeof(bad));
    bad[8] = 0x00;
    assert(dvvk_lldv_vsvdb(bad, sizeof(bad), &d) == -2 && d.status == DVVK_VSVDB_INVALID_PRIMARIES);
    memcpy(bad, v2, sizeof(bad));
    bad[10] = 31 << 3 | 5;
    assert(dvvk_lldv_vsvdb(bad, sizeof(bad), &d) == -2 && d.status == DVVK_VSVDB_INVALID_PRIMARIES);
    memcpy(bad, v2, sizeof(bad));
    bad[11] = 0 << 3 | 5;
    assert(dvvk_lldv_vsvdb(bad, sizeof(bad), &d) == -2 && d.status == DVVK_VSVDB_OUTSIDE_BT2020);
    puts("YBLOD: LLDV VSVDB targets, versions 1 and 2, the BT.2020 fit and refusals");
    return 0;
}
