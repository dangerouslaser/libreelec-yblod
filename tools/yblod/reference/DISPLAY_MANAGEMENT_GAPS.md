# What still belongs to the player or the TV

2026-10-05; read-only source audit, not a playback measurement.

Our new colour engine can translate the reconstructed picture into an explicitly chosen output colour representation. That is **not the same as deciding how bright a particular TV should make it**. Those are two different jobs, and mixing them can apply an adjustment twice or apply none at all.

The inspected existing HDMI path is a standard, TV-led tunnel: the player reconstructs and packages the picture and its instructions; the TV is expected to adapt that picture to its own capabilities. A future player-led/LLDV path would need a separate, explicit display-adaptation contract. Changing the output label or matrices alone would not implement it.

## Ownership before implementation

| Job | New standalone engine | Inspected existing runtime / downstream owner |
|---|---|---|
| Reconstruct BL + EL from mapping/NLQ | Native integer foundation and prepared-input GPU diagnostic | Existing libplacebo float shader; its sampling/precision contract remains separate |
| Expand chroma / sample EL | Diagnostic operators only; no selected production filter | VAAPI plus texture sampling / libplacebo plane sampling |
| Decode source colour instructions and change colour coordinates | `native_colour` with explicit matrices, offsets, PQ policy and output quantization | libplacebo Dolby decode plus bridge packing conversion |
| Adapt brightness/colour to a particular display | Not implemented | TV in intended standard tunnel; generic libplacebo mapping for the distinct HDR10 fallback |
| Artistic display trims | Not applied by the new colour core | Existing tunnel serializes supported instruction blocks; actual TV interpretation is not measured here |
| Pack pixels, embed dynamic instructions, signal HDMI mode | Not implemented by the colour core | Existing DV bridge, DRM connector state and kernel path |
| Turn signal into emitted light | Not measured by these numerical stages | TV processing, picture settings, panel and viewing conditions |

