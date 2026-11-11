# Kodi playback benchmark

Measures Dolby Vision playback in real Kodi on a bench image: full films
over NFS, a clean profile, audio passthrough, warm shader caches. The same
scripts run on every image, so two images can be compared; nothing that
only one image logs is a primary source.

| File | Runs on | Does |
| :--- | :--- | :--- |
| `install-image.sh` | workstation | puts an image on the N150 as a bench profile and boots it |
| `bench.py prepare` | workstation | copies `box/` to the box and prepares the profile |
| `bench.py run` | workstation | plays the matrix and writes one JSON per run |
| `bench.py analyse` | workstation | recomputes the JSON files from the raw files |
| `report.py` | workstation | Markdown comparison and summary JSON from result folders |
| `box/prepare-profile.sh` | box (busybox sh) | the profile settings, identical for every image |
| `box/sample.sh` | box (busybox sh) | one measurement window: raw counters only |
| `matrix.json` | | films, passages, which film plays in which scenario |

The workstation needs Python 3.9+, `ssh` and key access to the box as root.
Nothing is installed on the box; `box/` lives in `/storage/yblod-bench`.

## A new image, start to finish

```sh
cd yblod/tools/bench
BOX=root@192.168.1.179
NAME=y050t1                      # the bench profile's name: one per image
RESULTS=~/yblod-bench-results    # copied to Ollie afterwards

# 1. the image's KERNEL and SYSTEM (from the build host), onto the box
scp ollie:Projects/libreelec-yblod-vk/target/LibreELEC-Generic.x86_64-13.0-VERSION.kernel /tmp/KERNEL
scp ollie:Projects/libreelec-yblod-vk/target/LibreELEC-Generic.x86_64-13.0-VERSION.system /tmp/SYSTEM
./install-image.sh "${BOX}" "${NAME}" /tmp/KERNEL /tmp/SYSTEM

# 2. the profile (also waits for yblod-dv-prepare to build the pipeline cache)
./bench.py prepare --host "${BOX}" --image "${NAME}"

# 3. the matrix, twice (2 h 15 min), then the table against 0.4.1
./bench.py run --host "${BOX}" --image "${NAME}" --out "${RESULTS}" \
  --display-note "TV on, Dolby Vision picture mode"
./report.py "${RESULTS}/y041" "${RESULTS}/${NAME}" --md comparison.md --json comparison.json
rsync -a "${RESULTS}/${NAME}" ollie:yblod-050/bench/results/
```

`bench.py run` continues where it stopped: a run that has its JSON is
skipped (`--force` measures again), so after a `FAILED` line (the
workstation lost the network for longer than a minute, say) the same
command measures what is missing. `--scenarios A,B`, `--films 1917` and
`--reps 1 --first-rep 3` select part of the matrix. Keep the workstation
awake (`caffeinate -i` on a Mac): a repetition takes 66 minutes. The 0.4.1 baseline's raw
files are on Ollie in `~/yblod-050/bench/results/y041`; its summary is in
`yblod/docs/releases/data/`.

## The box

The owner's N150 (LG TV behind a Denon AVR) dual-boots from one eMMC:

- `mmcblk0p1` "System": LibreELEC's `KERNEL` and `SYSTEM` **and big-fella's
  boot loader**. `install-image.sh` writes there only through
  `/var/lib/yblod-bench/le-switch.sh` (on big-fella), which replaces
  `KERNEL`, `SYSTEM`, `syslinux.cfg`, `EFI/BOOT/grub.cfg`,
  `mount-storage.sh` and `bench-name` and nothing else.
  `le-switch.sh restore` puts the owner's LibreELEC back from
  `/var/lib/yblod-le-backup`.
- `mmcblk0p2` "Storage": the owner's LibreELEC data. A bench profile's
  `/storage` is `Storage:/.bench/NAME`; nothing outside `/.bench` is used.
  An existing `/.bench/NAME` is kept, so use a new name for a new image.
- `mmcblk0p3/p4`: big-fella. First in `BootOrder`, never changed. LibreELEC
  ("UEFI OS", `Boot0005`) is booted once with `efibootmgr -n 0005`; a reboot
  from LibreELEC returns to big-fella.

Every reboot and every Kodi restart is preceded by a check that nothing is
playing, and is not done otherwise: `Player.GetActivePlayers` in LibreELEC;
no `mpv` and no running audio stream in big-fella. `bench.py run` likewise
refuses to start while something plays, and checks that the box runs the
profile it was asked to measure (`/flash/bench-name`).

Do not use `paste` on the box: in LibreELEC it uploads its input to
paste.libreelec.tv.

## The profile

`box/prepare-profile.sh` makes these settings and no others, the same for
every image, and prints what it finds:

- LibreELEC's first-run wizard closed (`oe_settings.xml`
  `wizard_completed`), then Kodi is on its home screen;
