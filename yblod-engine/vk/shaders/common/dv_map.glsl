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
//
// MAP_EXPERT (a specialization constant, id MAP_EXPERT_ID; with MAP_SDR 0):
// CroqueMr's CB1 Expert recipe for a stated display (DVVK_MAP_EXPERT,
// yblod/dv_map.c expert_display), 1 to HDR10 (DVVK_HDR10_TARGET), 2 to
// LLDV (DVVK_OUTPUT_LLDV). Its own constant for the same reason as HLG's.
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
    // Expert (dvvk_map.h ex_*; 1 = 203 cd/m2 linear light)
    uint ex_flags;   // DVVK_EX_*
    uint ex_lut_n;
    uint ex_bits;
    uint ex_pad;
    vec4 ex_fast[3];
    vec4 ex_basis[3];
    vec4 ex_to_trim[3];
    vec4 ex_from_trim[3];
    vec4 ex_cm4_sop;
    vec4 ex_cm4_shape;
    vec4 ex_cm4_flags;
    vec4 ex_cm4_luma;
    vec4 ex_cm4_rgb_lms[3];   // columns, as CB1's mat3 uniforms
    vec4 ex_cm4_lms_rgb[3];
    vec4 ex_cm4_residual[3];
    vec4 ex_cm4_centres[2];
    vec4 ex_cm4_gains[2];
    vec4 ex_cm4_turns[2];
    vec4 ex_chroma;  // x, y: expert_chroma; z: expert_cap
    vec4 ex_luma;
    vec4 ex_out[3];
    vec4 ex_scale;   // LLDV: x 203 / peak, y peak / 203; HDR10: z the PQ ceiling
    vec4 ex_gui[3];
    vec4 ex_out_inv[3];
    float ex_tone_lut[4096];
};
layout(binding = MAP_PARAMS_BINDING, std430) readonly buffer MapParams { DvMap mp; };
#ifdef MAP_EXPERT_ID
layout(constant_id = MAP_EXPERT_ID) const uint MAP_EXPERT = 0u;
#else
const uint MAP_EXPERT = 0u;
#endif
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
#ifdef MAP_EXPERT_ID
    // LLDV: CB1's player-led decode clamps at 0 only (dvvk_map_nonlinear)
    if (MAP_EXPERT == 2u)
        return max(map_m3(mp.ycc, codes * (1.0 / 4095.0)) + mp.ycc_offset.xyz, 0.0);
#endif
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
// PQ for the SDR map: the same curves as map_pq_eotf and map_pq_oetf, to
// more of a float's precision. A display's R'G'B' near 0 is a small
// difference of the mapped L, M and S, and the textbook form loses it: its
// 78.84th power of a value near 1 (and the inverse's value less 0.8359)
// leaves the light a few parts in 100000 out, which is a display code or
// more there (five with a 2.2 power, whose slope at black has no bound).
// So the value near 1 is kept as its distance from 1: the OETF's base is
// 1 - u, and its power exp(78.84 log(1 - u)) with the logarithm from u
// (2 atanh(u / (2 - u)), its series); the EOTF's root is 1 - w with w
// from the logarithm (expm1's series). HDR10 output keeps the textbook
// form: its bytes are CB1's.
vec3 map_pq_eotf_sdr(vec3 v)
{
    // (0 has no logarithm: any signal this small is light 0)
    vec3 t = log(max(v, 1e-30)) * (1.0 / 78.84375);
    vec3 w = -t * (1.0 + t * (1.0 / 2.0) * (1.0 + t * (1.0 / 3.0) * (1.0 + t * (1.0 / 4.0) * (1.0 + t * (1.0 / 5.0) *
             (1.0 + t * (1.0 / 6.0) * (1.0 + t * (1.0 / 7.0)))))));
    return pow(max(0.1640625 - w, 0.0) / (0.1640625 + 18.6875 * w), vec3(1.0 / 0.1593017578125));
}

