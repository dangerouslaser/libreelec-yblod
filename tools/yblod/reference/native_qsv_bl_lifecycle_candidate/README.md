# Base-layer QSV lifecycle candidate

This isolated source increment preserves the historical integrated probe at `../native_qsv_bl_compare_probe.c`. The copied headers are identical to that baseline's headers. Enable the candidate's lifecycle path explicitly with `YB_BL_PROBE_LIFECYCLE=1`; the default remains OFF.

`NATIVE_QSV_BL_LIFECYCLE_HOST_RESULTS.json` records synthetic CPU accounting, mocked NULL-drain progression and CPU AVFrame reference tests. The strict second attempt passed with a 35,082,240-byte peak under a 512 MiB limit, one CPU, zero swap and zero memory events. The first compile failure is retained in the report.

The fixture covers bounded send/receive progression, accepted-count and complete-picture accounting, paired-picture checks, pending snapshot rejection, deadline expiry and epoch reset. It does not qualify hardware decoding, mapped MFX owner lifetime, actual OFF runtime equivalence, fixed-window hardware association, natural full-film EOF, Kodi playback or Dolby output.

To reproduce the CPU fixture, run `bash build_bl_lifecycle_cpu.sh` inside the pinned SDK container identified in the report, with cgroup v2 memory limited to 536870912 bytes, swap disabled, at most one CPU, no network and no GPU devices. Set `SDK_ROOT` to the original LibreELEC FFmpeg 9.0.2 SDK, `LIFECYCLE_SOURCE_DIR` to this directory and `PROBE_OUTPUT` to an existing writable output directory. Mount the SDK and sources read-only. The helper verifies the resource bounds, compiles against the SDK public headers/libraries, executes the fixture and reports hashes and resource counters. This reproduction does not execute media or a real decoder.
