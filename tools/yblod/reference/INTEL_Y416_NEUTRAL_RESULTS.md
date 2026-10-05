# Intel Y416 observations near neutral

The small synthetic test now reaches fractional values that our earlier saved
surfaces did not. This establishes a useful diagnostic input, **not the correct
Dolby reconstruction policy**. No playback default or precision policy changed.

Evidence: [measured surfaces and invocation records](results/intel-y416-near-neutral-small-v11.json)
and [explicit arithmetic alternatives](results/intel-y416-near-neutral-precision-v11-v2.json).
The latter is reproducible with `hardware_y416_neutral_precision.py`.

The separately approved [production-size checkpoint](results/intel-y416-near-neutral-large-v11.json)
and its [arithmetic alternatives](results/intel-y416-near-neutral-large-precision-v11.json)
are now complete too. They demonstrate why the small result must not be
extrapolated unchanged to 4K.

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

## Production-size checkpoint

Two 1920×1080 inputs—neutral and the same one-code Y step—were processed into
3840×2160 Y416 with the same flags. Native-size Y416 was explicitly omitted.
All four P010 copy/native identity gates passed before four scaled Y416 jobs;
**eight jobs** total, stable repeat hashes and 288.72 MiB of retained raw files.
All 26 archived input/output/log files were independently hash-verified on
Ollie. Standard-library little-endian decoding independently checked every word
of all 16 stored centre-row/column profiles for the two first-repeat surfaces.

Neutral and inactive colour words remained exactly 32768. The Y step now
produced raw word **32784 (+¼ native code), in 2160 samples**, rather than the
small case's −¼/+½ values. The full set of Y words was
`32768, 32784, 32816, 32832, 32848`. The following centre-row deltas use the
declared input step at the native midpoint, with output position measured
relative to twice that index; no fitted registration was applied:

| Output position | −3 | −2 | −1 | 0 | +1 | +2 |
| --- | --- | --- | --- | --- | --- | --- |
| Small Y-step raw delta | −16 | 0 | +32 | +64 | +80 | +64 |
| Production-size Y-step raw delta | 0 | 0 | +16 | +48 | +80 | +64 |

All six submitted VPP jobs had positive `video-enhance` accounting deltas and
zero render deltas. This is measured per-client engine activity, not proof of
a separately identifiable scaling unit or a portable hardware-engine promise.
Alpha was observed at 65472, versus 65280 in the small scaled surfaces; it was
retained, not interpreted as colour or forced to an assumed opaque value.

The production-size runner took 10.854 seconds offline. Python peak RSS was
27,468 KiB, but actual kernel cgroup peak was **505,266,176 bytes (481.86 MiB)**
under the unchanged 512 MiB limit. Job swap and all max/OOM events were zero.
The cgroup includes child processes and charged file cache, not just Python
working memory. This peak is close to the limit: future large experiments
need a reduced output/cache-retention strategy, not a higher memory cap.
No files were deleted. The following subsection records the subsequent,
separately approved opt-in checkpoints.

### Separately approved opt-in cache checkpoints

The runner now offers `release_cache=True` / `--release-cache`; it is not the
default. It validates and analyses the first repeat before generating the
second, then requests per-file cache release after required verification.
Helper failures stop the run; evidence is never deleted.

First, the [small opt-in checkpoint](results/intel-y416-near-neutral-small-cache-release-v11.json)
completed 24 jobs and 52 successful advice events. All four input records,
24 output hashes and every result—including complete raw profiles, word sets,
near-neutral counts and repeat hashes—matched the original small cohort exactly.
Only then was the [production opt-in checkpoint](results/intel-y416-near-neutral-large-cache-release-v11.json)
approved: eight jobs, 18 successful advice events, both input records, eight
output hashes and every result exactly matching the original production cohort.
The same P010 identity gates still preceded every Y416 stage.

The production opt-in kernel cgroup peak was **271,278,080 bytes (258.71 MiB)**,
versus the prior **481.86 MiB**, under the unchanged 512 MiB/no-job-swap cap.
This is a pair of measured offline observations, not a controlled benchmark
or guaranteed future bound. Swap/max/OOM events were zero. For each of the four
4K output advice events, sampled file charge decreased by 66,355,200 bytes,
the packed output size. Per-job memory statistics remain in the report; advice
is nonbinding and does not prove per-page eviction.

The small archive's 76 evidence files plus both executed sources, and the
production archive's 26 evidence files plus both sources, were hash-verified
on Ollie; VM copies remain. Runner SHA-256 was
`ea47acd67f5e8edd1d3231e4c8a9de0875fd2dc583bf03d393160b8d1fded320`;
cache helper SHA-256 was
`35707b380ccaa4db43ca0d5d791aa84ec82af7db19698fbf5fd53a82932435d0`.
No image accuracy, phase, metadata or fractional policy changed. See the
[cache handling evidence and constraints](FILE_CACHE_RELEASE_PLAN.md).

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

The production-size checkpoint above is complete; it did not choose a policy
or compare against an empirical RPU/capture target. Next, an explicit offscreen
shader diagnostic can observe the sampled EL value
after its declared coordinate shift and normalization, and the correction
before colour conversion, using a constant mapped base layer. Integer anchors,
neutral and these measured fractional words would discriminate implementation
behavior without fitting to SK4. Even that would establish what our shader
does—not which fractional rule licensed hardware implements.
