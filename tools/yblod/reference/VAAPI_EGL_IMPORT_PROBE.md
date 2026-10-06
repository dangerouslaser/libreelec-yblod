# Synthetic VA → EGL raw-plane import gate

## Completed VM checkpoint

[Exact raw evidence](VAAPI_EGL_IMPORT_RESULTS.json) records both synthetic
formats on Intel iHD 26.3.5 and Mesa26.2.4. P010 passed actual texture2D
import and shader sampling: all 24 stored words matched the independent public
oracle, with zero mismatches. Its R16 and GR32 exported modifier was advertised
for ordinary texture2D use, not external-only. Charged peak was 36,700,160 bytes.

Y416 completed capability inventory only. Its exported modifier was advertised
as external-only; no packed-format reinterpretation, shader sampling or word
comparison was attempted. An empty observation list is not pixel agreement.
The normalized_texture flag describes the designed P010 reader, not a
demonstrated Y416 texture mode. Charged peak was 23,244,800 bytes.

Both jobs enforced 512 MiB/no swap, with zero memory-limit/OOM events and
unchanged Kodi activity. Public evidence was compared field-for-field with
the untouched raw records using integer-safe parsing. No movie data was used.

This is a narrow success for the P010 surface adapter, not a new playback
engine or performance improvement. Next expand patterns and resolutions,
exercise surface reuse, and separately establish exact Y416 packed access
before using either transport with reconstructed movie frames.

This standalone C experiment reuses the reviewed fixed 4×4 VA upload/export
lifecycle in a separate source file. It associates EGL with the exact render
device, queries exported DRM layer formats and their exact 64-bit modifiers,
and rejects `external_only` layouts for ordinary texture2D reads. Unsupported
cases finish as capability inventory, with no substitute RGB/YUV conversion.

P010 R16/GR32 layers are imported with their exported offsets, pitches and
modifiers. Desktop GL4.3 verifies normalized R16/RG16 storage and uses
`texelFetch` without filtering. The shader rounds each normalized component
times 65535 into a 32-bit unsigned word. This is **not integer texture import**;
exact preservation requires the actual 24 stored 16-bit words to match.
The public synthetic observations are included for independent oracle checking.

Y416 is capability inventory only: the 12-bit render-target contract and packed
component ordering are not assumed to preserve the synthetic low-bit pattern.
No media, Dolby metadata, scaling, reconstruction, renderer or playback is used.
Successful sampling is not a zero-copy or real-playback performance proof.

The GPU fence waits at most five one-second intervals. The caller must also
enforce an overall subprocess timeout because VA/driver calls can block.
Imported images/textures/context are destroyed before the VA surface and owned
export FDs. Modifiers remain uint64 values, never floating-point JS numbers.
Host helper tests run with UBSan; optional CLI guards need
`YBLOD_VAAPI_EGL_IMPORT_PROBE_BINARY`. No host test claims GPU sampling occurred.

Schema: `yblod.vaapi-egl-import-probe.v1`. Read `egl_import.actual_shader_read`,
compared count, mismatch count and reason together; an empty observations array
means no actual read, not an exact match. Normalized-16 recovery and no filtering
describe only the explicitly verified P010 branch.
Top-level `complete` means the allocation/export and inventory completed;
unsupported EGL capabilities do not mean the shader import test passed.
