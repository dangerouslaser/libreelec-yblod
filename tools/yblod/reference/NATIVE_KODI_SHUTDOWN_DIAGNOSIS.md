# Existing integer-build shutdown failure: diagnostic checkpoint

A shutdown abort was reproduced in the existing integer/timing playback build,
before activation of the experimental FP32 composer. A private core and its
verified matching executable were examined with selectively loaded symbols.
Neither the core nor runtime libraries belong in the public repository.

The allocator detects `corrupted size vs. prev_size while consolidating` while
the main thread is destroying an EGL context during application cleanup:

```
malloc_printerr / _int_free_merge_chunk / _int_free_chunk
  util_vma_heap_free
  bo_close / iris_bo_unreference
  iris_destroy_batches / iris_destroy_context
  tc_destroy / st_destroy_context_priv / st_destroy_context
  dri_destroy_context / Mesa EGL cleanup
  CEGLContextUtils::Destroy
  CApplication::Cleanup / CApplication::Run / main
```

Runtime Mesa and the SDK Mesa binary matched byte-for-byte. The retained Mesa
build's `.text` also matched, allowing local symbols to resolve the driver
frames without assuming that differently built symbols are interchangeable.
The successful focused debugger run peaked at approximately 118 MiB under a
512 MiB/no-extra-swap cap, with zero memory-limit/OOM events. An earlier attempt
to automatically load all dependency symbols exceeded that diagnostic cap;
it was replaced by selective symbol loading, not a larger uncontrolled job.

This establishes where corruption was **detected**, not where it originated.
The stack is not a direct call to the native composer's destruction function.
It does not prove a Mesa defect or clear the native integration of earlier
ownership mistakes. The preceding output-restoration failure is relevant
context, not demonstrated causation.

A concrete ordering issue warrants instrumentation: when `EndDVBridge()` fails,
`CWinSystemGbmGLESContext::DestroyWindowSystem()` returns before its explicit
renderer reset and base teardown. `CApplication::Cleanup()` ignores that return
value and still resets the window-system owner. Subsequent member/destructor
cleanup can therefore reach EGL-owner destruction despite the earlier message
about retaining scanout state. This is not proof that destructor cleanup is
incorrect; record its actual native-release and ownership state before choosing
a change.

Source locations in the inspected Kodi tree (before adding shutdown logging):

- `xbmc/windowing/gbm/WinSystemGbmGLESContext.cpp:1047`: early return on failed
  output restoration skips explicit renderer reset/base teardown.
- `xbmc/application/Application.cpp:1782`: the return value is ignored before
  `m_pWinSystem.reset()` at line 1785.
- `xbmc/utils/EGLUtils.cpp:186`: destructor calls `Destroy()`; line 537 starts
  context/surface/display teardown, and line 549 destroys owned contexts.
- `xbmc/cores/VideoPlayer/VideoRenderers/DVBridgeGLES.cpp:148`: destructor calls
  `ReleaseNative()`; line 488 retains uncertain native cleanup rather than
  explicitly freeing pending resources.

Read-only import audit found no obvious exported-fd double-close: exported
descriptor fds are deduplicated and closed after EGL import. Native imports
delete owned GL textures before EGLImages; the output bridge waits for its
consumer before deleting sibling textures/images. The native context does not
call `eglTerminate` or `vaTerminate`; those displays belong to the application.
These checks narrow the investigation but do not constitute lifetime proof.

The next useful investigation is the shutdown ordering around failed output
restoration, retained renderer resources, and destruction of the borrowed EGL
display, together with imported dma-buf/buffer-object lifetimes. No lifetime
checks, waits, or retention safeguards should be removed merely to suppress
this shutdown symptom. A fix requires evidence and repeated stop/restart
qualification on the actual playback path.

## Diagnostic-only patch qualification

`kodi-9999-yblod-11-native-shutdown-diagnostics.patch` adds logging at window
restoration, native renderer cleanup, and EGL context/display destruction. It
does not change call order, fences, retention, or cleanup decisions. EGL return
values are recorded without adding error queries or recovery actions.

The patch dry-run passed against the current Kodi source. Three isolated source
copies compiled successfully with the existing SDK/compiler commands, preserving
all flags and adding only the original source-parent quoted-include search path.
Each job ran serially with a 512 MiB memory cap, no extra swap, one CPU, and no
network access. No full Kodi link or runtime qualification is implied:

| Unit | Peak memory | Memory-limit/OOM events | Swap peak |
|---|---:|---:|---:|
| `DVBridgeGLES.cpp` | 330,559,488 B | 0 | 0 B |
| `EGLUtils.cpp` | 335,753,216 B | 0 | 0 B |
| `WinSystemGbmGLESContext.cpp` | 417,705,984 B | 0 | 0 B |
