# Paired whole-code cached/reference CPU diagnostic

`native_scaled_frame_cached_benchmark.c` compares the experimental cached
composer with unchanged reference processing on the same saved inputs. It is
not playback, a fractional policy, independent arithmetic conformance or an
image-accuracy comparison. GPU scaling, decoding, file I/O, colour conversion,
HDMI and display mapping are excluded from the timed frame workload.

The input contract matches the original standalone benchmark: even dimensions
2..3840 by 2..2160, an exact same-build 9216-byte instruction blob, native10
planar base Y/Cb/Cr and registered luma guide, and exact tightly packed P010.
Input descriptors and tokens remain externally asserted associations. Regular,
non-symlink, distinct-inode sources have exact extents and stable pre/post read
identity. All base codes and every active enhancement word are checked before
comparison or timing; fractional enhancement words are rejected, never rounded.

Before any clocked workload, the program creates both tracked frame sessions,
extracts every component chunk once and compares all four stage arrays byte for
byte after both paths process that same chunk. Both sessions must finish with
all component counts. The public report labels this **untimed full-frame**
equivalence. `component_routes` records 1 for polynomial lookup and 0 for
unchanged batch MMR fallback; it contains no coefficients or picture hashes.

One warmup per backend is excluded. Three measured pairs alternate order:
reference/cached, cached/reference, reference/cached. Every run creates a fresh
decoder bridge context. Cached runs additionally create a fresh owned plan,
including allocation and exact table generation. Wall (`CLOCK_MONOTONIC`) and
process CPU clocks cover bridge/plan preparation, every surface extraction,
four stage writes, completion/count verification, owned-plan destruction and
context reset. Preparation is reported separately but already included in each
total. Shared input loading and scratch-buffer allocation occur **outside**
timing; preparation does not mean all program allocations.

All kernels must be separately compiled without LTO. A post-timer comparison
checks all four arrays from the final chunk against saved verified results to
make those writes observably consumed. This is explicitly a **last-chunk-only**
timed crosscheck, not full-frame verification of every timed pass. No timings
are published unless the initial whole-frame equivalence gate, every tracked
completion and every post-timer crosscheck succeed. No speed threshold changes
whether correct output is accepted.

From the repository root, compile the separate units with strict C11 warnings
and **`-fno-lto`**:

```sh
cc -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow \
  -fno-fast-math -ffp-contract=off \
  -Iengine/include -Iengine/experimental \
  engine/experimental/native_scaled_frame_cached_benchmark.c \
  engine/experimental/native_cached_composer.c \
  engine/experimental/native_scaled_surface.c \
  engine/experimental/native_decoder_frame_bridge.c \
  engine/experimental/native_integration_probe.c \
  engine/experimental/native_sampling_probe.c \
  engine/src/native_composer.c -o native_scaled_frame_cached_benchmark
./native_scaled_frame_cached_benchmark WIDTH HEIGHT INSTRUCTIONS BL_Y BL_CB BL_CR GUIDE P010
python3 -m unittest discover -s tools/yblod/reference \
  -p test_native_scaled_frame_cached_benchmark.py -v
```

The synthetic test command needs no movie file, Kodi, GPU or licensed player.
Use your own matching private inputs for the CLI; instruction blobs are
same-build ABI data, not a portable format. The generic JSON omits picture
hashes and paths, but privately archive and verify your inputs externally.

For the LibreELEC SDK, mount the whole repository and SDK read-only, disable
network, limit to one CPU and 512 MiB/no additional swap. Pin each executed
source/header, executable and runtime library before and after the private
job. Use a fresh 512 MiB/zero-swap runtime scope and archive its memory events.
Keep all movie pixels, instruction blobs, private paths and picture-associated
hashes excluded from public reports. Record source/binary identities and honest
scope instead. Run `test_native_scaled_frame_cached_benchmark` for synthetic
CLI guards and multi-chunk equivalence; this contract alone claims no actual
target performance result.

## Actual LibreELEC CPU checkpoint (2026-10-05)

The [public result](results/native-cached-frame-vm-20261005a.json) records the
same 3840x2160 saved-input workload on the VM. All 49,766,400 stage values over
191 dispatches matched byte-for-byte in the untimed gate, and both sessions
completed counts [8,294,400, 2,073,600, 2,073,600]. The actual component routes
were [1,0,0]: luma used lookup tables; both chroma components used unchanged
MMR batch processing. Owned plan/frame sizes were 27,632 and 9,384 bytes.

Reference wall times were 603.655, 602.396 and 656.125 ms; cached times were
402.645, 404.596 and 434.256 ms. That is roughly one-third less CPU-workload
wall time, **not** playback FPS. Cached preparation took 0.679–0.729 ms and was
already included, together with teardown, in those totals. Exact nanoseconds,
process CPU measurements and reference preparation values are in the report.

The cgroup peak snapshot before wrapper exit was 57,438,208 bytes under a
512 MiB/zero-swap cap, with zero observed swap, high/limit/OOM events. This is
not a final lifetime peak or total GPU-allocation measurement. The runtime
scope's CPU-quota controller was unavailable; the SDK compiler had a one-CPU
container limit, which does not establish a one-CPU runtime quota.

Executed source/header identities, binary/wrapper and six private inputs, libc
and loader identities were checked unchanged before/after their respective
build/runtime stages. Kodi remained active. Private input/output hashes, paths
and metadata remain excluded; public replay tests verify the 14 executed
C/header source pins and exact checkpoint scope. The comparison establishes
exactness against our unchanged reference, not an independent mathematical
answer, closer SK4 output, fractional Y416 handling or production playback.
