// The output colour mapping (include/dvvk_map.h, yblod/dv_map.c's
// dvvk_map_nonlinear / dvvk_map_rgb / dvvk_map_ycc in float): Dolby Vision's
// reconstructed 12-bit Y'CbCr to BT.2020 PQ, as CroqueMr's CB1 "Reference
// Basic" renders it with libplacebo (pl_shader_decode_color for Dolby
// Vision, then pl_shader_color_map_ex: IPT, the tone LUT on I, the hull
// desaturation). The includer declares MAP_PARAMS_BINDING, and
// MAP_CELLS_BINDING for the cells buffer (map_bake's marked cells, then the
// fix-up list at word mp.list: groups, 1, 1, count, the entries).
//
// MAP_SDR (a specialization constant, id MAP_SDR_ID, where the includer
// defines one: the HDR10 pipelines keep their code): the output is an SDR
// display's R'G'B' instead (the same recipe compressing to the display's
// white, then libplacebo's gamut LUT and the display's inverse EOTF), as
// 8-bit codes. The includer then declares MAP_TABLES_BINDING
// (dvvk_map_tables' words: the dither pattern) and MAP_GAMUT_BINDING (the
// gamut LUT, the tables' second part as an RGBA16 UNORM 3D texture).
// MAP_SDR 2: SDR output of an HLG source (DVVK_MAP_HLG). A constant and not
// the parameters' flag, so that the pipelines of PQ sources are compiled
// from the code they had before there was HLG: their bytes stay.
struct DvMap {
    vec4 ycc[3];
    vec4 ycc_offset;
    vec4 src_lms2rgb[3];
    vec4 rgb2lms[3];
    vec4 lms2rgb[3];
    vec4 lms2ipt[3];
    vec4 ipt2lms[3];
    vec4 tone_in;    // min, max, 1 / (max - min) (PQ)
    vec4 tone_out;
    uint flags;      // 1 tone
    uint lut_n;
    uint list;       // the cells buffer's fix-up list (word offset; the engine's)
    uint lut_ny;     // SDR: the LUT's points along luma (lut_n: along each chroma)
    uvec4 black_in;  // the stream's black codes, and their exact output codes
    uvec4 black_out;
    float tone_lut[256];
    vec4 gamut_at;   // SDR: the gamut LUT's I coordinate, x * I + y
    vec4 out_trc;    // V = pow(max(x * L + y, 0), z) - w
    vec4 out_code;   // codes: x * V + y
    uvec2 gamut_key;
    vec2 lut_box;    // SDR: the LUT's domain in codes: luma 0 .. x, chroma 2048 -+ y
    vec4 src_trc;    // an HLG source: x the black lift, y gamma - 1, z the peak
    vec4 src_luma;
};
layout(binding = MAP_PARAMS_BINDING, std430) readonly buffer MapParams { DvMap mp; };
#ifdef MAP_SDR_ID
layout(constant_id = MAP_SDR_ID) const uint MAP_SDR = 0u;
layout(binding = MAP_TABLES_BINDING, std430) readonly buffer MapTables { uint map_tables[]; };
layout(binding = MAP_GAMUT_BINDING) uniform sampler3D map_gamut;
#else
const uint MAP_SDR = 0u;
#endif
#ifdef MAP_CELLS_BINDING
layout(binding = MAP_CELLS_BINDING, std430) buffer MapCells { uint map_cells[]; };

#endif

vec3 map_m3(vec4 m[3], vec3 v) { return vec3(dot(m[0].xyz, v), dot(m[1].xyz, v), dot(m[2].xyz, v)); }

vec3 map_pq_eotf(vec3 v)
{
    vec3 p = pow(max(v, 0.0), vec3(1.0 / 78.84375));
    return pow(max(p - 0.8359375, 0.0) / (18.8515625 - 18.6875 * p), vec3(1.0 / 0.1593017578125));
}

vec3 map_pq_oetf(vec3 v)
{
    vec3 p = pow(max(v, 0.0), vec3(0.1593017578125));
    return pow((0.8359375 + 18.8515625 * p) / (1.0 + 18.6875 * p), vec3(78.84375));
}

