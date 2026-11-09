// Shared helpers, 1:1 with yblod's opencl_kernels.cl. Integer only.
#extension GL_EXT_shader_16bit_storage : require
#extension GL_EXT_shader_explicit_arithmetic_types_int16 : require
#extension GL_EXT_shader_explicit_arithmetic_types_int64 : require

int edge(int p, uint n) { return clamp(p, 0, int(n) - 1); }

// rounded(): division rounding of the OpenCL kernels, saturated to ushort.
uint rounded(int v, int d)
{
    v += d / 2;
    v = v >= 0 ? v / d : -((-v + d - 1) / d);
    return uint(clamp(v, 0, 65535));
}

// A 16-bit UNORM sample as yblod recovers it: x65535, round to nearest even.
uint unorm16(float v) { return uint(roundEven(v * 65535.0)); }
uint unorm8(float v) { return uint(roundEven(v * 255.0)); }

#ifdef ERROR_OR
// --- direct P010 input (opencl_kernels.cl DV_INPUT_P010) ---------------------
// input_sample(): one channel of an R16/RG16 UNORM plane, exact 10-bit code;
// nonzero low bits flag error bit 0 (the caller passes the error buffer's
// atomic through ERROR_OR, a macro each shader defines).
uint input_sample(sampler2D src, uint x, uint y, uint channel)
{
    vec4 raw = texelFetch(src, ivec2(x, y), 0);
    uint q = unorm16(channel == 0u ? raw.r : raw.g);
    if ((q & 63u) != 0u)
        ERROR_OR(1u);
    return q >> 6;
}

uvec2 input_uv(sampler2D src, uint x, uint y)
{
    vec2 raw = texelFetch(src, ivec2(x, y), 0).rg;
    uvec2 q = uvec2(unorm16(raw.r), unorm16(raw.g));
    if (((q.x | q.y) & 63u) != 0u)
        ERROR_OR(1u);
    return q >> 6;
}

uvec2 phase_uv_sample(sampler2D src, uint x, int row, uint h, uint method)
{
    uint y = uint(edge(row, h));
    if (method == 2u)   // none: the decoded chroma (CB1's Master Reference)
        return min(input_uv(src, x, y), uvec2(1023u));
    ivec2 v = ivec2(0);
    if (method == 0u)
        v = 3 * ivec2(input_uv(src, x, y)) + ivec2(input_uv(src, x, uint(edge(int(y) + 1, h))));
    else {
        const int taps[4] = int[4](-9, 111, 29, -3);
        for (int k = 0; k < 4; ++k)
            v += taps[k] * ivec2(input_uv(src, x, uint(edge(int(y) + k - 1, h))));
    }
    return min(uvec2(rounded(v.x, method != 0u ? 128 : 4), rounded(v.y, method != 0u ? 128 : 4)), uvec2(1023u));
}

#endif

// luma_equal/luma_pair's final step: Q16 mapping + residual -> 12-bit.
uint recon12(int64_t total) { return uint(clamp(total > -8 ? (total + 8) / 16 : int64_t(0), int64_t(0), int64_t(4095))); }
bool overflows32(int64_t total) { return total > int64_t(2147483647) || total < int64_t(-2147483647) - 1; }

// The EL's 2x upsampling, dvvk_plan.el_method: EL_ANNEXB the CCM Annex B
// filters (8-tap horizontal, 4-tap vertical luma), EL_BILINEAR 2-tap linear
// interpolation at the same sample phases: even columns pass through and odd
// ones are midway between their two EL neighbours; luma rows lie a quarter
// of an EL row above (even) and below (odd) their EL row. The EL chroma's
// vertical step (64/192 after the chroma phase filter) is 2-tap already and
// the same for both. Integer only, rounded as rounded() rounds.
#define EL_ANNEXB 0u
#define EL_BILINEAR 1u
// the odd (interpolated) column between EL samples a (left) and b (right)
uint el_bilinear_mid(uint a, uint b) { return (a + b + 1u) / 2u; }
// a row a quarter of an EL row from `near` towards `far`
uint el_bilinear_quarter(int near, int far) { return rounded(3 * near + far, 4); }

// horizontal(): the EL's 2x upsample (even samples passed through);
// HORIZONTAL(name, buffer) defines one for a given source buffer.
#define HORIZONTAL(NAME, BUF)                                                              \
    uint NAME(uint w, uint x, uint y, uint method)                                         \
    {                                                                                      \
        uint ix = x / 2;                                                                   \
        if ((x & 1u) == 0u)                                                                \
            return uint(BUF[y * w + ix]);                                                  \
        if (method == EL_BILINEAR)                                                         \
            return el_bilinear_mid(uint(BUF[y * w + ix]), uint(BUF[y * w + uint(edge(int(ix) + 1, w))])); \
        const int taps[8] = int[8](22, 94, -524, 2456, 2456, -524, 94, 22);                \
        int v = 0;                                                                         \
        for (int k = 0; k < 8; k++)                                                        \
            v += taps[k] * int(BUF[y * w + uint(edge(int(ix) + k - 3, w))]);               \
        return rounded(v, 4096);                                                           \
    }
