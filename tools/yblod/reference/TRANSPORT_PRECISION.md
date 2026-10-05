# Locating the alternating-row difference in the saved transport

This is a read-only audit of existing source-associated SK4 captures and the
unchanged standalone direct output. It asks where the difference lives in the
stored numbers, before choosing another rendering change. It does not correct
the capture, alter the output, or identify a hardware cause by itself.

## Why inspect bits?

Each 12-bit component is transported in two pieces: its upper eight bits and
its lower four bits. The pieces travel in different RGB8 byte fields. A small
error in one transported byte can therefore have a different effect on the
recovered Dolby component than a similarly sized error in another byte.

For any component code, exactly:

```text
code = 16 * upper_eight_bits + lower_four_bits
signed_difference = 16 * upper_difference + lower_difference
```

This is an accounting identity, not a new colour transform. Carries matter:
the difference between codes 15 and 16 is only one, despite their upper and
lower pieces changing in opposite directions. Signed contributions add;
their absolute errors generally do not. The tests explicitly cover that case.

RGB8 capture storage is not evidence that Dolby content was reduced to eight
bits. The existing format packs 12-bit values into RGB8 fields. Conversely,
valid metadata checksums support the byte arrangement but do not establish
that every active-picture bit was preserved by every hardware block.

## Independent checks and scope

An exact scalar oracle and literal byte patterns check the packing, nibble
placement, paired colour samples and CoreELEC's reversed 64-bit memory words.
They do not use the production packer to generate their expected byte values.
Arithmetic tests cover all 4096 possible component codes and carry boundaries.
These prove implementation agreement with the stated storage layout, not the
fidelity of a physical capture path.

The audit keeps the original active rectangle and frame coordinates. It reports
I, P and T separately, with all-row, even-row and odd-row groups; P and T share
the same co-sited colour-sample coordinates. Upper/lower distributions and
individual bit counts are descriptive evidence. They are not fitting targets.
No image shift, fitted offset, filter change or rounding adjustment is applied.

Metadata packet copies, checksums, coordinate matrices and input hashes are
validated before a completed report is produced. Capture frame association is
the existing supplied visible-counter association, not a new timestamp proof.
Only numerical aggregates are public; raw movie/capture pixels remain private.

The comparison uses 32-row strips. On Ollie, each processing job runs separately
under `MemoryMax=512M`, `MemorySwapMax=0`, with one numerical-library thread.
No live-device registers, capture settings or playback code are changed.

## Findings in the four existing captures

All exact arithmetic and per-bit accounting checks pass. The table shows the
T-channel **even-row minus odd-row gap in mean signed error**, not a constant
error at every pixel and not the total picture error. The last two columns add
to the first (apart from displayed rounding). Signed error is standalone direct
output minus SK4 capture.

| Frame | Complete 12-bit error gap | Upper-eight-bit contribution, multiplied by 16 | Lower-four-bit contribution |
| --- | ---: | ---: | ---: |
| 461 | 8.636544 | 8.658351 | -0.021807 |
| 1406 | 8.887384 | 8.821525 | 0.065859 |
| 1960 | 8.817118 | 8.553527 | 0.263591 |
| 2296 | 7.468395 | 7.386062 | 0.082332 |

Almost all of this particular row-gap statistic is in the upper-byte
contribution. All 16 lower-nibble values occur in both row-parity groups of
every captured channel in these four frames; this is not simply every other
row losing all four fine bits. This does **not**
prove that a byte was altered after packing: earlier arithmetic differences
can change the same byte, and carries complicate individual-pixel attribution.

Splitting each row into even and odd **colour-sample columns** leaves the pattern
essentially unchanged in the global means. For frame 1960, even-row T errors
are `10.930418` and `10.926391`; odd-row errors are `2.112680` and `2.109894`.
That does not rule out local or longer-period patterns; it only describes this
two-column split. P and T use the same sample-column coordinates, not their
different packed RGB pixel slots.

