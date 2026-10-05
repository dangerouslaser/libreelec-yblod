# First Intel EL-scaling measurements

Follow-up: [production-size controls](INTEL_LARGE_SCALING_RESULTS.md) show
different engine-class routing and siting responses. Do not extrapolate the
small-surface conclusions below to1920x1080→3840x2160 processing.

Measured on2026-10-05 using private GPU surfaces in the LibreELEC VM on Petunia.
No Kodi/display/HDMI settings changed; Kodi remained active. The SK4/TV were not
used. These are native-code synthetic tests, not rendered movie comparisons.

## Environment and evidence

- LibreELEC yblod-0.1-direct-test4, kernel7.2.8, glibc2.44, Python3.14.8.
- Intel PCI8086:9a49, iHD26.3.5 `(3de4708)`, libva2.24.0/API1.24.
- Probe binary SHA256 `b46e1ad061e21b02a1aef1929ab9635bf1ca090148f9aeaf3a8ac53b5ba01c62`.
- Probe C source SHA256 `585b92818bc76483014d81a86c23d92d309b7d68a7e7807e5bfc84e47c6bda43`.
- iHD library SHA256 `fca0ac8e50a27e9278b8ad17b488dd662af34eb5cd48fe3670e7d7971b3d7d7f`.
- libva library SHA256 `f7238c347148567131476e74443e493c9ee7b9729f1da875af20828ce1d93c61`.

The [full synthetic report](results/intel-scaling-64-v5.json) records binary,
tool/input pins, all112 commands, invocation metadata, log hashes, raw-output
hashes, identity results, independent-reference scores and repeat stability.
Actual per-job logs/downloads remain in the fresh private VM test directory;
no movie/capture files are published. Source and generators are reproducible.

The [exact-ramp report](results/intel-affine-phase-v5c.json) separately records
32 invocations:4 ascending/descending fields, each copied and submitted through
default1:1VPP, then enlarged twice under each of3 mode requests.

## General64x64→128x128 results

All14 upload/readback copies and14 actual default-mode1:1VPP outputs are
byte-exact. This includes0,1,512,1023, distinct Cb/Cr tags and a single-code
step. There was no detected range remap, channel swap or precision loss in
these identity tests. Fast/HQ1:1 identity was not independently tested.

All84 enlargement invocations completed and repeated hashes match. Default,
fast and HQ requests produce byte-identical outputs for **every one of these
14 patterns**. This does not prove identical engines or algorithms on larger
surfaces. Successful submission does not identify the engine used.

Against the informative Annex-B CPU reference:

- All constant/tag/unit-step patterns match exactly.
- Horizontal ramps match exactly in the interior; one-code edge differences remain.
- Vertical staircase ramps differ by roughly one code in the interior.
- Alternating vertical rows differ substantially: mean absolute errors32.648438
  for Y and19.375 for Cb/Cr, with interior errors33 and20 respectively.
- Impulses and edges expose additional filter/border differences.
- The depth-overshoot stress has256 reference samples above1023. P010 cannot
  preserve those values; retain this labelled representational/filter divergence,
  not a perceived-quality score or evidence of a Dolby clamp.

## Exact affine controls isolate the sampling moments

Each component starts at its own base `B` and increases by exactly8 codes per
native x or y sample. Decreasing fields are exact mirrors. Values remain within
10bit range. Identity checks pass for all4 fields, repeats are stable, and the
three mode requests again produce identical output.

Away from edges, Annex B predicts horizontal `B+4m` and vertical `B-2+4m`.
These predictions are integers, so no half-code rounding ambiguity is involved.
Measured ascending vertical fields are:

| Plane | Even output row2n | Odd output row2n+1 | Difference from Annex B |
| --- | --- | --- | --- |
| Annex-B reference | B+8n−2 | B+8n+2 | baseline |
| Hardware Y | B+8n | B+8n+4 | +2 on both parities |
| Hardware Cb/Cr | B+8n | B+8n+2 | +2 on even,0 on odd |

Horizontal ascending/decreasing fields match the affine reference exactly.
Reversing the vertical field reverses the nonzero error to−2. This argues
against a fixed additive code bias and supports an effective sampling-moment
difference. It does **not** identify filter coefficients or prove Dolby geometry.

In logical input-plane coordinates, observed Y moments are `{0,1/2}` and
chroma moments `{0,1/4}`, versus reference vertical moments `{-1/4,1/4}`.
Chroma increments alternate2/6 instead of4/4; this is not one uniform shift.
Do not hide it with a fitted offset or assert that it causes the SK4 difference.
Physical layer registration and encoded chroma siting remain separate contracts.

## Independent input/output colour-position experiment

The [siting matrix report](results/intel-chroma-siting-v6b.json) adds102
synthetic invocations:6 transport copies and96 default VPP jobs spanning
four left/top-left declarations, native/2x sizes, six patterns and two repeats.
The V6 binary SHA256 is
`778453ce5edf78d1955f23c4e6e7ddf59e5ca41356e2ed53cb0ac3076f86ed64`;
its C source SHA256 is
`a47108893b2191d9ef10ef38f2dd7a082a71a190b5434b2d8aadb191e1584aa2`.
Same runtime/device as above; jobs remain sequential under512MiB/no-swap.

All copies are exact. Every1:1 job, including the cross-grid requests, is
also exact. Constants/channel tags stay exact at both sizes; repeated outputs
are stable and brightness is byte-identical across all four declarations.

For ascending vertical ramps at2x, interior differences from the unchanged
logical Annex-B first-moment reference are:

| Input request | Output request | Y even/odd error | Cb/Cr even/odd error | Cb/Cr increments |
| --- | --- | --- | --- | --- |
| left | left | +2/+2 | +2/0 | 2/6 |
| top-left | left | +2/+2 | +2/0 | 2/6 |
| left | top-left | +2/+2 | +2/−2 | 0/8 |
| top-left | top-left | +2/+2 | +2/−2 | 0/8 |

Descending ramps reverse the error signs. Horizontal ramps remain exact in
the measured interior. Changing the input declaration gives byte-identical
outputs for each fixed output declaration across the whole tested corpus.
Changing the output declaration affects vertical chroma but not brightness.
Thus there is a measurable output-control response; input-control response was
not observed in this path. This is not a universal claim about driver behaviour.

Neither setting gives reference4/4 chroma increments, and the Y logical
sampling-moment difference remains. A zero mean chroma error under top-left output masks
alternating+2/−2 errors; it is **not** improved accuracy. Identical bytes under
different input declarations represent different physical sample grids, not the
same physical picture. Reference differences remain diagnostics, not a Dolby
conformance verdict. No playback geometry is changed based on these results.

## Limits and next discriminating experiment

The main run takes10.327 seconds including subprocesses and scalar CPU scoring.
Reported self/child peak RSS is32,816 KiB, swap deltas0. It runs under a512MiB
hard cap with job swap disabled. This is not playback latency or throughput;
RSS is a process high-water mark, not total GPU/cgroup allocation.

Production-size slope controls are now measured in the linked follow-up.
Next distinguish output phase quantization/filter behaviour with full-size
mirrored horizontal and mode controls. The completed siting matrix does
not explain every filter coefficient or establish correct physical registration.
Matching one response by changing the declared output grid is **not** a
deployable fix.

Also verify actual video/graphics engine use before feeding a hardware result
into reconstruction. This checkpoint does not
change the faster production path, resolve SK4 colour differences, certify Dolby
accuracy, or establish AMD support.
