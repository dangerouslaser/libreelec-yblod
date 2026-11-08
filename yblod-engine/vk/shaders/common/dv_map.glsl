// The output colour mapping (include/dvvk_map.h, yblod/dv_map.c's
// dvvk_map_nonlinear / dvvk_map_rgb / dvvk_map_ycc in float): Dolby Vision's
// reconstructed 12-bit Y'CbCr to BT.2020 PQ, as CroqueMr's CB1 "Reference
// Basic" renders it with libplacebo (pl_shader_decode_color for Dolby
// Vision, then pl_shader_color_map_ex: IPT, the tone LUT on I, the hull
// desaturation). The includer declares MAP_PARAMS_BINDING, and
// MAP_CELLS_BINDING for the cells buffer (map_bake's marked cells, then the
// fix-up list at word mp.list: groups, 1, 1, count, the entries).
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
    uint pad1;
    uvec4 black_in;  // the stream's black codes, and their exact output codes
    uvec4 black_out;
    float tone_lut[256];
};
layout(binding = MAP_PARAMS_BINDING, std430) readonly buffer MapParams { DvMap mp; };
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
// the 3D LUT's domain
vec3 map_nonlinear(vec3 codes)
{
    return clamp(map_m3(mp.ycc, codes * (1.0 / 4095.0)) + mp.ycc_offset.xyz, 0.0, 1.0);
}

float map_tone(float x)
{
    float t = clamp((x - mp.tone_in.x) * mp.tone_in.z, 0.0, 1.0) * 255.0;
    uint i = min(uint(t), 254u);
    return mix(mp.tone_lut[i], mp.tone_lut[i + 1u], t - float(i));
}

// the nonlinear source to the output's PQ R'G'B'; the returned bits say
// which way each clamp and branch went (dvvk_map_rgb)
uint map_rgb(vec3 nl, out vec3 rgb)
{
    uint regime = 0u;
    vec3 lin = map_m3(mp.src_lms2rgb, map_pq_eotf(nl));
    regime |= uint(lin.x < 0.0) | uint(lin.y < 0.0) << 1 | uint(lin.z < 0.0) << 2;
    lin = max(lin, 0.0);
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

// The decode (map_nonlinear) in the LUT's texture coordinates, split: the
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
    return map_codes(map_ycc(rgb));
}

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
