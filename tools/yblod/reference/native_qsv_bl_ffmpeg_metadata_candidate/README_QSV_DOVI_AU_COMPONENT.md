# HEVC QSV Dolby access-unit transaction component

This GPL-3.0-or-later component uses FFmpeg 9.0.2's actual NAL splitter, Dolby parser, and resolved metadata snapshot builder. It adapts the project's earlier association/deep-clone ownership algorithms. It is a source-only component: no codec option or decoder integration is published in this batch, and the SDK is unchanged. The planned integration must remain default off and gated by `CONFIG_GPL`, `CONFIG_VERSION3`, and `CONFIG_HEVC_QSV_DECODER`.

## Restricted admission and ownership

Input must be one complete AnnexB access unit with exactly one layer-zero picture start. Continuation slices are allowed; a second first slice, malformed header, unsupported layer, or ambiguous trailer is rejected. Opaque enhancement-layer UNSPEC63 encapsulation is allowed without treating it as another base-layer picture. The eligible trailing RPU is selected with the native HEVC decoder's backwards scan. Prefix-only/RPU-only input and graceful parameter-change draining remain outside the initial restricted integration contract.

Preparation deep-copies resolved parser state, parses once, and builds immutable metadata/raw-RPU snapshots. The committed state is not mutated by preparation or a partial-consumption retry. Native parse errors are ignored in the same way as native HEVC: resulting state changes are retained when the complete access unit is accepted. A picture without a new RPU inherits resolved metadata but not an old raw-RPU side-data buffer. Before any resolved state exists, associated metadata is absent.

The table holds at most 64 distinct positive internal identities and never resets their generation at seek. Original signed/duplicate/absent timestamps are stored separately. Only actual hardware consumption of the entire access unit may publish state. Returned identities transfer exactly their own snapshot; unknown, duplicate, or still-prepared identities cannot borrow another picture's instructions. Flush releases table ownership; hardware retirement must be established by the future decoder integration first.

## CPU qualification only

The private fixture supplies a complete type62 HEVC NAL without an AnnexB delimiter. The public test constructs delimiters and synthetic picture/EL headers in memory; those minimal picture headers are admission fixtures, not decodable movie frames. No private bytes, input hash, or movie content are published.

The actual parser differential checks complete resolved state and pointer-origin equivalence, repeated and absent RPUs, truncation errors, independent allocation failure, snapshot output ownership, stale side-data removal, negative/duplicate source timestamps, exact reordered snapshots, table capacity, cancelled identities, and overflow. The tested RPU does not establish previous-RPU-reference behavior. These comparisons are not Dolby conformance or hardware timestamp qualification.

Reproduce with a private full-NAL fixture:

```sh
sh tools/yblod/reference/native_qsv_bl_ffmpeg_metadata_candidate/check_qsv_dovi_au.sh /path/to/private/frame.rpu.nal
```

The helper uses the existing reviewed FFmpeg 9.0.2 CPU fixture image, a 512 MiB cap, no additional swap, one CPU, no network, and no GPU access. Output is scalar results and public source hashes only. It does not copy input into public files.

## Still required

Actual MFX identity propagation and synchronization, stable hardware-allocator owner lifetimes, seek/drain/parameter-change handling, HEVC_QSV option integration, Kodi pre-open selection/mapped buffers, movie pixel equality, and playback performance remain separate work. In particular, a call to hardware close without a verified success status is not ownership proof.
