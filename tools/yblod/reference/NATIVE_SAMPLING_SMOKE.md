# Python-free sampling diagnostic smoke

`native_sampling_smoke.c` builds and runs without Python, EGL or a GPU. It joins
three diagnostic APIs, not a playback pipeline: lossless LE U/Y/V/A unpacking,
explicit exact half-pixel sampling, and the separately named informative
Annex B integer resampler.

The LibreELEC SDK build and VM CPU-only run passed on 2026-10-05. The smoke
preserved fractional words, overshoot and alpha; sampled `[32768,32784]` into
32776 with the declared half-pixel contract; retained 65535/65472 above one;
and matched the independent Y/C vertical, final and global-tile literals.
No fractional reconstruction policy or complete pipeline was selected.

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
  native_sampling_smoke.c native_y416.c native_sampling_probe.c \
  native_annexb_probe.c -o native_sampling_smoke
./native_sampling_smoke
```

The target build used GCC 16.2.0, one compiler job, read-only source/SDK mounts,
and the existing network-disabled container with a 512 MiB/no-job-swap cap.
The VM run used a fresh standalone directory and a scope with the same cap.
Peak charged scope memory was 1,024,000 bytes; job swap and max/OOM events were
zero. This tiny fixture's charged memory is not a full-frame memory requirement,
total system/GPU memory or playback timing. Kodi remained active; no binaries,
libraries, display settings or playback defaults were replaced.

The [public checkpoint](results/native-sampling-smoke-libreelec-20261005a.json)
pins the binary and source files. Binary hashes matched Ollie and the VM before
execution and the VM afterwards. Headers/sources are diagnostic inputs rather
than proof of loaded Kodi behavior or Dolby conformance.
