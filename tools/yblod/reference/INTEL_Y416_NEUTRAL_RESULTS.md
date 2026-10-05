# Intel Y416 observations near neutral

The small synthetic test now reaches fractional values that our earlier saved
surfaces did not. This establishes a useful diagnostic input, **not the correct
Dolby reconstruction policy**. No playback default or precision policy changed.

Evidence: [measured surfaces and invocation records](results/intel-y416-near-neutral-small-v11.json)
and [explicit arithmetic alternatives](results/intel-y416-near-neutral-precision-v11-v2.json).
The latter is reproducible with `hardware_y416_neutral_precision.py`.

## What was measured

Four 64×64 P010 inputs: neutral 512, a Y horizontal 512→513 step, a Cb vertical
512→511 step, and a one-column Cr 513 stripe on a 512 background. The probe
used default quality, BT.2020 reduced range, LEFT input chroma, unspecified
output chroma, and explicit Y416 allocation diagnostics. Y416 was allocated
successfully but was not advertised in the probed output-surface list; there
was no format fallback.

All eight P010 copy/native identity gates completed before any Y416 job.
Native-size and 128×128 Y416 outputs were each repeated twice: **24 sequential
jobs**, all successful, with identical repeat hashes. The neutral colour words
remained exactly 32768. Native outputs in these particular nonconstant cases
contained only integer-code anchors; this does not establish a universal rule
for native-size 4:2:0→4:4:4 conversion.

The scaled outputs contained these near-neutral colour words:

| Pattern/channel | Raw-word delta from 32768 | Native-code equivalent | Samples |
| --- | --- | --- | --- |
| Y step / Y | −16, +32 | −¼, +½ | 128 each |
| Cb step / Cb | −32 | −½ | 128 |
| Cr stripe / Cr | +16, +32 | +¼, +½ | 256 each |

The denominator 64 describes this declared Intel native-10-bit route; it is
not a universal Y416 format property. Every raw word and alpha value was
preserved. These observations do not demonstrate useful precision at every
one-word (1/64-code) increment.

The job had a 512 MiB memory limit and no job swap. Actual kernel cgroup peak
was **48,582,656 bytes (46.33 MiB)**, with zero swap and zero OOM events.
Python peak RSS was 23,716 KiB. The 0.262-second runner interval is an offline
diagnostic duration, not a playback performance measurement. All 76 archived
input/output/log files were subsequently hash-verified on Ollie.

Engine-counter deltas were zero in this small cohort. They therefore identify
neither the engine used nor a hardware scaling path. These 64→128 observations
must not be assumed to describe production-size 1920→3840 processing.

## What the alternatives show—and do not show

The comparison deliberately uses an artificial arithmetic fixture:
`b=10, D=23, O=512, S=2048, T=0, M=1048576`. Those scalar values match the
previously verified frame-2296 coefficient subset, but this experiment does
not use movie metadata or claim a complete real-frame metadata contract.
The residual cap is nonbinding in this near-neutral sweep.

For an observed +¼-code word, all three declared integer quantizers produce
zero correction, while the hypothetical literal extension produces −4
correction units. At −¼, floor produces −8, both nearest alternatives zero,
and the literal extension +4. At +½, half-up produces +8 but ties-even zero.
These are materially different calculations, **not evidence that one wins**.

The literal extension's opposite-sign corrections are source-algebra behavior,
not a demonstrated licensed Dolby rule or an accuracy failure. Its diagnostic
implementation omits the shader noise guard; the inspected ideal guard is
about 1/128 of one raw word near neutral, far narrower than these measured
16/32-word differences. This is not a measurement of GPU floating-point
evaluation. See [the shader arithmetic audit](NLQ_SHADER_AUDIT.md).

The public integer composer and informative Annex B example do not establish
how arbitrary fractional Y416 words should enter reconstruction. Moreover,
the playback path's later `shift_x=-0.5` and texture interpolation can change
the value actually supplied to NLQ. Raw surface words are not automatically
shader input samples. Layer registration, full metadata semantics, transport
precision and licensed fractional handling remain separate uncertainties.

## Next non-fitting check

First repeat only neutral and the one-code Y step at production size, retaining
the same declared flags and identity gates. Two inputs with native Y416 omitted
would require eight jobs and about 288.72 MiB of raw files, within the runner's
300 MiB cap. This larger cohort has not been run. Compare raw
values and profiles directly, without adjusting phase or coefficients.

Then an explicit offscreen shader diagnostic can observe the sampled EL value
after its declared coordinate shift and normalization, and the correction
before colour conversion, using a constant mapped base layer. Integer anchors,
neutral and these measured fractional words would discriminate implementation
behavior without fitting to SK4. Even that would establish what our shader
does—not which fractional rule licensed hardware implements.