// the reconstructed codes to the source's nonlinear R'G'B' (L'M'S' for IPT),
// HDR10's 3D LUT's domain. An HLG source's (MAP_SDR 2) is not clamped at 1:
// its signal goes on above nominal white; SDR output of a PQ source at 1.5
// (dvvk_map_nonlinear).
vec3 map_nonlinear(vec3 codes)
{
#ifdef MAP_SDR_ID
    if (MAP_SDR == 2u)
        return max(map_m3(mp.ycc, codes * (1.0 / 4095.0)) + mp.ycc_offset.xyz, 0.0);
    if (MAP_SDR == 1u)
        return clamp(map_m3(mp.ycc, codes * (1.0 / 4095.0)) + mp.ycc_offset.xyz, 0.0, 1.5);
#endif
    return clamp(map_m3(mp.ycc, codes * (1.0 / 4095.0)) + mp.ycc_offset.xyz, 0.0, 1.0);
}

float map_tone(float x)
{
    float t = clamp((x - mp.tone_in.x) * mp.tone_in.z, 0.0, 1.0) * 255.0;
    uint i = min(uint(t), 254u);
    return mix(mp.tone_lut[i], mp.tone_lut[i + 1u], t - float(i));
}

#ifdef MAP_SDR_ID
// An HLG source's R'G'B' to light (dv_map.c dvvk_map_rgb; pl_shader_linearize):
// the inverse OETF, the scene's light over 12, then the OOTF.
vec3 map_hlg(vec3 v)
{
    v = (1.0 - mp.src_trc.x) * v + mp.src_trc.x;
    v = mix(4.0 * v * v, exp((v - 0.55991073) * (1.0 / 0.17883277)) + 0.28466892, lessThan(vec3(0.5), v)) * (1.0 / 12.0);
    return v * (mp.src_trc.z * pow(max(dot(mp.src_luma.xyz, v), 0.0), mp.src_trc.y));
}

// pl_shader_color_map_ex's gamut LUT lookup (dv_map.c gamut_map), as its
// shader does it: the texture sampled linearly at I, 2 C, h / 2 pi + 0.5
// (texel centres at the ends of each axis), P and T stored with an offset.
// (The sampler's weights have 8 bits on these GPUs: against the CPU's exact
// ones that is a few hundredths of an output code at most.) A neutral colour
// has no hue: any.
vec3 map_gamut_lookup(vec3 ipt)
{
    float h = ipt.y == 0.0 && ipt.z == 0.0 ? 0.0 : atan(ipt.z, ipt.y);
    vec3 idx = vec3(mp.gamut_at.x * ipt.x + mp.gamut_at.y, 2.0 * length(ipt.yz), h * 0.15915494309189535 + 0.5);
    const vec3 n = vec3(48.0, 32.0, 256.0);
    vec3 v = textureLod(map_gamut, clamp(idx, 0.0, 1.0) * ((n - 1.0) / n) + 0.5 / n, 0.0).rgb;
    return v - vec3(0.0, 32768.0 / 65535.0, 32768.0 / 65535.0);
}

// SDR: linear BT.2020 light to the display's R'G'B' (0..1), always through
// IPT (the tone curve, the gamut LUT, the display's primaries).
vec3 map_sdr(vec3 lin)
{
    vec3 ipt = map_m3(mp.lms2ipt, map_pq_oetf(map_m3(mp.rgb2lms, lin)));
    if ((mp.flags & 1u) != 0u) {
        float i0 = ipt.x;
        ipt.x = map_tone(i0);
        float h0 = ((i0 - 6.0) * i0 + 9.0) * i0, h1 = ((ipt.x - 6.0) * ipt.x + 9.0) * ipt.x;
        ipt.yz *= ipt.x > 0.0 && h0 > 0.0 ? min(i0 / ipt.x, h1 / h0) : 0.0;
    }
    if ((mp.flags & 8u) != 0u)
        ipt = map_gamut_lookup(ipt);
    lin = map_m3(mp.lms2rgb, map_pq_eotf(map_m3(mp.ipt2lms, ipt)));
    return clamp(pow(max(mp.out_trc.x * lin + mp.out_trc.y, 0.0), vec3(mp.out_trc.z)) - mp.out_trc.w, 0.0, 1.0);
}
#endif