The independent literal-byte tests pass for the existing packer/decoder. They
include every possible 12-bit code, every bit in a 24-byte memory block, odd
strip boundaries and separate P/T placement. No implementation error was found
in those tested storage operations. We have **not** established that the entire
physical capture path preserves the video output exactly.

No fitted offset, byte substitution or discarded precision is justified by
these findings. The remaining possibilities include earlier reconstruction or
colour processing, device output behaviour, and capture-side processing.
The measured pattern alone does not establish dithering.

## Correct hardware family and limits of the live state check

A read-only query after these original captures reports device-tree model
`Ugoos SK4` and compatible `amlogic, s7d`. The current system reports Linux
`5.15.196`, CoreELEC `22.0-Piers_nightly_20261005`, build
`96280fdbba2cadbf6c890e63248b6fe89fd5bc14`. These are **current** observations,
not proof of the software configuration at the time of the saved captures.

The Dolby module's `ko_info` separately reports the label `chip_name = s6` and
`[stb:2.6:e]-[v1.0]` with FEL support. Keep the device-tree and module labels
separate; this audit does not infer a configuration error from their difference.
The read-only Dolby state showed `dv_mode = off`, no active video source, SDR
graphics, `support_info = 7` and `operate_mode = 0`. This idle state cannot tell
us which precision controls were active during the original playback.
The actual module parameter directory is `/sys/module/aml_media/parameters`;
observed values were flags `536870917`, mode `5`, low-latency policy `0`, and
enable `N`. These software variables are not hardware-register readback or
evidence of the earlier active capture configuration.

The pinned public driver source explicitly declares
[S7D capture capabilities with detunnelling disabled](https://github.com/CoreELEC/common_drivers/blob/4dbe1c27ae176fde4c1cbef7506618fd7f62b976/drivers/media/vin/tvin/vdin/vdin_drv.c#L5894).
Consequently, an S5-specific 12-to-10-bit conversion path is **not evidence** that
this SK4 loses precision. Matching the actual build and active runtime path is
still necessary. No certification, bypass or precision flag was changed.

## Next controlled capture check

1. During a visibly verified paused numbered frame, record the active software
   state and only safely identified hardware state for this device/build.
2. Read the **same frozen completed buffer twice** to test readback stability.
3. Freeze fresh buffers over several refreshes of that same paused picture and
   compare the unmodified bytes, metadata copies, row groups and bit groups.
4. Retain buffer identities, timing and state, and keep source-frame identity
   separate from the driver's timestamp.

Stable patterns do not exclude spatial dithering; changing patterns do not
prove temporal dithering. The existing VENC0 loopback capture is not independent
HDMI-wire measurement. Do not enable broad certification/bypass modes as a
single-variable test: they affect several processing blocks. These repeated
captures have **not** been performed in this checkpoint.

## Results and reproduction

Detailed aggregate reports: [461](results/transport-precision-461.json),
[1406](results/transport-precision-1406.json),
[1960](results/transport-precision-1960.json),
[2296](results/transport-precision-2296.json).

The reference suite passes **246 tests** on Ollie, including 26 new transport
checks. Each real-frame audit took about 1.4 seconds and peaked at no more than
**48,232 KiB RSS**, with no swaps or OOM failure. These are offline diagnostic
measurements, not playback performance numbers.

With the existing local baseline and corresponding capture, choose an unused
report path and run from the repository root:

```sh
systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0 -- \
  env OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 tools/yblod/reference/transport_precision.py \
  target/sk4-sweep-1960-direct "$SK4_CAPTURE" \
  --report target/transport-precision-1960-reproduced.json

python3 -m unittest discover -s tools/yblod/reference -p 'test_transport_precision*.py'
```

Set `SK4_CAPTURE` to the matching saved `native.rgb`. The synthetic tests require
neither movie files nor a device. The audit reads existing captures; it does not
start playback, freeze buffers or write device settings.
