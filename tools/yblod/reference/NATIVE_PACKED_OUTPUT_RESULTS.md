# Native colour and transport packing results

The opt-in packing candidate reduces GPU render-client activity by 30.74 percent
and whole Kodi CPU by 16.24 percent on the matched Saving Private Ryan scene.
It preserves every transmitted RGB byte on three matched frames while eliminating
a full-resolution RGB intermediate write/read and a separate packing draw during
eligible playback. Production default remains disabled pending broader checks.

## Output preservation

The candidate keeps native reconstruction, enhancement-layer scaling, chroma
expansion, release RGB colour conversion, colour offsets, quantization, and
metadata payload generation. It does not adopt the earlier direct LMS colour
conversion. Existing fullscreen and overlay eligibility guards remain in place;
composition remains available when packed output is ineligible or fails.

On 2026-10-06, three 4K Saving Private Ryan frames were captured in composed,
packed, and composed order using the same candidate binary. Both layer timestamps
and source metadata matched. Each capture sequence verified the actual Kodi child
executable digest and process identity, expected native/packed route, player stop,
and clean service shutdown.

| Frame | Composed to packed RGB byte differences | Maximum I code difference | Maximum P code difference | Maximum T code difference | Packet count |
| --- | ---: | ---: | ---: | ---: | ---: |
| First | 0 | 0 | 0 | 0 | 1 |
| Second | 0 | 0 | 0 | 0 | 2 |
| Third | 0 | 0 | 0 | 0 | 2 |

Equality covers the entire transmitted RGB raster, including black borders and
metadata rows. Packet repetitions and CRCs also pass. Alpha is not transmitted
and is excluded. The original current-engine binary and the candidate with the
feature disabled additionally preserve all three frames' full picture and payload.

The final composed repeat preserves the same picture and payload exactly. Its
first frame has identical transmitted bytes; the second and third differ in
120 and 96 bytes solely from validated transport update IDs and their CRCs.
Startup history changes these IDs. The comparison requires unchanged payloads,
including scene-refresh signalling, and exact pixels everywhere else. It does
not accept a pixel tolerance.

These checks establish preservation for the captured frames on this Intel
hardware, not universal equivalence, licensed Dolby accuracy, or conformance.
Offset-disabled output, other metadata, additional scenes, and overlay transitions
remain qualification targets before default adoption.

## Matched playback results

The same candidate binary played the scene at 20 minutes for 180 seconds per
case in disabled/enabled/enabled/disabled order, with a clean restart and at least
20 seconds of startup settling each time. Only the explicit native packing option
changed; layer and output captures were disabled.

| Balanced measurement | Composed output | Packed output | Change |
| --- | ---: | ---: | ---: |
| GPU render client busy percent | 59.4510 | 41.1742 | Minus 18.2768 percentage points |
| Whole Kodi CPU percent of one core | 19.6927 | 16.4948 | Minus 16.24 percent |
| Video decode client busy percent | 5.3478 | 5.3423 | Minus 0.0055 percentage points |
| Video enhancement client busy percent | 9.4635 | 9.5095 | Plus 0.0461 percentage points |
| Consumer release helper wait ms | 7.4075 | 3.9558 | Minus 46.60 percent |

Render activity in test order was 59.6232, 41.4122, 40.9361, and 59.2788 percent.
Both enabled cases are below both controls. Whole Kodi CPU was 19.8669, 16.6099,
16.3797, and 19.5185 percent of one core. All four cases recorded zero drops and
skips, including startup/seek, normal steady playback speed, no stalls, and clean
player-stop and service shutdown. The controller exited zero and restored its
prior override without restarting Kodi.

Renderer counters prove exclusive packed preparations between the first and last
periodic summaries in enabled cases, and exclusive composition in controls.
Actual colour conversion remained release RGB; FP32, lookup and metadata-only
handoff qualification passed without fallback or stage failure.

CPU pools process CPU seconds over elapsed seconds. GPU counters are deduplicated
Kodi client activity weighted by interval duration; copy activity was zero. Helper
waits pool cumulative timing differences over 8,160 control and 8,400 candidate
released operations. They are host completion waits, not exclusive shader latency
or FPS, and should not be summed. Only two repeats per route and one scene were
measured. Playback counters do not establish output accuracy; separate pixel
checks above establish preservation for the captured frames.

The [playback measurements](NATIVE_PACKED_OUTPUT_SPR_PLAYBACK_RESULTS.json) retain
per-case route, health, lifecycle, timing, memory and counter records.

## Build and reproduction

Strict native and non-native C/C++ SDK compilation passed under a 512 MiB,
one-CPU, no-extra-swap cap. The full serial build passed under a four-GiB cap,
with peak memory 2,198,007,808 bytes, all memory events zero, and swap use zero.

The performance controller requires passing native composed/packed preservation
reports before it can start. It runs the same Saving Private Ryan scene at
20 minutes for 180 seconds per case in disabled/enabled/enabled/disabled order.
Both conditions use FP32 reconstruction, the NLQ lookup, and metadata-only colour
handoff. Output and layer capture flags are disabled during these measurements.
Actual renderer counts must prove the selected route; fallback warnings fail
qualification.

Enable only for testing with `DVBRIDGE_NATIVE_PACKED_OUTPUT=1`. The numbered Kodi
patch and reproducible test controllers are public on the experimental branch.
The [scalar frame results](NATIVE_PACKED_OUTPUT_FRAME_RESULTS.json) contain no
raw film frames or source metadata.
