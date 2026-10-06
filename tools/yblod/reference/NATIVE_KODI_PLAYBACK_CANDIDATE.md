# Native Kodi playback candidate — 2026-10-05

The complete opt-in Kodi candidate compiled and linked successfully: 82 dependency-aware build actions, including all changed-header consumers and 14 native C objects. The final link used 429 serial LTO jobs. Peak memory was 2,362,478,592 bytes under a hard 4 GiB ceiling, with no swap or memory events. See the [actual build checkpoint](results/native-kodi-build-checkpoint-20261005.json).

The candidate was transferred with its hash verified, installed through a temporary bind mount, and started with the runtime opt-in. Kodi remained active with zero unexpected restarts and answered its JSON-RPC health check. The original squashfs executable remains intact. See the [installation/startup checkpoint](results/native-kodi-install-checkpoint-20261005.json).

**Native movie playback has not yet been tested.** All five Intel display connectors currently report disconnected. The TV must be connected to petunia's HDMI output and turned on before testing the actual Dolby renderer. A playing base layer, or a synthetic GPU result, is not proof that the new engine presented movie frames. The next test is 1917, checking the native presented-frame log markers and playback stability before making performance or colour-accuracy claims.

The [regression summary](NATIVE_PLAYBACK_REGRESSION_SUMMARY.md) records 1,305 reference tests with no failures/errors and one discovery skip; that SDK-only contract test passed separately. Build/runtime instructions are in [the playback context documentation](NATIVE_PLAYBACK_CONTEXT.md). The unchanged new hook patch is placed after its prerequisites in `projects/Generic/patches/kodi/`, not the earlier common package patch phase.

The temporary test installation and runtime drop-in disappear on reboot. A manual rollback for this specific test installation is:

```sh
systemctl stop kodi
umount /usr/lib/kodi/kodi.bin
rm -f /run/systemd/system/kodi.service.d/yblod-native-playback.conf
systemctl daemon-reload
systemctl start kodi
```

These commands assume this documented candidate bind mount is still installed; inspect the active mount before unmounting any different installation.

## Connected-display attempt — 2026-10-06

HDMI-A-2 became connected. Restarting Kodi refreshed the display information and enabled Dolby output. The first 1917 test attempted native reconstruction but rejected the base-frame chroma declaration and used the existing renderer instead. The existing path reported no drops or skips through 70 seconds; this is not native-engine performance evidence. See the [first playback attempt](results/native-kodi-first-playback-attempt-20261006.json).

The remaining work is the real Kodi source/storage adapter: its surface-backed path does not hand the renderer the same frame object as the standalone FFmpeg tests. Preserve exact public source properties and Dolby metadata, retain the actual render picture, and validate its pool generation through completion. Do not guess a chroma location, manufacture a hardware-frame context, or label fallback playback as success. Native playback and stop/restart safety must be tested after that adapter is built.