vec3 map_pq_oetf_sdr(vec3 v)
{
    vec3 p = pow(max(v, 0.0), vec3(0.1593017578125));
    vec3 u = 0.1640625 * (1.0 - p) / (1.0 + 18.6875 * p), z = u / (2.0 - u), z2 = z * z;
    return exp(-157.6875 * z * (1.0 + z2 * (1.0 / 3.0 + z2 * (1.0 / 5.0 + z2 * (1.0 / 7.0 + z2 * (1.0 / 9.0))))));
}

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

// The same lookup with the CPU's weights (dv_map.c gamut_map): eight texels
// and float weights instead of the sampler's 8-bit ones (DVVK_MAP_GAMUT_EXACT,
// flags 128: CB1's targets with a black floor, which magnifies them to two
// codes).
vec3 map_gamut_lookup_exact(vec3 ipt)
{
    float h = ipt.y == 0.0 && ipt.z == 0.0 ? 0.0 : atan(ipt.z, ipt.y);
    vec3 idx = vec3(mp.gamut_at.x * ipt.x + mp.gamut_at.y, 2.0 * length(ipt.yz), h * 0.15915494309189535 + 0.5);
    const vec3 n = vec3(48.0, 32.0, 256.0);
    vec3 t = clamp(idx, 0.0, 1.0) * (n - 1.0);
    ivec3 i0 = min(ivec3(floor(t)), ivec3(n) - 2);
    vec3 f = t - vec3(i0), v = vec3(0.0);
    for (int c = 0; c < 8; c++) {
        ivec3 d = ivec3(c & 1, (c >> 1) & 1, c >> 2);
        vec3 w = mix(1.0 - f, f, vec3(d));
        v += w.x * w.y * w.z * texelFetch(map_gamut, i0 + d, 0).rgb;
    }
    return v - vec3(0.0, 32768.0 / 65535.0, 32768.0 / 65535.0);
}

// SDR: linear BT.2020 light to the display's R'G'B' (0..1), always through
// IPT (the tone curve, the gamut LUT, the display's primaries).
vec3 map_sdr(vec3 lin)
{
    vec3 ipt = map_m3(mp.lms2ipt, map_pq_oetf_sdr(map_m3(mp.rgb2lms, lin)));
    if ((mp.flags & 1u) != 0u) {
        float i0 = ipt.x;
        ipt.x = map_tone(i0);
        float h0 = ((i0 - 6.0) * i0 + 9.0) * i0, h1 = ((ipt.x - 6.0) * ipt.x + 9.0) * ipt.x;
        ipt.yz *= ipt.x > 0.0 && h0 > 0.0 ? min(i0 / ipt.x, h1 / h0) : 0.0;
    }
    if ((mp.flags & 8u) != 0u)
        ipt = (mp.flags & 128u) != 0u ? map_gamut_lookup_exact(ipt) : map_gamut_lookup(ipt);
    lin = map_m3(mp.lms2rgb, map_pq_eotf_sdr(map_m3(mp.ipt2lms, ipt)));
    return clamp(pow(max(mp.out_trc.x * lin + mp.out_trc.y, 0.0), vec3(mp.out_trc.z)) - mp.out_trc.w, 0.0, 1.0);
}

#ifdef MAP_EXPERT_ID
// Expert's tone LUT (ex_lut_n entries over tone_in), as libplacebo samples it
float map_ex_tone(float x)
{
    float t = clamp((x - mp.tone_in.x) * mp.tone_in.z, 0.0, 1.0) * float(mp.ex_lut_n - 1u);
    uint i = min(uint(t), mp.ex_lut_n - 2u);
    return mix(mp.ex_tone_lut[i], mp.ex_tone_lut[i + 1u], t - float(i));
}