// the nonlinear source to the output's PQ R'G'B' (SDR: the display's
// R'G'B'); the returned bits say which way each clamp and branch went
// (dvvk_map_rgb; not for SDR)
uint map_rgb(vec3 nl, out vec3 rgb)
{
    uint regime = 0u;
#ifdef MAP_SDR_ID
    if (MAP_SDR == 2u) {
        rgb = map_sdr(max(map_m3(mp.src_lms2rgb, map_hlg(nl)), 0.0));
        return regime;
    }
#endif
    vec3 lin = map_m3(mp.src_lms2rgb, map_pq_eotf(nl));
    regime |= uint(lin.x < 0.0) | uint(lin.y < 0.0) << 1 | uint(lin.z < 0.0) << 2;
    lin = max(lin, 0.0);
#ifdef MAP_SDR_ID
    if (MAP_SDR != 0u) {
        rgb = map_sdr(lin);
        return regime;
    }
#endif
    if ((mp.flags & 1u) != 0u) {
        vec3 ipt = map_m3(mp.lms2ipt, map_pq_oetf(map_m3(mp.rgb2lms, lin)));
        float i0 = ipt.x;
        regime |= uint(i0 <= mp.tone_in.x) << 3 | uint(i0 >= mp.tone_in.y) << 4;
        ipt.x = map_tone(i0);
        float h0 = ((i0 - 6.0) * i0 + 9.0) * i0, h1 = ((ipt.x - 6.0) * ipt.x + 9.0) * ipt.x;
        bool ok = ipt.x > 0.0 && h0 > 0.0;
        float k = ok ? min(i0 / ipt.x, h1 / h0) : 0.0;
        regime |= uint(ok && i0 / ipt.x < h1 / h0) << 5 | uint(!ok) << 6;
        ipt.yz *= k;
        vec3 lms = map_m3(mp.ipt2lms, ipt);
        regime |= uint(lms.x < 0.0) << 7 | uint(lms.y < 0.0) << 8 | uint(lms.z < 0.0) << 9;
        lin = map_m3(mp.lms2rgb, map_pq_eotf(lms));
    }
    regime |= uint(lin.x < 0.0) << 10 | uint(lin.y < 0.0) << 11 | uint(lin.z < 0.0) << 12;
    rgb = map_pq_oetf(lin);
    return regime;
}

// BT.2020 non-constant luminance: Y' 0..1, Cb', Cr' -0.5..0.5
vec3 map_ycc(vec3 rgb)
{
    float y = dot(rgb, vec3(0.2627, 0.6780, 0.0593));
    return vec3(y, (rgb.b - y) * (1.0 / 1.8814), (rgb.r - y) * (1.0 / 1.4746));
}

// 12-bit limited-range codes, unrounded (the 3D LUT holds these / 4096)
vec3 map_codes(vec3 ycc) { return vec3(256.0, 2048.0, 2048.0) + vec3(3504.0, 3584.0, 3584.0) * ycc; }
// rounded (16 .. 4079: no HDMI-reserved values)
uint map_q(float v) { return uint(clamp(floor(v + 0.5), 16.0, 4079.0)); }
// What the 3D LUT's nodes hold: map_rgb's result as unrounded output codes
// over map_node_scale() (12-bit Y'CbCr / 4096; SDR: the display's R'G'B'
// codes / 256).
float map_node_scale() { return MAP_SDR != 0u ? 256.0 : 4096.0; }
vec3 map_out_codes(vec3 rgb)
{
    if (MAP_SDR != 0u)
        return mp.out_code.x * rgb + mp.out_code.y;
    return map_codes(map_ycc(rgb));
}
#ifdef MAP_SDR_ID
// SDR: pixel (x, y)'s codes from its unrounded ones: floor(code + bias), the
// bias the dither pattern's rank / 4096 (pl_shader_dither's blue noise), or
// one half (rounded). dvvk_map_sdr_code.
uvec3 map_sdr_q(vec3 codes, uvec2 at)
{
    float bias = (mp.flags & 16u) != 0u ? float(map_tables[(at.y & 63u) * 64u + (at.x & 63u)]) * (1.0 / 4096.0) : 0.5;
    return uvec3(floor(codes + bias));
}
// XRGB8888
uint map_sdr_word(uvec3 c) { return c.b | c.g << 8 | c.r << 16 | 0xff000000u; }
#endif

// The decode (map_nonlinear) in the LUT's texture coordinates (not SDR's
// LUT: map_sdr_coord), split: the
// pair's chroma part once (map_base), then each sample's luma (map_coord).
// t = clamp(nl, 0, 1) * (n - 1) / n + 0.5 / n.
vec3 map_base(uint cb, uint cr)
{
    float n = float(mp.lut_n), s = (n - 1.0) / n;
    vec2 c = vec2(cb, cr) * (s / 4095.0);
    return vec3(dot(mp.ycc[0].yz, c), dot(mp.ycc[1].yz, c), dot(mp.ycc[2].yz, c)) + mp.ycc_offset.xyz * s + 0.5 / n;
}
vec3 map_coord(uint yy, vec3 base)
{
    float n = float(mp.lut_n), s = (n - 1.0) / n;
    vec3 my = vec3(mp.ycc[0].x, mp.ycc[1].x, mp.ycc[2].x) * (s / 4095.0);
    return clamp(my * float(yy) + base, 0.5 / n, s + 0.5 / n);
}

