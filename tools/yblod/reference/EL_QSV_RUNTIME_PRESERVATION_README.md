# EL QSV runtime preservation capture

`capture_el_qsv_runtime_preservation.py` captures three matched frames with EL QSV decoding **disabled**, then restores the retained Kodi binary, its original library mappings, and the exact original service override. Use it only after reviewing the target's existing bind mount layers, candidate runtime, and rollback files. It is not an unattended or universal installer.

## Required preparation

The isolated stage must already contain `kodi-el-qsv-candidate.bin`, the reviewed runtime `lib/` and `manifest.json`, and `baseline-tools/` containing the current `capture_scene.py`, `observe_subtitle_fixture.py`, `collect_el_qsv_target_identity.py`, and `capture-el-qsv-planar1-flag0.conf`. Complete the target loader and dependency checks before using the template.

Create the retained baseline on the same target with three exact source timestamps and the same movie, title, seek, native planar output, packed output, batch disabled, immutable instructions disabled, and subtitles temporarily disabled. Supply its private capture report, independently observed target and source stat evidence, and an exact backup of the original service override. The retained Kodi must be idle, with its verified original executable as the current top bind mount. Preserve all lower mount layers and rollback artifacts.

The private launcher is copied from the actual target with its original permissions. Only its final binary invocation changes: candidate libraries are prepended after the system profile resets `LD_LIBRARY_PATH`. Normal startup arguments remain unchanged; the original launcher and profiles are never edited.

## Bounded launch

Run the controller in a dedicated transient unit with these settings:

```sh
systemd-run --wait --pipe --unit=UNIQUE_REVIEWED_UNIT \
  -p MemoryMax=536870912 -p MemorySwapMax=0 -p CPUQuota=100% \
  -p RuntimeMaxSec=330 -p TimeoutStopSec=30 -p UMask=0077 \
  -p Environment=PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/python3 /path/capture_el_qsv_runtime_preservation.py \
  --stage /storage/REVIEWED_STAGE --attempt-tag UNIQUE_FRESH_TAG \
  --retained-source /storage/REVIEWED_RETAINED_BINARY \
  --retained-sha256 RETAINED_CODE_SHA256 \
  --candidate-sha256 CANDIDATE_CODE_SHA256 \
  --driver-sha256 EXISTING_TARGET_DRIVER_SHA256 \
  --baseline-report /storage/REVIEWED_STAGE/BASELINE_REPORT.json \
  --baseline-identity /storage/REVIEWED_STAGE/BASELINE_IDENTITY.json \
  --original-override /storage/REVIEWED_STAGE/ORIGINAL_OVERRIDE.conf \
  --movie-id LOCAL_LIBRARY_MOVIE_ID \
  --expected-title 'Exact library title' --seek-seconds 1200
```

Replace every placeholder with reviewed actual values; code digests must be 64 lowercase hexadecimal characters. The title defaults to `Saving Private Ryan` and the seek defaults to 1200 seconds. The movie ID is required and may differ between libraries. The stage uses simple absolute `/storage` paths without spaces or shell metacharacters. Keep reports and private source identity evidence directly inside the isolated stage.

Do not enable `PrivateNetwork` for this capture controller: it needs the target's local Kodi RPC endpoint. The 512 MiB, no-swap and one-CPU limits apply to the controller, not to the separate Kodi service. The work alarm interrupts after 180 seconds, leaving time for restoration before the unit's 330-second deadline. SIGTERM initiates restoration during capture; the restoration phase ignores repeated SIGTERM while its bounded operations complete.

## Results and recovery

A successful capture is not an output-equality qualification. Compare the retained and candidate frames separately using `compare_renderer_frames.py --require-picture-and-payload-preserved`, with an additional requirement that both BL and EL timestamps are exactly equal. Keep raw captures, metadata, library mappings and source identity records private. Only validated transport update IDs and their CRCs may differ; picture samples and the full Dolby payload must remain identical.

If `rollback_uncertain` is true, stop further tests. Independently inspect the actual service PID and executable, top mount source, and complete mount layer count before any recovery action. Never guess ownership, remove lower layers, or stack another candidate mount. Restore only a separately verified owned top and the exact original override, then verify the retained binary, runtime mappings and idle state. External termination, OOM or an unexpected mount/process can prevent automatic recovery; operator verification is required.

The published preservation result came from the reviewed private controller. This parameterized template has CPU-only parsing, launcher and fault-injection tests; it is not a separate hardware-tested run. Neither capture success nor normal process shutdown proves QSV-enabled decoding, raw EL equality, playback performance, Dolby conformance, or clean display restoration.

## Live raw EL probe identity

`target_el_qsv_live_handshake.py` provides an additive live-proof callback for a separately reviewed probe controller. It does not launch a probe. The C probe must hold its actual QSV helper and device alive after its frame comparisons and runtime checks, create a fresh private ready checkpoint with its actual PID and nonce, and wait for the exact acknowledgement bytes.

Call `acknowledge_unit_child` in the same PID namespace as the probe. Supply the independently observed wrapper PID and start ticks, exact private loader and probe argv, expected probe code digest, render node, complete approved mapped-library closure and existing driver. The callback requires exactly one actual direct child, validates its parent and process generation, checks the actual loader executable and mapped probe code, inspects the same child's live i915 client and library mappings, rechecks identity, then creates a fresh 0600 acknowledgement containing only the nonce. Unknown or extra children fail closed. Do not substitute a host PID for a PID emitted inside a container.

This callback alone does not establish a complete qualification. The controller must additionally enforce actual resource limits and exit status, unchanged executable/runtime/driver/source stat identity, independent capture-host and physical-GPU association, and the probe's literal zero-difference raw EL sample results. An Ollie hardware diagnostic cannot qualify a different target GPU. The helper's published tests are CPU-only mocks; actual C-hook and controller wiring need review before a hardware run.

`prepare_sdk_probe_runtime_identity.py --sdk SDK_PATH --binary PROBE_PATH --output FRESH_PRIVATE_JSON` prepares the explicit SDK code closure for `observe_live_el_qsv_probe.py`; it follows only SDK dependencies, not host-library fallbacks. Run preparation in the pinned offline container with 512 MiB, no swap and one CPU, SDK and source mounted read-only, only a fresh private output directory writable, and no GPU or media mounts. Measure final cgroup peak/events/swap before the container exits. The observer runs in the probe's PID namespace with the same limits, emits safe numeric results, and keeps the complete C report, live identity proof and decoder stderr private. Its host controller must separately enforce idle playback and the total deadline. Unstripped SDK code can exceed the memory cap in file-cache charges; the code-only fingerprint helper advises away complete aligned ranges after hashing without changing bytes or relaxing resource gates. Do not treat these diagnostic cache hints as a playback-performance optimization.
