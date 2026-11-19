# Playback health diagnostics

With `DVBRIDGE_DIAGNOSTICS=1` set, or Kodi's debug logging on, DV playback records one summary every 10 seconds while pictures reach the video output, including when the information panel is closed (kodi-9955). Otherwise nothing is sampled. No GPU synchronization or pixel readback is added.

- Native dropped/skipped totals and interval deltas, with counter-reset detection.
- Source frame rate, output attempts, playback speed, stalled state and picture timestamp.
- Video queue fill and duration, and bitrate.
- Kodi render-engine occupancy averaged over the interval, from DRM accounting. This is not total GPU or hardware decoder utilization. Unsupported counters report `unavailable`.
- Pause, speed, flush, reset and resynchronization transition count. An interval with transitions is not steady-state playback.

The initial interval establishes a baseline. Output attempts are not displayed frames. Native counters do not identify the responsible pipeline stage by themselves. A completely stalled output cannot emit another summary until it resumes; correlate with existing decoder, renderer and kernel messages.

`DVBRIDGE_DIAGNOSTICS=0` turns all of Kodi's added diagnostics off ([DIAGNOSTICS.md](DIAGNOSTICS.md)). There is no user setting.
