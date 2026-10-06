# Normalized P010 texture ingestion checkpoint

This separate diagnostic takes five resident normalized textures instead of a
CPU-expanded per-sample SSBO. It uses integer-coordinate `texelFetch`, restores
the 16-bit stored word by rounding, rejects fractional Q6 input, and feeds the
unchanged scalar-streamed integer composer. No new chroma or guide filter is used.

| Binding | Format / stored values | Dimensions |
|---|---|---|
| 0 | BL Y, R16 normalized, raw P010 Q6 words | W × H |
| 1 | BL Cb/Cr, RG16 normalized, raw P010 Q6 words | W/2 × H/2 |
| 2 | Explicit prepared guide, R16 normalized, native 10-bit codes | W/2 × H/2 |
| 3 | EL Y, R16 normalized, raw P010 Q6 words | W × H |
| 4 | EL Cb/Cr, RG16 normalized, raw P010 Q6 words | W/2 × H/2 |

Luma reconstruction uses BL Y with zero Cb/Cr inputs. Chroma reconstruction uses
the supplied guide and both BL chroma components. Only enhancement-enabled
10-bit BL/EL metadata is admitted at this checkpoint. Disabled enhancement and
fractional/raw Y416 are not silently substituted or rounded into this route.

This checkpoint uploads fixture planes once; it **does not import live VAAPI
surfaces**. Its normalized R16/RG16 sampling ABI is intended to be independently
validated with live exported surfaces later. Native BL fixture planes are packed
to P010 once; the guide remains a separate already-prepared plane.

## Completed prepared-frame gates

[Public scalar evidence](results/native-gpu-texture-streamed-frame-checkpoint-20261005a.json)
records one cohort per prepared frame. Separate CPU preflights completed first;
each GPU cohort checked all 49,766,400 stage values exactly through 48 GPU batches
and 191 CPU oracle subchunks before warm timing.

| Frame | Three resident warm whole-pass times | Combined plane preparation / completed upload |
|---|---|---|
| 2296 | 51.583, 49.507, 45.837 ms | 38.131 ms wall / 33.175 ms CPU |
| 1406 | 51.690, 49.117, 42.332 ms | 29.227 ms wall / 25.570 ms CPU |

The input preparation/upload cost is excluded from warm execution and is included
in cold setup: 174.763 ms and 54.677 ms respectively. It includes host packing,
allocation, upload API calls and completion wait; it is not isolated GPU transfer
time. Context/compiler/cache effects also affect cold setup. Warm CPU times were
1.6–3.0 ms. Peak charged memory was 259,481,600 bytes under 512 MiB, with no swap
or memory events and unchanged Kodi identity.

Warm passes still dispatch 48 batches, wait once per batch and read only the
final 41,984-sample suffix. Full equality is the separate untimed gate. These
warm resident results are not directly comparable to former per-frame packing
diagnostics and do not establish 24-fps movie playback or per-new-frame costs.
There is no owned full reconstructed output image yet or Kodi integration.

Eighteen normal and eighteen UBSan host tests passed, including exhaustive
float32-model / actual C helper recovery of 65,536 words, coordinate boundaries,
atomic helper rejection, inherited malformed inputs and complete-oracle/suffix
guards. These do not prove an arbitrary imported texture's format or ownership.
The VM full-frame gates validate this particular driver and uploaded ABI.

Khronos defines normalized texture conversion and texture fetch behavior in the
[OpenGL 4.3 specification](https://registry.khronos.org/OpenGL/specs/gl/glspec43.core.pdf).
The next backend will borrow validated input textures in a caller-owned context,
write owned R16UI reconstructed planes, report a frame error flag and use three
full-plane dispatches with one completion fence. It must retain explicit guide,
scale, association and metadata-width contracts before becoming a playback path.
