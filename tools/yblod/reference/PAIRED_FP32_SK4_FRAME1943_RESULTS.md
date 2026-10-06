# FP32 and integer output compared with SK4 frame 1943

The faster FP32 composer leaves our measured difference from the SK4
essentially unchanged on this frame. It does not establish better or worse
colour accuracy. This comparison measures saved output codes, not the picture
displayed by the TV.

Both our integer reference and the FP32 output used the same native C colour
conversion, target matrices, direct conversion policy, active picture area,
and chroma expansion. The integer reference is our own engine, not original
CroqueMr playback.

## Difference from the SK4

Values are 12-bit transport codes. I, P and T identify the three transport
components; they are not direct measurements of displayed brightness or colour.
Lower mean absolute or RMS error means closer agreement with this capture,
not proof of correct Dolby processing.

| Measurement | Integer | FP32 | FP32 minus integer |
| --- | ---: | ---: | ---: |
| I mean absolute error | 9.780931 | 9.781119 | +0.000188 |
| P mean absolute error | 4.971984 | 4.971224 | -0.000760 |
| T mean absolute error | 5.603209 | 5.603080 | -0.000129 |
| I RMS error | 16.144802 | 16.144859 | +0.000057 |
| P RMS error | 6.422221 | 6.421298 | -0.000923 |
| T RMS error | 6.903395 | 6.903272 | -0.000123 |
| Maximum I error | 119 | 119 | 0 |
| Maximum P error | 71 | 71 | 0 |
| Maximum T error | 81 | 81 | 0 |

All six saved captures produced identical comparison statistics, so their
minimum and maximum values equal the figures above. This demonstrates
repeatability of these saved comparisons. It does not verify that the SK4
capture driver synchronized its memory correctly.

## Differences introduced by FP32

Reconstructed source-plane differences were at most one code. After the shared
nonlinear colour conversion, final packed transport differences reached
three I codes, four P codes and three T codes. Those are different stages;
the one-code composer result must not be described as a one-code guarantee
for final HDMI transport.

| Packed component | Changed samples | Compared samples | Mean absolute FP32 difference | Maximum |
| --- | ---: | ---: | ---: | ---: |
| I | 9,433 | 6,178,560 | 0.001743 | 3 |
| P | 4,645 | 3,089,280 | 0.002178 | 4 |
| T | 2,872 | 3,089,280 | 0.001078 | 3 |

The native C colour conversion reproduced the historical NumPy conversion
exactly for the integer baseline, in both raw transport codes and packed bytes.
Colour-backend rounding therefore did not contaminate this paired comparison.

## Coverage and resource limits

This is one numbered Profile 7 FEL test frame with six saved SK4 captures. Its
historical linear preparation differs from current playback's cubic chroma
preparation and VA enhancement scaling. The result qualifies the composer
change on identical inputs, not the complete live playback pipeline, other
films, displayed colour accuracy, HDMI-wire fidelity or Dolby conformance.

Saved frame association, metadata checksums and transport matrices were checked.
Capture-driver DMA synchronization remains unverified. No fitted offsets,
changed matrices or correction intended to imitate the hardware were applied.

The CPU-only conversion and comparison job had a 512 MiB ceiling, no swap and
a one-core quota. Peak scoped memory was 426,176,512 bytes, about 406.4 MiB;
all memory-pressure and OOM event counters remained zero. These are offline
diagnostic resources, not engine-only playback memory or playback timings.
Playback performance is reported separately in
[FP32 playback comparison](FP32_PLAYBACK_COMPARISON.md).

## Reproduction and scalar evidence

[The scalar JSON results](PAIRED_FP32_SK4_FRAME1943_RESULTS.json) contain all
six paired comparisons, capture ranges and the colour-backend control. Film
pixels, RPU payloads, private source hashes and private paths are excluded.

`gpu_dump_colour_adapter.py` checks the native producer's source association,
matches prepared base planes and luma guide to the historical input hashes,
and unpacks every P010 enhancement sample to verify identical inputs. It
emits only reconstructed-plane stages from the actual GPU dump; it does not
invent or copy mapped, residual or intermediate colour results.

`run_paired_sk4_colour.py` converts integer and FP32 planes with the same
existing native C colour library, then compares all six saved captures.
`sanitize_paired_sk4.py` exports scalar evidence. Keep these helpers in the
same directory; their `--help` commands list explicit input paths. The adapter
currently accepts only the qualified 3840 by 2160, 12-bit diagnostic layout.

Run the comparison inside a fresh scope with `MemoryMax=512M`,
`MemorySwapMax=0` and `CPUQuota=100%`, and set `OPENBLAS_NUM_THREADS=1` and
`OMP_NUM_THREADS=1`. The driver checks those limits before work and verifies
memory events after each phase. Saved captures and extracted private fixtures
must be supplied separately; this tooling does not operate a player or TV.

Six focused CPU helper tests passed. From this directory, run
`python3 -m unittest -v test_paired_sk4_colour_helpers.py`. They check JSON
file and size guards, the adapter's fixed geometry gate, resource limits and
scalar-only export. They are not substitutes for the completed real GPU and
paired capture tests summarized above.
