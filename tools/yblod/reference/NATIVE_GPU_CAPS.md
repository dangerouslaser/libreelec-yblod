# GPU integer-compute capability check

The LibreELEC VM exposes a usable **desktop OpenGL 4.6** context on the requested
Intel render device, including compute shaders, storage buffers and advertised
64-bit integer shader support. Its separately tested **OpenGL ES 3.2** context
does not advertise `GL_ARB_gpu_shader_int64`.

This is a capability result, not a shader correctness or performance result.
No shader was compiled or run, and no compute, drawing, presentation or Kodi
operation was submitted. Desktop OpenGL support does not automatically make a
desktop shader usable inside Kodi's existing OpenGL ES context.

## Device and contexts actually queried

2026-10-05, `/dev/dri/renderD128`, Mesa 26.2.4, reported renderer
`Mesa Intel(R) Iris(R) Xe Graphics (TGL GT2)`.

| Query | Desktop OpenGL | OpenGL ES |
|---|---|---|
| Requested minimum context | 4.3 core | 3.1 |
| Actual context | 4.6 core | 3.2 |
| Compute/storage-buffer core version | Available | Available |
| `GL_ARB_gpu_shader_int64` advertised | Yes | No |
| Exact extension entries recorded | 235 | 168 |
| Software renderer detected | No | No |
| Query errors | None | None |

Both contexts reported 1,024 maximum work-group invocations, 65,536 bytes of
shared compute memory, 16 compute shader-storage blocks and 80 storage-buffer
bindings. The full per-axis limits and maximum storage-block size are preserved
in the report. Queried maxima are not safe memory-allocation budgets.

The report is
[native-gpu-caps-libreelec-20261005a.json](results/native-gpu-caps-libreelec-20261005a.json).
It records exact extension names, individual GL/EGL query outcomes, requested
device association, cleanup outcomes, source/binary hashes, installed-library
hashes and memory counters. GL success is numeric zero; EGL success is
`EGL_SUCCESS`, numeric 12288. The installed-library snapshot is not represented
as a complete inventory of modules actually loaded by the driver.

## Device binding and safety

`native_gpu_caps.c` accepts an explicit `/dev/dri/renderD<number>` path. It opens
that node, verifies a character device, enumerates EGL devices, and accepts only
one device whose advertised DRM render-node path has the same device identity.
It then creates a device-platform EGL display and checks the display's associated
EGL device before creating either context. Software devices/renderers are
rejected, not silently treated as the Intel GPU.

Contexts are made current without a surface and are separately unbound and
destroyed. A cleanup failure prevents the subsequent context test. The display
is terminated, the EGL thread released, and the owned render-node descriptor
closed. All cleanup succeeded in the recorded run.

There is no default-display fallback, window or pbuffer creation, shader API,
buffer allocation, framebuffer object, draw, dispatch, swap or KMS call. The
tool does not modify permissions, display modes, Kodi configuration or playback.
EGL/driver initialization can allocate context resources; this is not a claim
that querying a graphics implementation has literally no internal activity.

Top-level `status: complete` means discovery and cleanup completed. It can
legitimately contain an unavailable context; always inspect each context's
status, version, extension flags and query errors. It never means arithmetic
execution or performance has been validated.

## Build, tests and resources

The recorded executable was built with the existing LibreELEC GCC 16.2.0 SDK,
strict C11 warnings-as-errors and `-lEGL`. The build container had no network,
one CPU, a 512 MiB memory limit and no container swap. No additional libraries
were installed. Its direct dependencies were existing `libEGL.so.1` and
`libc.so.6`, with required glibc symbol versions no newer than 2.34; the VM had
glibc 2.44. Resolved dependencies were inspected before execution.

- Executed source SHA256: `1fe894943f81fb893e8086f2923964d4c008a48c0133fbe428fd8fd745da8ad7`
- Executable SHA256: `d0a92ccf07b002eff11f8f812a0c77f33c06d1d1aa891feb538b55d408538b0b`

Six no-GPU tests passed locally and on Ollie. They exercise strict node-path
validation, exact extension-token matching, software-renderer rejection,
separate desktop/ES version gates, JSON escaping and the absence of prohibited
workload entry points. These tests do not mock a complete EGL implementation or
prove every possible driver error path.

The actual query ran inside an enforced 512 MiB/no-job-swap VM scope. Charged
peak memory was 42,569,728 bytes, child peak RSS 66,912 KiB, and pressure/OOM/
OOM-kill counters and job swap were zero. The query took 0.189 seconds. These
different CPU memory accounting measures do not bound every GPU allocation.
Kodi remained active afterwards. No display surface was created.

With existing EGL and desktop GL development headers:

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
  native_gpu_caps.c -lEGL -o native_gpu_caps
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  ./native_gpu_caps /dev/dri/renderD128
python3 -m unittest test_native_gpu_caps
```

Use an SDK-compatible binary on LibreELEC. The recorded run kept the exact raw
JSON and stderr in a fresh diagnostic subdirectory and independently pinned
the executable before and after execution.

## Meaning for the next experiment

The result removes one uncertainty: a separate desktop-GL compute context with
advertised integer64 support is available on this machine. It does not establish
native-speed 64-bit operations, 128-bit shader arithmetic, signed-floor behaviour,
overflow correctness, texture precision, synchronization or GLES interoperability.

The next appropriate gate is a small, independently checked synthetic integer
shader test against the C/Python arithmetic—not production integration or a
picture-matching adjustment. Wide intermediate arithmetic still requires its
own explicit representation and tests. Existing hardware EL scaling can remain
a separate stage while these contracts are established.

## Primary API references

The explicit render-node association follows
[EGL_EXT_device_drm_render_node](https://registry.khronos.org/EGL/extensions/EXT/EGL_EXT_device_drm_render_node.txt),
and the display is created from the selected device using
[EGL_EXT_platform_device](https://registry.khronos.org/EGL/extensions/EXT/EGL_EXT_platform_device.txt).
The no-surface context operation is described by
[EGL_KHR_surfaceless_context](https://registry.khronos.org/EGL/extensions/KHR/EGL_KHR_surfaceless_context.txt).
The advertised integer extension is
[ARB_gpu_shader_int64](https://registry.khronos.org/OpenGL/extensions/ARB/ARB_gpu_shader_int64.txt);
an extension string is an implementation capability declaration, not the result
of an arithmetic execution test.