Dolby describes dynamic analysis and artistic trims as instructions that accompany the image so it can be adapted to devices with different capabilities; its iCMU maps to selected output targets. That is distinct from simply changing colour coordinates. [Dolby: content-creation workflow](https://professional.dolby.com/content-creation/dolby-vision-for-content-creators/).

## Exactly what the new colour stage accepts

`ColourConfig.from_dm` accepts uncompressed source DM with `signal_eotf=65535`, all three EOTF parameters zero, bit depth 12, colour space 0, chroma format 0, and full-range flag 1. It extracts the nine source nonlinear coefficients divided by 8192, nine source linear coefficients divided by 16384, and three offsets divided by 2^28. Other source signal descriptions fail rather than silently convert.

The C core itself accepts already configured finite source/target matrices and offsets. It does **not** parse RPU, validate a bitstream, select a TV target, or apply extension-block trims. Target matrices must be invertible. Supported explicit PQ policies are `reject-outside-unit` and `extend-positive-negative-to-zero`; neither is a licensed display-mapping algorithm. Source/expanded component inputs stay in 0..4095. Final output is rounded using `floor(value*4096+0.5)` and bounded to 0..4095. That final carrier bound is not a TV brightness limit.

`colour_metadata.load` independently verifies the saved extraction/preparation/RPU association and supported source subset. It requires exactly one CMv2.9 Level5 active-area block and validates the rectangle. `colour_frame` masks the outside area and uses the explicitly labelled bilinear-left diagnostic expansion. Level5 handling is geometry, not tone mapping. L1, L2, L3, L4, L6, L8-L11 and L254 are not consumed as display-adaptation instructions by `native_colour`; their presence in saved DM does not mean this core implements their display effects.

Source provenance, arithmetic and output policy therefore remain separate contracts. No whole film is rehashed here, and a self-consistent saved association is not proof of authenticity, actual HDMI signaling or licensed output.

## What the pinned runtime actually does

The libplacebo mapper reads source offsets and matrices, BL reshaping and EL NLQ. Its colour wrapper tags BT.2020/PQ, derives source min/max brightness from source PQ fields, and reads Level1 maximum/average PQ. This is not an implementation of all artistic display trims.

In bridge rendering the ordinary DV target initially shares the source colour description. The explicitly different `hdr10` branch chooses a BT.2020/PQ target peak from valid Level6 mastering maximum, otherwise source maximum PQ. It chooses Level1/CIE-Y or HDR10 metadata for generic libplacebo colour mapping, disables inverse tone mapping, and does not claim this is licensed Dolby display management. Source CLL/FALL are not reported as measurements of the mapped output.

The standard tunnel serializer rewrites the signal description to the bridge's fixed full-range 12-bit IPT representation and corresponding matrices. It passes Level1 and Level2 fields, emits/remaps Level5 geometry, preserves selected raw blocks (4,3,8,9,10,11,254) through its checked wire converter, and excludes Level6 from dynamic DV wire data. Unknown levels fail. It requires exactly one Level1, rejects duplicate Level2 targets and invalid active-area structure, inserts a default Level5 when absent, limits the payload to 482 bytes/four packets, and checks packet CRC. Repeats retain stable scene-refresh state; discontinuities force refresh. These are source-level serialization rules, not proof that every field reaches or is honoured by a TV.

The DRM eligibility check requires `SupportsStandardDolbyVision`, an atomic DRM backend, a connected connector exposing `DVBRIDGE_DV_STANDARD_LAB`, and progressive 3840x2160. The state transaction requests that standard-DV property, an 8-bit RGB carrier ceiling, full Broadcast RGB and default connector colourspace, clears static HDR metadata and available CTM/gamma/degamma state, and prevents competing planes/cursors from altering tunnel bytes. Original state is saved for restoration. The inspected branch does not implement an LLDV display-target mapper. Requested connector values and successful commits are not independently measured wire format, panel behaviour or loaded-build identity.

## TV-led versus player-led: what the distinction does and does not settle

Dolby's HDMI-tunneling description says video and Dolby metadata are delivered to a Dolby Vision TV. [Dolby: HDMI tunneling](https://dolby.my.site.com/professionalsupport/s/article/HDMI-Tunneling?language=en_US). Together with this runtime's explicit standard-DV property and preserved dynamic instruction payload, this supports the intended TV-led ownership above; it does not reveal a normative TV algorithm.

For an independently documented LLDV implementation, HDfury's own VRROOM manual explains that a maximum luminance in the advertised DV data block informs the player, which tone-maps the Dolby picture to LLDV. It also distinguishes that source target from later HDR metadata/TV processing. [HDfury VRROOM manual, printed pages 57-58](https://www.hdfury.com/docs/HDfuryVRRoom.pdf). This is manufacturer documentation of that workflow, not a Dolby specification or a recommendation to spoof EDID.

Consequently, a player-led backend would need explicit sink capabilities, a declared mapping algorithm/trim support, target precision and signal-format rules, and separate output signaling. We cannot assume that the TV does absolutely no subsequent processing in LLDV, or that standard-DV merely moves every Dolby processing step into the TV. Reconstruction and transport still belong to the player in this inspected design. Neither mode name resolves the unknown fractional-EL policy, chroma registration or extreme-value handling inside reconstruction.

## Smallest useful next tests, without choosing a mapping policy

1. **Metadata-only sensitivity:** hold source colour coefficients, reconstructed triples and target configuration fixed; vary synthetic L1/L2/L8 trim blocks. The colour core must remain unchanged, while a separate tunnel serializer test must preserve the supported payload changes. This demonstrates ownership rather than inventing trim mathematics.
2. **Transport self-consistency:** synthetic colour triples, including negative/above-unit intermediate cases, go through explicit colour conversion, packing, metadata encoding, independent unpacking and declared inverse target coordinates. Check component order, denominators, rounding, CRC, active-area and scene-refresh transitions. No SK4-derived fitted matrices or offsets.
3. **Mode isolation:** fake EDID/property fixtures distinguish standard-DV capability from LLDV-only capability; require failure instead of selecting a standard tunnel on an incompatible sink. Test HDR10 versus standard metadata/state requests and exact restore after a failed commit. No live connector changes needed.
4. **Boundary observability:** add named intermediate taps to diagnostic reports: reconstruction, chroma expansion, source nonlinear coordinates, linear LMS, target pre-quantization, packed payload and signaled mode. Compare corresponding stages, not a post-TV screenshot against an earlier player stage.

Only after those contracts are checked should a separately approved runtime observation inspect the loaded build, actual generated shader/import, HDMI payload and TV mode. Licensed-device captures remain comparison evidence, not a target curve to fit or a replacement for those checks.

## Source inventory

Local staging sources read 2026-10-05; hashes identify this audit checkpoint, not a deployed binary:

| File | Relevant lines | SHA256 |
|---|---|---|
| `native_colour.c` | 145-178 | `2d90cef334b5c0c32a59a7ed8b6a161171f13cc3719821c1395bb534a57753cb` |
| `colour_stage.py` | 112-160 | `405ac904ae8711587ad20d4f77658a54838804035b7d6eaef4cb484e70ed7217` |
| `colour_metadata.py` | `_active`, `load`, `make_configuration` | `f770827e565dca81930ed50e85b6b54ba00311521961a074e85451a67f706e10` |
| `colour_frame.py` | frame adapter / explicit target policy | `9422de8c96e6582170c0e0d1be47084f56721f9f4359a19d7da273c6a0c20bdd` |

Pinned Ollie build root: `/home/bryan/Projects/libreelec-yblod/build.LibreELEC-Generic.x86_64-13.0-devel/build/`. `K` is `kodi-22.0rc1-Piers`; `P` is `libplacebo-e2972fdd09adacd383656738d7d280f0cd84a761`. These patched build files were read directly; upstream version labels alone are insufficient.

| File beneath build root | Relevant lines | SHA256 |
|---|---|---|
| `K/tools/dvbridge/dvbridge_placebo.c` | 8-42,45-96 | `5d548a2107d802bb9548dc37be875cc5ee50b279e13df9b356b9ba09aaf5a32e` |
| `K/tools/dvbridge/dvbridge_render.c` | 259-300,318-355 | `f829f1ff5467892391640fb4f2368202cdb4e8decc9e46b151b5ce81cbe640e0` |
| `K/tools/dvbridge/dvbridge_metadata.h` | 100-220 | `da799ab08381318601bb0a3f8a1a74ed3293ca09b2cdde52228ea6f7e4c06d36` |
| `K/xbmc/windowing/gbm/drm/DVBridgeState.cpp` | 7-99 | `975d37b53d035194d3fc57ffd0f9d390dc9cd2a7efa66e0ffa2bd30732c859df` |
| `K/xbmc/windowing/gbm/WinSystemGbm.cpp` | 316-350 | `d59f4b14fdfa51b7b9813a6751cdc6db50fd06ea9f87a0a9e977ca2800809d8d` |
| `P/src/include/libplacebo/utils/libav_internal.h` | 941-1058 | `542055662c561cbccbb479a89be0ed1b6e295bbc7b2298a83d8424d053d14189` |
| `P/src/shaders/colorspace.c` | 323-369,452-483 | `5961adebdc5f4768eb6cf28560f9cb1143c65d3cfbe6be089097347dc232ebcf` |

No licensing status, proprietary algorithm equivalence, SK4 match, display calibration or new default follows from this audit.
