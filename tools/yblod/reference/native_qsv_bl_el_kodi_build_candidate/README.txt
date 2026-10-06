Combined BL+EL QSV Kodi isolated build evidence (2026-10-06)

RESULT AND LIMITS
The complete Kodi executable compiled and linked. A subsequent, separately
approved read-only target-loader check passed against that exact executable and
the qualified c0eee FFmpeg libraries: 156 resolved library records, 51 unchanged
DT_NEEDED entries, loader exit 0, empty stderr. Kodi was not executed. This is
NOT combined playback, EGL/direct-map, crop admission, lifecycle or performance
qualification. Nothing was deployed. Default BL-QSV selection remains OFF.

The full build controller itself exited 1 after successful linking because its
original loader search omitted inherited SDK PulseAudio/Samba staging paths.
Do not relabel that run successful: the independent final loader check closes
the dependency-resolution question without overwriting either failed build.
BUILD_RESULTS.json records all five sequential attempts and their limitations.

SOURCE CONTENTS
prepare_build_qsv_kodi.py: exact tested second-attempt controller, unmodified.
test_build_controller.py: 17 mocked tests (passed locally and on Ollie).
source-manifest.json: exact approved source, dependency and resource pins.
qsv-bl-kodi-async-depth-one.patch: additive default-OFF pre-open option patch.
disk-tmpdir-fix.diff: reviewed change from first to second build controller.
diagnose_kodi_loader.py, diagnose_kodi_loader_pulse.py,
diagnose_kodi_loader_samba.py: exact sequential read-only loader diagnostics.
These helpers retain historical paths/CIDs and immutable-output guards. They
are provenance, not a portable one-command rerun; do not run against occupied
output directories. A fresh reproduction requires reviewed new paths and, for
loader helpers, the new exact owned build CID and resulting executable hash.
No automatic retry, cleanup, deployment or GPU work is authorized by this bundle.

PATCH ORDER
Use the complete public integration patch and buffer-registration correction in
tools/yblod/reference/native_qsv_bl_kodi_integration_candidate, then the additive
async-depth patch here. Do not also apply historical partial foundation patches.
The new log reports requested async_depth=1 and AVOption readback, not effective
SDK AsyncDepth. The controller pins all three patches and baseline EL fed8 source.

REPRODUCTION ON THE PINNED OLLIE SDK
First review all scripts and source-manifest.json. Run mocked tests:
  python3 -B -m unittest -v test_build_controller
The controller requires Linux, the pinned SDK/image and qualified code-only
closure report. Use the following arguments with a NEW lowercase output suffix:
  python3 prepare_build_qsv_kodi.py --phase plan \
    --sdk /home/bryan/Projects/libreelec-yblod \
    --public /home/bryan/Projects/libreelec-yblod-reconstruction \
    --candidate /home/bryan/Projects/libreelec-yblod-reconstruction/target/qsv-bl-compatible-param-library-20261006 \
    --closure-manifest /home/bryan/Projects/libreelec-yblod-reconstruction/target/qsv-bl-compatible-param-library-runtime-1536-20261006/runtime-identity-private.json \
    --output /home/bryan/Projects/libreelec-yblod-reconstruction/target/qsv-bl-el-kodi-reviewed-fresh-suffix
After reviewing the plan, substitute --phase prepare. Independently verify its
manifests before separately approving --phase build with identical arguments.
The frozen controller's initial post-link loader check may reproduce exit127;
the final diagnostic helper demonstrates the exact explicit staging paths needed.
No host-library fallback was used. Search precedence was SDK sysroot/usr/lib,
target GCC lib, sysroot/usr/lib/pulseaudio, install_pkg/samba-4.25.0/usr/lib last.
Old/new direct dependencies are identical; actual Petunia libtevent matches the
SDK staging hash recorded in BUILD_RESULTS.json. Target closure still needs its
own preflight and runtime verification; SDK loader success is not target proof.

ISOLATION AND RESOURCES
Preparation copied 15,615 regular files (about 1.04GB), preserving two symlinks,
and verified byte equality plus distinct inodes: no hardlinks and no live SDK
edits. Exactly 11 source paths were changed/added, no source paths removed.
Unchanged configured objects were reused with exact tree provenance. CMake was
regenerated; changed sources/header dependents rebuilt; full executable linked.
Original absolute /build paths were preserved using a read-only SDK mount with
only the private Kodi copy writable. Eight pinned FFmpeg ELF files were bound
read-only over resolved sysroot destinations, including absolute CMake link paths.
Image: sha256:40b586615eae489cab72f139f659b81360da4c9e0b0787fadc5cba0119d9b29e.
Full build: CPU1, 4GiB memory, zero swap, network none, read-only container root,
no GPU devices, serial LTO=1. Host launch reserve was 6GiB MemAvailable; abort
threshold 2GiB (not 3GiB). Disk launch floor 6GiB, abort reserve 2GiB. Ninety-minute
deadline. Compiler TMPDIR was private disk-backed output/compiler-tmp; sampled
2GiB budget is a monitored limit, not a filesystem quota. /tmp stayed 128MiB.
Bounded exact-CID cleanup verified terminal state; all artifacts were retained.
The final 1GiB loader diagnostic is not a product playback memory recommendation.

REMAINING RUNTIME GATES
Observe frame width/height, frames-context allocation width/height, all four crop
fields, interlace flag, mapped VAAPI/P010 and same-device booleans, preserved
properties and mapped-buffer admission on actual selected Kodi frames. Existing
CQsvMappedBuffer::Valid rejects nonzero crop; the raw comparator's even-crop
support does not qualify that Kodi gate. Do not clear crops or weaken admission.
Actual combined Kodi EGL/direct mapping, reset/lifecycle, matched pictures and
performance remain separate tests. Retained SDK EL9615 and target19379 artifacts
were not replaced by this workflow.
