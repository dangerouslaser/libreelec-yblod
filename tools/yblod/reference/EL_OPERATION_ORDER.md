# Enhancement-layer operation order

The public reference supports **resample coded EL, then inverse-quantize**.
The fractional sign reversal we observed is not evidence to reverse that order.
Order, sampling phase and transport rounding are separate questions.

## Primary-source evidence

[ETSI GS CCM 001 V1.1.1](https://www.etsi.org/deliver/etsi_gs/CCM/001_099/001/01.01.01_60/gs_ccm001v010101p.pdf)
provides the following evidence (printed page numbers):

- Clause 4, Note 1, p.11: input resampling precedes composition; resampling is
  explicitly nonnormative.
- Clause 5.2.2, pp.12–13: composer BL/EL inputs have matching dimensions and
  sample phases, with 8/10-bit samples.
- Clauses 5.4.3.1–5.4.3.3, pp.20–21: inverse quantization consumes that EL array;
  reconstruction adds the resulting residual to mapped BL.
- Informative Annex B.3, p.37: resampling takes coded `EL_bit_depth` input and
  returns the same data type, using integer-rounded filters. This is not an
  example of resampling already inverse-quantized corrections.

Together these support the coded-first public reference architecture. They do
not establish modern licensed Dolby implementation details, an obligatory
resampling filter, or a fractional Y416-to-composer rule. Annex B's uint16 bounds
also should not be confused with a demonstrated nominal-depth clamp.

## Deterministic order discriminator—proposal only

Use constant mapped BL 32768 and an explicitly artificial arithmetic fixture:
`b=10, D=23, O=512, S=2048, T=0, M=1048576`. Its integer inverse quantization
gives `N(512)=0`, `N(513)=8`. Define a simple linear sampler
`L_w(a,b)=(1−w)a+wb`. This is a declared mathematical fixture, **not a claim
about Intel or Annex B filter weights**. For coded endpoints 512/513:

| Declared calculation, correction units | w=¼ | w=½ | w=¾ |
| --- | --- | --- | --- |
| Inverse first: `L_w(N(512),N(513))` | 2 | 4 | 6 |
| Coded first, hypothetical literal continuation | −4 | 0 | 4 |
| Coded first, explicit floor to native integer | 0 | 0 | 0 |
| Coded first, explicit nearest-half-up | 0 | 8 | 8 |
| Coded first, explicit nearest-ties-even | 0 | 0 | 8 |

The literal row follows `16(s−512)−8 sign(s−512)` away from neutral. It is a
hypothetical fractional extension, not the integer standard or measured GPU
floating-point arithmetic. The cap is nonbinding here. Swapping endpoint 513
for 511 supplies a negative control: inverse-first corrections are −2/−4/−6,
while the literal row becomes +4/0/−4. Constant neutral is an additional control.

These independently derived values show that the operations do not commute.
Observe the correction **before** final composition rounding, which can hide
differences. Then examine the separately declared Annex B integer example and
the actual shader sampling contract, without silently replacing either with
the linear fixture. Metadata cap/floor tests are separate controls. No result
chooses a rounding winner or infers correctness from SK4 similarity.

## Preserve the offload contract

Coded-first processing keeps the existing QuickSync scaling placement available;
backend choice remains explicit and can include equivalent AMD support.
A hypothetical inverse-first route must instead specify a lossless carrier for
signed corrections, their units and width. Clause 5.4.3.2 describes a residual
width of 17 including sign; this is **not a Y416 packed-storage definition**.
Do not discard negative values or presume the existing unsigned native-10/Q6
carrier and 12-bit surface precision can transport those corrections losslessly.
Neither this note nor the fixture changes production code or playback policy.

The separately checked [Annex B known answers](ANNEX_B_RESAMPLER_VECTORS.md)
pin a tiny two-pass example, including edge repetition and rounding between
passes. Those answers are not the declared bilinear experiment above.
