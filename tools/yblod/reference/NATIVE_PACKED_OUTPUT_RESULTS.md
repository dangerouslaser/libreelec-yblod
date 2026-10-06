# Native colour and transport packing results

The opt-in packing candidate preserves every transmitted RGB byte on three
matched Saving Private Ryan frames while eliminating a full-resolution RGB
intermediate write/read and a separate packing draw during eligible playback.
Its utilization benefit is being measured separately; production default remains
disabled.

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

## Build and playback measurement

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