// CB1's CM4.0 controls (dvbridge_render.c dvbridge_creative_cm4_shader), its
// GLSL: the IPT and its inverse in difference form for a float's precision.
// The secondary (six-vector) trims are neutral in the Expert plan: left out.
vec3 cb1_cm4_log1p(vec3 x)
{
    vec3 v = x * (vec3(1.0) - x * (vec3(0.5) - x * (vec3(1.0 / 3.0) - x * (vec3(0.25) - x * (vec3(0.2) - x * (vec3(1.0 / 6.0) -
             x * (vec3(1.0 / 7.0) - x / 8.0)))))));
    if (all(lessThanEqual(abs(x), vec3(0.125))))
        return v;
    return mix(v, log(max(vec3(1.0) + x, vec3(1e-30))), greaterThan(abs(x), vec3(0.125)));
}
vec3 cb1_cm4_expm1(vec3 x)
{
    vec3 v = x * (vec3(1.0) + x * (vec3(0.5) + x * (vec3(1.0 / 6.0) + x * (vec3(1.0 / 24.0) + x * (vec3(1.0 / 120.0) +
             x * (vec3(1.0 / 720.0) + x * (vec3(1.0 / 5040.0) + x / 40320.0)))))));
    if (all(lessThanEqual(abs(x), vec3(0.25))))
        return v;
    return mix(v, exp(x) - vec3(1.0), greaterThan(abs(x), vec3(0.25)));
}
vec3 cb1_cm4_pq_u(vec3 n)
{
    vec3 v = pow(max(n, 0.0) / 10000.0, vec3(2610.0 / 16384.0));
    return (21.0 / 128.0) * (vec3(1.0) - v) / fma(vec3(2392.0 / 128.0), v, vec3(1.0));
}
vec3 cb1_cm4_pq(vec3 n)
{
    vec3 u = cb1_cm4_pq_u(n);
    return exp((2523.0 / 32.0) * cb1_cm4_log1p(-u));
}
vec3 cb1_cm4_ipt(vec3 rgb, out vec3 lms, out vec3 q, out vec3 u)
{
    lms = fma(mp.ex_cm4_rgb_lms[2].xyz, vec3(rgb.b), fma(mp.ex_cm4_rgb_lms[1].xyz, vec3(rgb.g), mp.ex_cm4_rgb_lms[0].xyz * rgb.r));
    u = cb1_cm4_pq_u(lms);
    float g = exp((2523.0 / 32.0) * cb1_cm4_log1p(vec3(-u.g)).x);
    vec3 delta = g * cb1_cm4_expm1((2523.0 / 32.0) * cb1_cm4_log1p((vec3(u.g) - u) / (1.0 - u.g)));
    q = vec3(g) + delta;
    return vec3(g + 0.4 * delta.r + 0.2 * delta.b, 4.455 * delta.r + 0.396 * delta.b, 0.8056 * delta.r - 1.1628 * delta.b);
}
// Apply the colour delta around the input, not a large neutral RGB sum.
vec3 cb1_cm4_rgb(vec3 rgb, vec2 change, vec3 n, vec3 q, vec3 w)
{
    vec3 d = vec3(dot(change, vec2(0.0975689, 0.205226)), dot(change, vec2(-0.113876, 0.133217)),
                  dot(change, vec2(0.0326151, -0.676887)));
    d += vec3(dot(q, vec3(-4.849e-7, -6.7e-9, 4.916e-7)), dot(q, vec3(2.0352e-6, -2.4116e-6, 3.764e-7)),
              dot(q, vec3(1.033e-7, 1.135e-7, -2.168e-7)));
    d = clamp(d, vec3(1e-30) - q, vec3(1.0) - q);
    vec3 dw = -(vec3(1.0) - w) * cb1_cm4_expm1((32.0 / 2523.0) * cb1_cm4_log1p(d / q));
    float a = 21.0 / 128.0, b = 2392.0 / 128.0;
    vec3 delta = n * cb1_cm4_expm1((16384.0 / 2610.0) * (cb1_cm4_log1p(-dw / max(vec3(a) - w, vec3(1e-30))) -
                                                       cb1_cm4_log1p(b * dw / (vec3(a) + b * w))));
    mat3 residual = mat3(mp.ex_cm4_residual[0].xyz, mp.ex_cm4_residual[1].xyz, mp.ex_cm4_residual[2].xyz);
    return fma(mp.ex_cm4_lms_rgb[2].xyz, vec3(delta.b), fma(mp.ex_cm4_lms_rgb[1].xyz, vec3(delta.g),
               fma(mp.ex_cm4_lms_rgb[0].xyz, vec3(delta.r), rgb + residual * rgb)));
}
vec3 map_ex_cm4(vec3 colour)
{
    vec3 rgb = colour * 203.0;
    float peak = mp.ex_cm4_sop.w;
    vec4 sop = mp.ex_cm4_sop, shape = mp.ex_cm4_shape, flags = mp.ex_cm4_flags;
    if (flags.x != 0.0) {
        vec3 x = clamp(rgb / peak * sop.x + sop.y, 0.0, 1.0);
        if (sop.z != 1.0)
            x = pow(x, vec3(sop.z));
        rgb = peak * x;
    }
    if (flags.y != 0.0 || flags.z != 0.0) {
        bool gray = rgb.r == rgb.g && rgb.g == rgb.b;
        if (flags.y != 0.0) {
            float Y = gray ? rgb.r : dot(rgb, mp.ex_cm4_luma.xyz);
            if (Y > 0.0) {
                float x = clamp(Y / peak, 0.0, 1.0);
                float a = pow(x, shape.x), b = pow(1.0 - x, shape.x), v = peak * a / (a + b);
                rgb = gray ? vec3(v) : rgb * (v / Y);
            }
        }
        if (flags.z != 0.0) {
            float Y = gray ? rgb.r : dot(rgb, mp.ex_cm4_luma.xyz);
            if (Y > 0.0) {
                float x = clamp(Y / peak, 0.0, 1.0), t = clamp((x - 0.5) / 0.5, 0.0, 1.0);
                float v = peak * clamp(x + shape.y * x * t * t * (3.0 - 2.0 * t), 0.0, 1.0);
                rgb = gray ? vec3(v) : rgb * (v / Y);
            }
        }
    }
    if (flags.w != 0.0 && max(rgb.r, max(rgb.g, rgb.b)) - min(rgb.r, min(rgb.g, rgb.b)) > 1e-12) {
        vec3 lms, q, u;
        vec3 ipt = cb1_cm4_ipt(rgb, lms, q, u);
        vec2 authored = ipt.yz;
        if (length(ipt.yz) >= 1e-7) {
            float z = clamp(ipt.x / cb1_cm4_pq(vec3(peak)).x, 0.0, 1.0);
            float primary_log = log(2.0) * (shape.w + shape.z * (2.0 * z - 1.0));
            // (no secondary trims: g 0, turn 0)
            float gm = cb1_cm4_expm1(vec3(primary_log)).x;
            vec2 change = vec2(gm * authored.x, gm * authored.y);
            rgb = cb1_cm4_rgb(rgb, change, lms, q, u);
        }
    }
    return rgb / 203.0;
}

