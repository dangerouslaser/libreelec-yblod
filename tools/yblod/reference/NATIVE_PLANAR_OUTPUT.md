# Native planar output experiment

This opt-in candidate passes the reconstructed integer Y, Cb and Cr planes directly to the colour renderer. It replaces the full-size RGBA32F YCC image with the same chroma expansion inside the rendering shader. Reconstruction, release RGB colour conversion, transport packing and GUI eligibility remain unchanged.

`DVBRIDGE_NATIVE_PLANAR_OUTPUT=1` enables the candidate. The default is off. It requires `DVBRIDGE_NATIVE_FP32=1` and `DVBRIDGE_NATIVE_COLOUR_NO_REIMPORT=1`. The existing `DVBRIDGE_NATIVE_PACKED_OUTPUT` flag independently controls packed output; leaving it off retains composition.

The engine checks every reconstructed sample for the 12-bit range before importing all three planes. Frame association, finite completion waits and decoded-surface ownership remain enforced. Capture metadata reports `native_planar`, and renderer diagnostics count frames that actually used the planar route.

Strict SDK compilation, production argument guards and dyadic arithmetic tests pass. Playback pixel preservation, hardware fault tests and performance qualification are pending. No speed improvement or universal accuracy claim is established by these checks.

## Host checks

Run `python3 -m unittest discover -s tools/yblod/reference -p test_native_planar_math.py -v` for the arithmetic and source-contract checks. These are not device pixel tests.

`native_planar_contract_probe.c` exercises the real context implementation without EGL or VA execution. Compile it with assertions enabled, the engine include directories and the experimental playback library dependencies. It includes the context implementation to test private mode guards; do not additionally link that context object directly. Static archive linking pulls only the other required helpers.

The Kodi package patch changes only bridge sources. Package configuration copies the canonical `engine/experimental` sources into Kodi after applying patches.
