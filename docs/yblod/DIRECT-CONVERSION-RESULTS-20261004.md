# Direct conversion test: 2026-10-04

## Build and installation

- Image: `yblod-0.1-direct-test2`, built on Ollie and installed through the normal
  LibreELEC update mechanism on Petunia's LibreELEC VM.
- Build source: `643e57eeb9709cea69b0bd4e9f07338ea2ccdba6` on
  `experiment/direct-conversion` in Ollie's `Projects/libreelec-yblod` checkout.
- Update archive SHA-256:
  `b1199ba58a24ccc965c81390fd074ccd1d705043241d44d6bac331113d0af46b`.
- Six CPU math/source checks passed, and the full image build completed.
- Original SYSTEM, KERNEL and settings were backed up on the VM under
  `/storage/backup/yblod-before-direct-test-20261004/`. System/kernel backup
  hashes were checked against the installed originals before updating.

## Initial paired measurements

One 60-second measurement per mode per film, following a 10-second post-seek
warmup. 1917: approximately 10:10–11:10. Saving Private Ryan: 8:10–9:10.
Both files were confirmed as Profile 7 with active FEL reconstruction.
Quick Sync enhancement-layer scaling and hardware-level matching stayed on.
Subtitles and overlays were off during measurement. The log confirmed the new
path actually ran when requested; GPU client IDs remained stable.

| Film | Release GPU render busy | Direct GPU render busy | Relative reduction | Release CPU | Direct CPU |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1917 | 10.824% | 9.682% | 10.56% | 14.791% | 14.242% |
| Saving Private Ryan | 11.950% | 10.568% | 11.56% | 13.483% | 13.678% |

GPU percentages are per-process render-engine occupied time, with duplicate
file descriptors deduplicated. CPU percentages are relative to one core.
These are normal-speed playback measurements, not uncapped rendering benchmarks
or a claim that playback is 11% faster. GPU clocks were not locked. Sampled
active clocks were predominantly idle/1300 MHz, with some 1100 MHz readings.
No statistical significance or general improvement across titles is established
by a single pair per title. CPU differences are small and inconsistent.

Decoder and Quick Sync engine workloads stayed close between modes. Playback
positions advanced normally. The renderer reported zero stage failures and
zero presentation failures in each measured interval. These counters are not
decoder dropped-frame counters, and no visual smoothness judgment was made.

Raw JSON samples are retained on the VM in the backup directory above and on
Ollie under `Projects/libreelec-yblod/target/direct-test2-measurements/`.
The sampler and reproduction procedure are in
[DIRECT-CONVERSION-TEST.md](DIRECT-CONVERSION-TEST.md).

## Playback transitions and remaining validation

Opening the playback controls switched to the release RGB path; dismissing
them switched back to direct LMS. Playback continued and the subsequent
renderer summary still reported zero failures. Subtitles were re-enabled after
the controlled measurements. The experimental switch was left enabled for
interactive testing; its default in a fresh installation is still off.

Picture accuracy is NOT validated by these measurements. No matched-frame
capture comparison or external HDMI measurement was performed. Dark/saturated
colors, subtitle/menu transition appearance, and longer playback remain to be
checked. RGB clipping is intentionally removed only on the shortcut path, so
differences in affected colors require investigation before making it default.