// The display's linear light (1 = 203 cd/m2, its primaries) of a sample
// before the output's tail (dv_map.c expert_display); black: signal black.
vec3 map_ex_display(vec3 nl, out bool black)
{
    uint f = mp.ex_flags;
    vec3 lin = max(map_m3(mp.src_lms2rgb, map_pq_eotf_sdr(nl)), 0.0) * (10000.0 / 203.0);
    black = all(lessThanEqual(lin, vec3(0.0)));
    if (black && (f & 64u) != 0u && (f & 128u) == 0u)
        return vec3(0.0);
    vec3 c;
    if ((f & 2u) != 0u)
        c = map_m3(mp.ex_fast, lin);
    else {
        vec3 ipt = map_m3(mp.lms2ipt, map_pq_oetf_sdr(map_m3(mp.rgb2lms, lin) * (203.0 / 10000.0)));
        if ((f & 1u) != 0u) {
            float i0 = ipt.x;
            ipt.x = map_ex_tone(i0);
            float h0 = ((i0 - 6.0) * i0 + 9.0) * i0, h1 = ((ipt.x - 6.0) * ipt.x + 9.0) * ipt.x;
            ipt.yz *= ipt.x > 0.0 && h0 > 0.0 ? min(i0 / ipt.x, h1 / h0) : 0.0;
        }
        if ((mp.flags & 8u) != 0u)
            ipt = map_gamut_lookup_exact(ipt);
        c = map_m3(mp.lms2rgb, map_pq_eotf_sdr(map_m3(mp.ipt2lms, ipt)) * (10000.0 / 203.0));
    }
    if (black && (f & 128u) != 0u)
        c = vec3(0.0);
    if ((f & 4u) != 0u)
        c = map_m3(mp.ex_basis, c);
    if ((f & 8u) != 0u) {
        if ((f & 16u) != 0u)
            c = map_m3(mp.ex_to_trim, c);
        c = map_ex_cm4(c);
        if ((f & 16u) != 0u)
            c = map_m3(mp.ex_from_trim, c);
    }
    // cb1_hdr10_expert_trim
    float cap = mp.ex_chroma.z;
    c = clamp(c, 0.0, cap);
    if ((f & 32u) != 0u) {
        float Y = dot(c, mp.ex_luma.xyz);
        if (Y > 0.0)
            for (int k = 0; k < 3; k++)
                if (c[k] > 0.0)
                    c[k] *= pow((1.0 + mp.ex_chroma.x) * c[k] / Y, mp.ex_chroma.y);
        c = clamp(c, 0.0, cap);
    }
    return c;
}

