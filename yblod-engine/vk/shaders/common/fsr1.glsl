// AMD FidelityFX Super Resolution 1 (FSR 1), EASU and RCAS, for one
// channel: the reconstructed luma (src/scaler.rs). Written from AMD's
// ffx_fsr1.h and ffx_a.h, FidelityFX-FSR v1.20210629
// (github.com/GPUOpen-Effects/FidelityFX-FSR, a21ffb8f6c13), the 32-bit
// FsrEasuF and FsrRcasF with FSR_RCAS_DENOISE, under this notice:
//
// Copyright (c) 2021 Advanced Micro Devices, Inc. All rights reserved.
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files(the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and / or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions :
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.
// (also yblod-engine/vk/LICENSES/MIT-AMD-FidelityFX-FSR.txt)
//
// The samples are luma codes / 4095, i.e. 0..1 as FSR wants them, in the
// stream's PQ (a perceptual curve, as FSR asks). A sample stands for a grey
// pixel (R = G = B = Y): its colour channels are the one value and AMD's
// "luma times 2" (B / 2 + R / 2 + G) is 2 Y, so this is FSR on that grey
// picture, operation for operation. tools/dvvk-scaler-compare.c is the CPU
// reference (double precision, the same approximations).

// ffx_a.h's approximations, bit for bit
float fsr1_rcp_lo(float a) { return uintBitsToFloat(0x7ef07ebbu - floatBitsToUint(a)); }
float fsr1_rcp_med(float a)
{
    float b = uintBitsToFloat(0x7ef19fffu - floatBitsToUint(a));
    return b * (-b * a + 2.0);
}
float fsr1_rsq_lo(float a) { return uintBitsToFloat(0x5f347d74u - (floatBitsToUint(a) >> 1u)); }
float fsr1_sat(float a) { return clamp(a, 0.0, 1.0); }

#ifdef FSR1_EASU
// The includer's float fsr1_tap(ivec2 p): source texel p (unclamped integer
// position) as the edge clamps it, /4095.

// FsrEasuTapF
void fsr1_easu_tap(inout float ac, inout float aw, vec2 off, vec2 dir, vec2 len, float lob, float clp, float c)
{
    vec2 v = vec2(off.x * dir.x + off.y * dir.y, off.x * -dir.y + off.y * dir.x) * len;
    float d2 = min(v.x * v.x + v.y * v.y, clp);
    float wb = (2.0 / 5.0) * d2 - 1.0;
    float wa = lob * d2 - 1.0;
    wb *= wb;
    wa *= wa;
    wb = (25.0 / 16.0) * wb - (25.0 / 16.0 - 1.0);
    float w = wb * wa;
    ac += c * w;
    aw += w;
}

// FsrEasuSetF: the '+' around c (a above, b c d, e below), bilinear weight w
void fsr1_easu_set(inout vec2 dir, inout float len, float w, float la, float lb, float lc, float ld, float le)
{
    float dc = ld - lc, cb = lc - lb;
    float lenx = fsr1_rcp_lo(max(abs(dc), abs(cb)));
    float dirx = ld - lb;
    dir.x += dirx * w;
    lenx = fsr1_sat(abs(dirx) * lenx);
    len += lenx * lenx * w;
    float ec = le - lc, ca = lc - la;
    float leny = fsr1_rcp_lo(max(abs(ec), abs(ca)));
    float diry = le - la;
    dir.y += diry * w;
    leny = fsr1_sat(abs(diry) * leny);
    len += leny * leny * w;
}

// FsrEasuF at output pixel ip (FsrEasuCon's con0: scale, offset). The
// position is fused as GPU compilers fuse AMD's mad; the CPU reference
// uses fmaf for the same rounding.
float fsr1_easu(uvec2 ip, vec2 scale, vec2 offset)
{
    vec2 pp = fma(vec2(ip), scale, offset);
    vec2 fp = floor(pp);
    pp -= fp;
    ivec2 f0 = ivec2(fp);
    //    b c
    //  e f g h
    //  i j k l
    //    n o
    float b = fsr1_tap(f0 + ivec2(0, -1)), c = fsr1_tap(f0 + ivec2(1, -1));
    float e = fsr1_tap(f0 + ivec2(-1, 0)), f = fsr1_tap(f0), g = fsr1_tap(f0 + ivec2(1, 0)),
          h = fsr1_tap(f0 + ivec2(2, 0));
    float i = fsr1_tap(f0 + ivec2(-1, 1)), j = fsr1_tap(f0 + ivec2(0, 1)), k = fsr1_tap(f0 + ivec2(1, 1)),
          l = fsr1_tap(f0 + ivec2(2, 1));
    float n = fsr1_tap(f0 + ivec2(0, 2)), o = fsr1_tap(f0 + ivec2(1, 2));
    vec2 dir = vec2(0.0);
    float len = 0.0;
    fsr1_easu_set(dir, len, (1.0 - pp.x) * (1.0 - pp.y), 2.0 * b, 2.0 * e, 2.0 * f, 2.0 * g, 2.0 * j);
    fsr1_easu_set(dir, len, pp.x * (1.0 - pp.y), 2.0 * c, 2.0 * f, 2.0 * g, 2.0 * h, 2.0 * k);
    fsr1_easu_set(dir, len, (1.0 - pp.x) * pp.y, 2.0 * f, 2.0 * i, 2.0 * j, 2.0 * k, 2.0 * n);
    fsr1_easu_set(dir, len, pp.x * pp.y, 2.0 * g, 2.0 * j, 2.0 * k, 2.0 * l, 2.0 * o);
    vec2 dir2 = dir * dir;
    float dirr = dir2.x + dir2.y;
    bool zro = dirr < 1.0 / 32768.0;
    dirr = zro ? 1.0 : fsr1_rsq_lo(dirr);
    dir.x = zro ? 1.0 : dir.x;
    dir *= dirr;
    len = len * 0.5;
    len *= len;
    float stretch = (dir.x * dir.x + dir.y * dir.y) * fsr1_rcp_lo(max(abs(dir.x), abs(dir.y)));
    vec2 len2 = vec2(1.0 + (stretch - 1.0) * len, 1.0 - 0.5 * len);
    float lob = 0.5 + ((1.0 / 4.0 - 0.04) - 0.5) * len;
    float clp = fsr1_rcp_lo(lob);
    float lo = min(min(f, g), min(j, k)), hi = max(max(f, g), max(j, k));
    float ac = 0.0, aw = 0.0;
    fsr1_easu_tap(ac, aw, vec2(0.0, -1.0) - pp, dir, len2, lob, clp, b);
    fsr1_easu_tap(ac, aw, vec2(1.0, -1.0) - pp, dir, len2, lob, clp, c);
    fsr1_easu_tap(ac, aw, vec2(-1.0, 1.0) - pp, dir, len2, lob, clp, i);
    fsr1_easu_tap(ac, aw, vec2(0.0, 1.0) - pp, dir, len2, lob, clp, j);
    fsr1_easu_tap(ac, aw, vec2(0.0, 0.0) - pp, dir, len2, lob, clp, f);
    fsr1_easu_tap(ac, aw, vec2(-1.0, 0.0) - pp, dir, len2, lob, clp, e);
    fsr1_easu_tap(ac, aw, vec2(1.0, 1.0) - pp, dir, len2, lob, clp, k);
    fsr1_easu_tap(ac, aw, vec2(2.0, 1.0) - pp, dir, len2, lob, clp, l);
    fsr1_easu_tap(ac, aw, vec2(2.0, 0.0) - pp, dir, len2, lob, clp, h);
    fsr1_easu_tap(ac, aw, vec2(1.0, 0.0) - pp, dir, len2, lob, clp, g);
    fsr1_easu_tap(ac, aw, vec2(1.0, 2.0) - pp, dir, len2, lob, clp, o);
    fsr1_easu_tap(ac, aw, vec2(0.0, 2.0) - pp, dir, len2, lob, clp, n);
    // normalize and dering: within the 4 nearest texels
    return min(hi, max(lo, ac * (1.0 / aw)));
}
#endif

// RCAS's sharpness, FsrRcasCon's con.x = exp2(-stops): one stop, 0.5, the
// strength CroqueMr's CB1 RCAS uses.
const float FSR1_RCAS_SHARPNESS = 0.5;
#define FSR1_RCAS_LIMIT (0.25 - (1.0 / 16.0))

// FsrRcasF with FSR_RCAS_DENOISE on the cross b (above), d e f, h (below).
// Where a limiter divides 0 by 0 (a ring all at 0 or all at 1), AMD's HLSL
// gets a NaN and max() takes the other operand, as here. One change: the
// resolve divides exactly. AMD's APrxMedRcpF1 there is up to 0.32 % low
// (at lobe 0, i.e. even unsharpened), below a code of 8-bit sRGB but up to
// 13 of these 12-bit PQ codes, a flat area's level moving with the noise
// term.
float fsr1_rcas(float b, float d, float e, float f, float h)
{
    float bl = 2.0 * b, dl = 2.0 * d, el = 2.0 * e, fl = 2.0 * f, hl = 2.0 * h;
    float nz = 0.25 * bl + 0.25 * dl + 0.25 * fl + 0.25 * hl - el;
    nz = fsr1_sat(abs(nz) * fsr1_rcp_med(max(max(max(bl, dl), el), max(fl, hl)) - min(min(min(bl, dl), el), min(fl, hl))));
    nz = -0.5 * nz + 1.0;
    float mn4 = min(min(min(b, d), f), h), mx4 = max(max(max(b, d), f), h);
    float hitmin = min(mn4, e) * (1.0 / (4.0 * mx4));
    float hitmax = (1.0 - max(mx4, e)) * (1.0 / (4.0 * mn4 - 4.0));
    float lobe = mx4 == 0.0 ? hitmax : mn4 == 1.0 ? -hitmin : max(-hitmin, hitmax);
    lobe = max(-FSR1_RCAS_LIMIT, min(lobe, 0.0)) * FSR1_RCAS_SHARPNESS;
    lobe *= nz;
    return (lobe * b + lobe * d + lobe * h + lobe * f + e) / (4.0 * lobe + 1.0);
}
