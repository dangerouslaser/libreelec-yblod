KEYFLAG LIBRARY BUILD AND READ-ONLY KODI LOADER EVIDENCE

One approved isolated libavcodec build completed exit0. Exact codec SHA256:
871a5b008e907d67bc4ba3b36cc9dbe932657505c194c9d2f34784309c394a95
18,839,544 bytes. Seven companion libraries are byte-identical to the qualified
c0eee bundle. Public headers, native-code/ABI guards, configuration, ELF exports,
SONAME and NEEDED contracts are unchanged. Original candidate whole-tree identity
was verified before and after. This report does not qualify hardware playback.

KEYFLAG_BUILD_RESULTS.json is the exact generated code-only report. It separates
base compatible-param provenance from new qsvdec/header identities. Resources
are recorded separately in BUILD_RESOURCES.json: 738,394,112-byte peak, all memory
events zero, zero swap. No media, runtime frame data or content hashes included.

Exact tested builder build_keyflag.py SHA012ac45a5e0be98784139330863b3a7a8d193c88a7ce2c8490a27112ad2c45e7
uses build_safety.py, an unchanged fa027 copy of the already reviewed/published
combined-Kodi safety controller. Four focused mocked tests pass locally/Ollie;
the inherited exact-CID/limits/cleanup helpers previously passed17mocked tests.
Command: python3 -B -m unittest -v test_keyflag

Source delta: only private qsv_dovi.h and qsvdec.c, frozen renderer-reviewed
d0612fbabd19dd9797d17191204d9d57b57789ff00fbab6d638d83f1c8e3350f and
a87bbcec949bc5668a0fdcf14100bf20901a9b9242c3df0627aa3ac4dd74e8ed.
The immutable AU token carries native-equivalent HEVC IRAP KEY classification;
associated output restores only KEY, bypassing the later IDR-only overwrite only
when metadata mode is ON. Default OFF unchanged. Renderer owns CPU/runtime proof.

Build reproduction requires the pinned SDK, image, c0eee source tree and exact
two new source files. Historical artifacts are immutable: choose a NEW lowercase
output suffix; no automatic retry. First run read-only --phase plan:
sudo python3 -B build_keyflag.py --phase plan \
  --sdk /home/bryan/Projects/libreelec-yblod \
  --public /home/bryan/Projects/libreelec-yblod-reconstruction \
  --sources /home/bryan/Projects/libreelec-yblod-reconstruction/target/qsv-bl-irap-key-20261006 \
  --output /home/bryan/Projects/libreelec-yblod-reconstruction/target/qsv-bl-keyflag-library-reviewed-fresh
Only after separate approval use --phase build. sudo reads root-owned preserved
files without changing permissions. Plan budgets:14,914files/226,295,943bytes.
Independent copies, no hardlinks. SDK/original/source/control read-only; only
fresh output writable. make-j1/libavcodec only; unchanged CFLAGS/LDFLAGS LTO1;
CPU1/4GiB/noSwap/noNetwork/noGPU. Private disk TMPDIR with sampled2GiB budget,
2GiB disk reserve; host launch6GiB memory/disk reserve, abort memory2GiB.
All Docker controls bounded and exact-ID only; terminal state confirmed and
failure resources retained. No source configure or ABI changes, no Kodi rebuild.

COMPLETED LOADER CHECK (NO KODI EXECUTION)
diagnose_kodi_keyflag_loader.py performed a separate readonly1GiB/noSwapCPU1
target-loader --list check of exact Kodi0436 with new871 library closure. It
preserves known explicit PulseAudio/Samba paths and precedence. It pins the old
27-file code closure, allows exactly one named libavcodec hash replacement and
verifies the other26files unchanged; separately verifies all8library identities.
Nine exact readonly mounts change (candidate root +8sysroot ELF binds). It does
not execute Kodi. The helper retains historical build paths/CID and a fresh-output
guard: do not rerun over the preserved result directory. The separately approved
check completed after the renderer trial: loader exit0, empty stderr,156 resolved
libraries, container exit0/noOOM. Peak826,818,560bytes, all memory events0, zero
swap. LOADER_RESULTS.json records pins and resources. This passes the new closure
loader gate, not combined Kodi playback or target deployment. No Kodi execution
or deployment occurred.