// LLDV: the display's light (0..1 of its peak) to the carrier's BT.2020 PQ
// R'G'B' (dvbridge_pack_player_led_422's lldv_matrix, clamp, scale, PQ)
vec3 map_lldv_encode(vec3 v)
{
    return map_pq_oetf_sdr(clamp(map_m3(mp.ex_out, v), 0.0, 1.0) * (mp.ex_scale.y * (203.0 / 10000.0)));
}

// ... and back, for a sample the overlay is blended over (the display's
// gamut inside BT.2020: lldv_matrix's clamp left it as it was)
vec3 map_lldv_decode(vec3 rgb)
{
    return map_m3(mp.ex_out_inv, map_pq_eotf_sdr(rgb) * (10000.0 / 203.0 / mp.ex_scale.y));
}

// Expert: the nonlinear source to the output's BT.2020 PQ R'G'B' (LLDV's
// before the overlay; HDR10's tail is reference_output's)
vec3 map_expert(vec3 nl)
{
    bool black;
    vec3 c = map_ex_display(nl, black);
    if (MAP_EXPERT == 2u)
        return map_lldv_encode(c * mp.ex_scale.x);
    vec3 t = map_m3(mp.ex_out, c);
    vec3 rgb = mix(map_pq_oetf_sdr(clamp(t * (203.0 / 10000.0), 0.0, 1.0)), vec3(0.0), lessThanEqual(t, vec3(0.0)));
    if (black && (mp.ex_flags & 64u) != 0u)
        rgb = vec3(0.0);
    return min(rgb, vec3(mp.ex_scale.z));
}
#endif
#endif

// the nonlinear source to the output's PQ R'G'B' (SDR: the display's
// R'G'B'); the returned bits say which way each clamp and branch went
// (dvvk_map_rgb; not for SDR)
uint map_rgb(vec3 nl, out vec3 rgb)
{
    uint regime = 0u;
#ifdef MAP_EXPERT_ID
    if (MAP_EXPERT != 0u) {
        rgb = map_expert(nl);
        return regime;
    }
#endif
#ifdef MAP_SDR_ID
    if (MAP_SDR == 2u) {
        rgb = map_sdr(max(map_m3(mp.src_lms2rgb, map_hlg(nl)), 0.0));
        return regime;
    }
    if (MAP_SDR == 1u) {
        rgb = map_sdr(max(map_m3(mp.src_lms2rgb, map_pq_eotf_sdr(nl)), 0.0));
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
// DVVK_MAP_BT2020 (flags 64): the layer's colour (premultiplied sRGB, its
// codes those of a BT.709 display) as the BT.2020 display's codes of the
// same light, through the display's transfer (dv_map.c dvvk_map_layer_bt2020)
vec4 map_sdr_layer_bt2020(vec4 g)
{
    const mat3 m = mat3(0.6274038959, 0.0690972894, 0.0163914389, 0.3292830384, 0.9195403951, 0.0880133079,
                        0.0433130657, 0.0113623156, 0.8955952532);
    vec3 lin = pow(g.rgb / g.a + mp.out_trc.w, vec3(1.0 / mp.out_trc.z));
    return vec4(clamp(pow(m * lin, vec3(mp.out_trc.z)) - mp.out_trc.w, 0.0, 1.0) * g.a, g.a);
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
