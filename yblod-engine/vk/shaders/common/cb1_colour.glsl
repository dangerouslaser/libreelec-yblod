// Native CB1 colour arithmetic, shared without changing operation order.
vec3 cb1_mul(uint at, vec3 v)
{
    vec3 r = vec3(coeff[at], coeff[at + 1u], coeff[at + 2u]) * v.x;
    r = r + vec3(coeff[at + 3u], coeff[at + 4u], coeff[at + 5u]) * v.y;
    r = r + vec3(coeff[at + 6u], coeff[at + 7u], coeff[at + 8u]) * v.z;
    return r;
}

float cb1_lut(sampler2D lut, float v) { return textureLod(lut, vec2(v, .5), 0.0).r; }

vec3 cb1_gui_pq(vec3 v)
{
    vec3 l = vec3(cb1_lut(subtitle_degamma, v.r), cb1_lut(subtitle_degamma, v.g), cb1_lut(subtitle_degamma, v.b));
    vec3 m = vec3(.6274, .0691, .0164) * l.x;
    m = m + vec3(.3293, .9195, .0880) * l.y;
    m = m + vec3(.0433, .0114, .8956) * l.z;
    return vec3(cb1_lut(subtitle_pq, m.r), cb1_lut(subtitle_pq, m.g), cb1_lut(subtitle_pq, m.b));
}

vec3 cb1_matrix_pq(vec3 q)
{
    q = pow(max(q, 0.0), vec3(1.0 / (2523.0 / 32.0)));
    q = max(q - vec3(3424.0 / 4096.0), 0.0) / (vec3(2413.0 / 128.0) - vec3(2392.0 / 128.0) * q);
    q = cb1_mul(12u, pow(q, vec3(1.0 / (2610.0 / 16384.0))));
    q = pow(max(q, 0.0), vec3(2610.0 / 16384.0));
    q = (vec3(3424.0 / 4096.0) + vec3(2413.0 / 128.0) * q) / (vec3(1.0) + vec3(2392.0 / 128.0) * q);
    return pow(q, vec3(2523.0 / 32.0));
}