// the exact mapping of one sample (its luma, the pair's chroma): unrounded codes
vec3 map_exact(uint yy, uint cb, uint cr)
{
    vec3 rgb;
    map_rgb(map_nonlinear(vec3(yy, cb, cr)), rgb);
    return map_out_codes(rgb);
}

#ifdef MAP_SDR_ID
// SDR: a pixel has its own chroma, the pair's sample on the even pixel and
// the mean of it and the next pair's on the odd one (4:2:2 is sited on the
// even pixel), so the codes are not integers: map_exact for them.
// Its 3D LUT lies over the codes themselves (dvvk_map.h): luma along x from
// 0 to lut_box.x, Cb and Cr along y and z, lut_box.y either side of neutral.
// map_sdr_box: a point of that box (0..1 an axis) as codes. map_sdr_coord: a
// sample's texture coordinates (one outside the box: its nearest face's),
// from map_sdr_axes' numbers, which a shader works out once.
uvec3 map_sdr_size() { return uvec3(mp.lut_ny, mp.lut_n, mp.lut_n); }
vec3 map_sdr_box(vec3 u) { return vec3(u.x * mp.lut_box.x, 2048.0 + (2.0 * u.yz - 1.0) * mp.lut_box.y); }
void map_sdr_axes(out vec3 scale, out vec3 offset, out vec3 lo)
{
    vec3 n = vec3(map_sdr_size()), s = (n - 1.0) / n;
    lo = 0.5 / n;
    scale = s * vec3(1.0, 0.5, 0.5) / mp.lut_box.xyy;
    offset = lo + s * vec3(0.0, 0.5, 0.5);
}
vec3 map_sdr_coord(uint yy, vec2 cbcr, vec3 scale, vec3 offset, vec3 lo)
{
    return clamp(vec3(float(yy), cbcr - 2048.0) * scale + offset, lo, 1.0 - lo);
}
vec3 map_exact(uint yy, vec2 cbcr)
{
    vec3 rgb;
    map_rgb(map_nonlinear(vec3(float(yy), cbcr)), rgb);
    return map_out_codes(rgb);
}
// A pixel (its luma, its chroma, its unrounded codes c, where it is) as its
// XRGB8888 word. The stream's black (the letterbox) is its exact code,
// undithered: bars stay one value.
uint map_sdr_pixel(uint yy, vec2 cbcr, vec3 c, uvec2 at)
{
    uvec3 bi = mp.black_in.xyz;
    if (yy == bi.x && cbcr == vec2(bi.yz))
        return map_sdr_word(mp.black_out.xyz);
    return map_sdr_word(map_sdr_q(c, at));
}
#endif

// A pair's output codes from its input codes a (even: Y, Cb) and b (odd: Y,
// Cr) and its samples' mapped codes (unrounded) e and o (the pair's chroma is e's, the
// co-sited sample's). The stream's black (the letterbox) is exact: black_out.
void map_pair(uvec2 a, uvec2 b, vec3 e, vec3 o, out uvec2 ra, out uvec2 rb)
{
    uvec3 bi = mp.black_in.xyz, bo = mp.black_out.xyz;
    bool chroma_black = a.y == bi.y && b.y == bi.z;
    bool both = chroma_black && a.x == bi.x;
    ra = both ? bo.xy : uvec2(map_q(e.x), map_q(e.y));
    rb = uvec2(chroma_black && b.x == bi.x ? bo.x : map_q(o.x), both ? bo.z : map_q(e.z));
}

// the tunnel's pixel word (12-bit Y and C in XRGB8888), as pack's finish()
uint map_word(uvec2 v) { return ((v.y & 15u) << 4 | (v.x & 15u)) | (v.x >> 4) << 8 | (v.y >> 4) << 16 | 0xff000000u; }
uvec2 map_unword(uint w) { return uvec2((w >> 8 & 255u) << 4 | (w & 15u), (w >> 16 & 255u) << 4 | (w >> 4 & 15u)); }
