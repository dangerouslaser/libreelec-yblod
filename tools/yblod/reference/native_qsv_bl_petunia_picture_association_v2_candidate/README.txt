Petunia target raw BL picture-association.v2 proof (2026-10-06)

ACTUAL TARGET RESULT
One authorized standalone hardware trial passed on the target's actual render
device, existing iHD driver and staged stripped FFmpeg closure. 725 AUs accepted
and 725 frames returned on EACH route, decoder EOF for the finite window, all725
pictures paired against independently resolved native HEVC metadata and source
PTS/duration. Three selected 3840x2160 P010 pictures: all9planes exactzero sample
differences, including low-bit alignment. Real probe PID/GPU client/mapped-code
closure verified before handshake acknowledgement. Kodi19379 remained idle and
its process generation/binary unchanged; no Kodi playback/settings/mount changes.
No decoded pixel file or private media content/path/hash was exported. CPU frame
download was used only for in-memory diagnostics, not the product rendering path.

Scope is deliberately narrow: this target trial is not combined Kodi playback,
HDMI/display quality, full-film EOF, performance, seek/reset/reopen lifecycle or
previous-RPU coverage. All725actual AUs were new-RPU; previous/absent counts0.
Source identity is unchanged local stat only, not file-content immutability.
Picture-association.v2 excludes equality of triggering-packet DTS while requiring
known best-effort==source picturePTS, source duration and metadata association.
TransportDTS stays visible:665equal/60different pairs, max83ms,3bothunknown.
All3selected frameDTS values also matched. Never claim universal AVFrame equality.
Actual Kodi packet-duration forwarding is not proven by this library-level test.

EXACT ARTIFACTS
Probe da9791a63a48638be26098c85f728cfae31f3e6f5ea07618671365354b718367
70,128bytes; source/build proof in sibling native_qsv_bl_picture_association_v2_candidate.
Unchanged observer2b2f58cde3a4cba251c693debe54d30c20a05e4c4d62135887f53ae89b787186.
Stripped target codec60084d80290a491b1d37c104437ffc8c75e2033416e0f61c64bd29d4668230fc
derives from871a5b008e907d67bc4ba3b36cc9dbe932657505c194c9d2f34784309c394a95
with public ABI/dynamic symbols preserved (capture agent's separate stage proof).
Eight staged FFmpeg files were pinned; only actual probe dependencies are required
mapped. TARGET_CODE_CLOSURE.json is exact reviewed23file code closure51fe4ae8...
TARGET_OBSERVER_RESULTS.json and TARGET_RAW_SCALAR_RESULTS.json are byte-exact
persisted scalar reports, not reconstructed results. TERMINAL_SUMMARY.json is an
explicit authored summary of controller stdout plus independent terminal reads;
the original outer raw controller printed stdout, it did not create a disk report.

BOUNDED EXECUTION
Raw unit yblod-bl-picture-v2-raw1:1536MiB/noSwap/CPU1/PrivateNetwork,180s deadline,
owned control-group cleanup. Peak671,973,376bytes; allmemoryevents0; swap0;
observer9.9055s/controller10.5891s are diagnostic elapsed time, not playbackperf.
Launch requires targetMemAvailable>=2.25GiB, abortbelow768MiB; diskreserve32MiB.
Exact freshnonce in processargv plus atomic600mode ready/ACK binds actual unit
InvocationID, PIDgeneration and cgroup before observer/GPU admission. Unobserved
units are not adopted for cleanup. Success requires observedgeneration and unit
ExecMainStatus0/Resultsuccess/MainPID0, then exactownedstop and idleKodirecheck.

PRESERVED PREPARATION FAILURES
1. First attempt stopped before creating any unit: unused observe_subtitle_fixture
   was incorrectly required in sys.modules. Removed only that unused pin; all7
   actual imports remain exact-pinned. Regression checks actual imported paths.
2. CPU-only collector succeeded23files with35,569,664byte peak/events0/swap0.
   Its outer controller nevertheless failed cleanup: active/exited MainPID0 had
   no live ControlGroup, which the old cleanup wrongly demanded. Exact original
   false/cleanup_uncertain report is CLOSURE_OUTER_ORIGINAL_RESULTS.json. No live
   process remained. Manual exactownedstop occurred ONLY after checking the
   observed InvocationID, ExecMainPID and freshnonce checkpoint; inactive/dead
   MainPID0 confirmed. Collector was NOT rerun or its report relabeled.
3. Final cleanup permits active/exited MainPID0 only with alreadyknown generation
   and unchanged InvocationID; live-process guards remain strict. Sameowner and
   wrongowner regression tests pass. Successful raw trial used this corrected
   d791364a000358b12c0f7b8d6c0ba21363cce7e274bde099c6a628b825a49063 controller.
All original target folders/logs preserved. No automatic retry took place.

SOURCE/REPRODUCTION
Files contain exact tested code, including code-only512MiB/noSwapCPU1 collector
with PrivateDevices (no GPU), explicit stagedreceipt+loader/VPL/mfx/driver pins,
strict stagedFFmpeg origin checks and 'not found' rejection. Closure derives from
systemloader --list only; no program main or media operation. Readonly plan is
default. run_target_bl_closure_unit.py --phase run and raw controller --phase run
each require separate approval and fresh paths/unit names. Historical fixed names
are provenance, not permission to rerun/overwrite preserved results. Source pins
in SOURCE_PINS.json cover7actual imported helpers. All actual source/tool/closure/
targetidentity/probe hashes must be reviewed and provided; no inferred identities.
15mocked tests: python3 -B -m unittest -v test_target_bl_controller test_target_bl_closure
No binary, private input identity, live-proof record or frame buffer is included.