- Kodi's web server on (user `kodi`, password `bench`; the scripts use
  JSON-RPC on `127.0.0.1:8080`, through `ssh -L` from the workstation);
- audio passthrough on for every format; audio device and passthrough
  device are the HDMI ALSA device that has a sink;
- "adjust display refresh rate" on start/stop, so 24p plays at 24 Hz and
  60p at 60 Hz;
- `DVBRIDGE_DIAGNOSTICS=1` in `/storage/.config/native-dv.env`: Kodi then
  writes its dropped/skipped counters to the log every 10 s on every image
  (0.4 does so by default, 0.5 only when asked; the line costs one read of
  Kodi's DRM fdinfo files per 10 s).

The Dolby Vision settings, the GUI resolution, the skin and everything else
stay as the image sets them on a fresh `/storage`. `session.json` records
the settings, the image's and the profile's `native-dv.env`, the checksums
of `KERNEL`, `SYSTEM`, `kodi.bin` and the engine, kernel, Mesa, the GPU's
frequency range and the RAPL limits.

On images with `yblod-dv-prepare` the boot service builds the engine's
pipeline cache (71 s on the N150 for 0.4.1); `prepare` waits for it and
`run` refuses to start while it runs.

## A run

1. **Warm-up pass, discarded.** `Player.Open` with the passage's resume
   offset, the scenario's state applied, 15 s + the window's length played,
   stop. It plays exactly what is measured afterwards, so Mesa's shader
   cache and the engine's pipeline cache (`/storage/.cache/dv-engine-vk`)
   hold everything the measured pass needs.
2. **Measured pass.** The same again: open, scenario state, 15 s to settle,
   then `box/sample.sh` records a **60 s window** on the box, then 11 s more
   playback (so that Kodi logs its counters once more), stop.

Between two passes Kodi is back in the menu at the menu's refresh rate.
Repetitions are whole passes through the matrix, so two repetitions of a
run are about an hour apart.

### Scenarios

| | Films | State |
| :--- | :--- | :--- |
| A | all four | plain playback: no OSD, subtitles off |
| B | all four | video OSD opened (`Input.ShowOSD`) and left open: seek bar and controls visible |
| C | 1917, Gemini Man | a text subtitle on: a generated SRT with a two-line cue on screen 3 s in every 4 (the films' own subtitles are bitmaps, and lines on screen should not depend on the dialogue) |
| D | 1917, Gemini Man | paused, then a seek to 20 s into the passage: the same frame every time; the skin shows its seek bar while paused |
| E | 1917, Gemini Man | Settings > Player > Dolby Vision > Output mode = Convert to HDR10 (`dvbridge.outputmode` 1), set before the film opens and put back after |
| F | all four | playback start: one discarded start, then three traced ones |
| P | all four | as A with the engine's GPU timing log on (`dvbridge.gputiming`, which sets `DVVK_PROFILE=1`): the cross-check of A, never the primary number |

Each run's JSON has `checks` and `valid`: Kodi in full-screen video, the OSD
as the scenario wants it at both ends of the window, no other dialog or
notification, subtitles as the scenario wants, audio really bitstreamed
(`Player.Passthrough`, a `pt-` audio decoder and the HDMI PCM in
`S16_LE`: IEC 61937 frames, 8 channels 192 kHz for TrueHD), the tunnel
signal committed (`dv=1`) with an HDR10 metadata blob only in E, the
position advanced by the window's length (or not at all in D), and no trace
events lost. A run that fails a check is marked `(!)` in the report.

## What is measured

All in the 60 s window, between two snapshots `t0` and `t1` that
`sample.sh` takes on the box. Rates use the snapshots' own clock readings.

**Frame time (the headline), `gpu.render_ms_per_presented_frame`.** The
time the GPU's render engine was busy for Kodi, divided by the pictures
presented. Busy time is the increase of `drm-engine-render` (amdgpu: `gfx`
+ `compute`) in `/proc/PID/fdinfo` of `kodi.bin`, summed over its DRM
clients, each `drm-client-id` counted once (Kodi holds several descriptors
per client). It covers the Dolby Vision engine (its own client, by far the
largest: `engine_client_ms_per_presented_frame`) and Kodi's GLES drawing of
the GUI; video decoding is on another engine and reported separately
(`video_ms_per_presented_frame`). Pictures presented are the flips counted
below. `render_ms_per_source_frame` divides by window x source frame rate
instead: the two differ exactly when pictures are not presented at the
source rate (0.4 at 60p).

**Cross-check, `engine_profile` (scenario P).** The engine's own GPU
timestamps: with `DVVK_PROFILE=1` it prints `dvvk profile: gpu MEAN ms (p95,
max)` per 120 frames to the journal. The report compares the mean of those
lines inside the window with the fdinfo figure of the same pass (and shows
A beside it, to see whether the log itself costs anything). The engine's
figure has no GUI drawing by Kodi and none of the driver's work outside
the engine's command buffers, so it should be slightly lower.

**Presentation, `presentation`.** From the kernel's
`drm:drm_vblank_event_delivered` tracepoint: one event per completed page
flip, with the vertical blank's sequence number from the hardware frame
counter. `flips` and `presented_fps` count the events in the window;
`gap_histogram` is the difference of consecutive sequence numbers, in
refresh periods (`{"1": n}` alone is a new picture every refresh;
`gap_sequence_head` shows the pattern). `refresh_hz` comes from the
vertical blank timestamps of `drm:drm_vblank_event`.
`gaps_off_cadence` counts gaps that are not one source frame long. The
tracepoint is DRM core, the same on i915 and amdgpu, and independent of
Kodi's counters and of whether a commit blocks or is queued. The number of
`drm_vblank_event` lines is *not* used: i915 turns the vertical blank
interrupt off between flips. `trace_events_lost` must be 0.

**Kodi's own counters, `kodi.dropped`, `kodi.skipped`.** From the
`DVBridge playback health` log lines (every 10 s): the totals at the first
line after the window minus those at the last line before it, a span of
up to 20 s more than the window (`counter_span_s`). `output_attempts_per_s`
is how many pictures the video player handed to the renderer.

**CPU, `cpu`.** `render_thread_pct`: user + system time of `kodi.bin`'s
main thread (Kodi renders and commits on it), in % of one core.
`process_pct`: the whole process, in % of one core (400 % = four cores).
`top_threads_pct` names the six busiest threads.

**GPU clock and power, `gpu_clock`, `power`.** `gt_act_freq_mhz` sampled
every 0.5 s; a sample of 0 means the GPU was asleep at that moment
(`share_asleep`), the others give `awake_mhz_mean`/`min`/`max`. The clock
is **not pinned**: this is what a user gets, and a faster engine may be
given a lower clock, which shows as a smaller gain in ms than in work.
`power.package_0_w` is the RAPL package energy over the window.

**Paused (D).** `gpu.render_busy_pct` (render busy time / window) and
`presentation.presented_fps` (flips per second while paused).

**Start (F), `start_s`.** `sample.sh` writes a trace marker, posts
`Player.Open` and traces flips for 12 s. `start_s` is the time from the
marker to the first flip after the last hole of more than 250 ms, i.e. the
first picture of uninterrupted presentation (the earlier flips are the
menu, the refresh change and the black Dolby Vision signal). Kodi's log
gives two secondary times from its `OpenFile` line: `kodi_signal_s` (signal
committed) and `kodi_first_frame_s` (first frame prepared; this line may not
exist on other images).

## Result files

```
RESULTS/NAME/session.json             the image, the box, the settings
RESULTS/NAME/FILM-SCENARIO-rN.json    one run: everything above, checks, player state
RESULTS/NAME/raw/FILM-SCENARIO-rN/    t0.* t1.* freq.txt trace.txt.gz audio.txt display.txt
                                      kodi.log (the measured pass) journal.txt driver.json
```

`report.py` writes the tables (rows film x scenario, columns images: ms per
frame with presented fps and drops/skips, flip gaps, CPU/clock/power,
paused, start, the two frame-time sources, run-to-run spread) and a summary
JSON with every repetition's numbers.

## Reading the numbers

- Compare images by ms per frame; the spread table says what is noise. On
  0.4.1 the two repetitions of every scenario, an hour apart, were within
  0.4 % of each other in ms per frame and within 2 % in presented fps.
  Single windows can still sit higher: of the four plain-playback windows
  per film (A and P), one of 1917's was 2.6 % above the others and both
  engine-log passes of 28 Years Later were 3 to 4 % above plain playback
  (that film leaves the GPU at about 600 MHz instead of 900+). Treat a
  difference under 3 % as nothing, and repeat a run that looks off.
- A lower presented fps than the source's is a defect of that image, not of
  the measurement; then also read `render_ms_per_source_frame`. Kodi's own
  counters do not show it: 0.4.1 presents Gemini Man at 40.5 of 59.94 fps
  with 0 dropped and about 10 skipped frames in the window.
- The box cannot see whether the TV is on. An accepted commit is not a wire
  capture: `kodi.signal` is what the kernel accepted (`dv=1`, the mode).
  Note the TV's state with `--display-note`.
- The passages: 1917 0:30:40, Saving Private Ryan 1:49:40 (the heaviest
  FEL passage), 28 Years Later 0:30:40, Gemini Man 0:30:40, as in the
  earlier comparisons. Each JSON records what Kodi said the stream is
  (`kodi.stream`, `kodi.engine`, `source_fps`).
