# Native planar output experiment

This opt-in candidate passes the reconstructed integer Y, Cb and Cr planes directly to the colour renderer. It replaces the full-size RGBA32F YCC image with the same chroma expansion inside the rendering shader. Reconstruction, release RGB colour conversion, transport packing and GUI eligibility remain unchanged.

`DVBRIDGE_NATIVE_PLANAR_OUTPUT=1` enables the candidate. The default is off. It requires `DVBRIDGE_NATIVE_FP32=1` and `DVBRIDGE_NATIVE_COLOUR_NO_REIMPORT=1`. The existing `DVBRIDGE_NATIVE_PACKED_OUTPUT` flag independently controls packed output; leaving it off retains composition.

The engine checks every reconstructed sample for the 12-bit range before importing all three planes. Frame association, finite completion waits and decoded-surface ownership remain enforced. Capture metadata reports `native_planar`, and renderer diagnostics count frames that actually used the planar route.

Strict SDK compilation, production argument guards and dyadic arithmetic tests pass. Three matched frames from each of Saving Private Ryan and 1917, plus one numbered FEL frame, preserve the picture and Dolby metadata payload with planar output enabled. Three non-packed composition frames also pass. Only validated transport update IDs and their CRCs may differ; no pixel tolerance is accepted. Zoom fallback and playback performance qualification remain pending. These sampled checks do not establish universal equivalence or Dolby conformance.

The rebuilt Kodi candidate is installed on the test VM. Its complete SDK build passed with a 4 GiB memory limit, one CPU and serial compilation and linking. Peak memory was 2.20 GiB, with no memory-limit or out-of-memory events and no swap use. The qualified packed-output binary remains available for rollback.

Frame results are retained in [Saving Private Ryan](NATIVE_PLANAR_SPR_FRAME_RESULTS.json), [1917](NATIVE_PLANAR_1917_FRAME_RESULTS.json), [the numbered FEL test](NATIVE_PLANAR_FEL_FRAME_RESULTS.json), and [non-packed composition](NATIVE_PLANAR_COMPOSED_FRAME_RESULTS.json). [Build results](NATIVE_PLANAR_FALLBACK_BUILD_RESULTS.json) identify the tested candidate. If planar rendering is ineligible, the same composer can materialize its existing planes as RGBA without selecting the older reconstruction engine; committed metadata history is preserved during the retry.

## Synthetic renderer checks

On Intel UHD 770 with Mesa 26.2.4, four small synthetic source sizes passed a float to planar to float comparison in a desktop OpenGL context. All 54,784 compared RGBA32F component values, including alpha, and 1,024 metadata packet words were bit-identical. Twelve invalid-admission checks passed, and cleanup completed. The 512 MiB run peaked at 167,624,704 bytes with no out-of-memory events or swap use. This checks the small-source colour renderer, not movie playback or packed scanout.

The reproducible probe and SDK build helper are in `native_planar_output_candidate`; scalar results are in `NATIVE_PLANAR_SYNTHETIC_RENDER_RESULTS.json`. The renderer uses its fixed-size output allocation, but only the synthetic source rectangle is compared.

The small-source probe accepts dimensions from 4 to 64 pixels, divisible by four. Run the SDK build helper with the SDK root, patched Kodi source directory and an existing output directory. GPU execution takes a render node, an unused compatibility checkpoint argument and optional width and height. Use the 512 MiB, no-extra-swap, one-CPU, network-disabled diagnostic guard.

Independent GPU validator checks also passed for out-of-range samples in each plane, incorrect dimensions and formats, wrong completion methods and reuse between validation and expansion. Those scalar results are in `NATIVE_PLANAR_VALIDATOR_RESULTS.json`; they do not qualify movie playback.

## Generated full frame transport check

A separate row-streamed 3840 by 2160 synthetic test passed float packed to planar packed to float packed comparison in a desktop OpenGL context. All 66,355,200 compared transport bytes, including metadata rows, were literally identical; 256 candidate packet words also matched. The test used flipped output, the existing hardware offsets and asymmetric active-area margins. It compares generated GPU transport data, not physical HDMI or movie playback.

The initial diagnostic reached the 512 MiB cap with eleven memory-limit events but no out-of-memory events or swap. Draining diagnostic upload work every 64 rows reduced its peak to 406,188,032 bytes with zero memory-limit events; pixel results stayed exact. This changed only the probe upload schedule, not the playback engine, and establishes no performance improvement. Source and the SDK build helper are in `native_planar_output_candidate`; scalar results are in `NATIVE_PLANAR_SYNTHETIC_PACKED_RESULTS.json`.

## GLES synthetic check

Requesting GLES 3.1, reported as GLES 3.2 by Mesa, exposed a missing precision qualifier on the shader helper sampler parameter. The required `highp usampler2D` qualifier is now applied in the package patch and candidate Kodi source. With that qualifier, the generated full-frame packed comparison matched all 66,355,200 bytes literally, including metadata rows. Peak memory was 470,982,656 bytes with zero memory-limit or out-of-memory events and no swap. A desktop OpenGL repeat with the same qualifier also passed.

Set `YB_PLANAR_PROBE_GLES=1` to select the probe's GLES context and framebuffer `glReadPixels` readback; the default remains desktop OpenGL. Results, including the initial compiler failure, are in `NATIVE_PLANAR_SYNTHETIC_GLES_RESULTS.json`. This tests synthetic textures in one GLES context, not producer-to-consumer EGL sibling imports, movie playback or physical HDMI output.

## Synthetic cross-context sibling check

Generated 4 by 4 and 8 by 6 Y/Cb/Cr fixtures passed desktop OpenGL 4.6 to GLES 3.2 import using the production EGL bridge helpers. All three R16UI siblings remained live before any plane was read or released. All 96 integer samples matched exactly, including 0 and 4095; six timed releases completed, and the original consumer binding was preserved after every import and release. Peak memory was 66,351,104 bytes under the 512 MiB limit, with zero memory-limit or out-of-memory events and no swap.

The source and SDK helper are `native_planar_output_candidate/native_planar_sibling_probe.c` and `build_native_planar_sibling_probe.sh`; scalar results are in `NATIVE_PLANAR_SYNTHETIC_SIBLING_RESULTS.json`. This qualifies generated cross-context texture imports, not the native context's atomic three-plane publication, decoded-surface ownership, movie playback or physical HDMI output.

## Host checks

Run `python3 -m unittest discover -s tools/yblod/reference -p test_native_planar_math.py -v` for the arithmetic and source-contract checks. These are not device pixel tests.

`native_planar_contract_probe.c` exercises the real context implementation without EGL or VA execution. Compile it with assertions enabled, the engine include directories and the experimental playback library dependencies. It includes the context implementation to test private mode guards; do not additionally link that context object directly. Static archive linking pulls only the other required helpers.

The Kodi package patch changes only bridge sources. Package configuration copies the canonical `engine/experimental` sources into Kodi after applying patches.
