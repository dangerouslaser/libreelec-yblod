#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Functional checks of Dolby Vision playback on a bench image (see README.md).

  checks.py --host root@BOX --image NAME --out RESULTS [--label VARIANT]
            [--only pause,seek,gui,verify,cadence,sequence] [--films 1917,gemini]

Drives Kodi the way a viewer does (pause, frame step, seeks, OSD, subtitles,
stop and start) while the kernel traces the page flips, and writes
RESULTS/LABEL/checks/CHECK-FILM.json (what was done, what was seen, what
failed) with the raw files in RESULTS/LABEL/checks/raw/. Nobody looks at the
TV: a check passes on flips, positions, counters and log lines. Python 3.9+,
standard library only; uses bench.py's connection and parsers.
"""

import argparse
import collections
import json
import os
import re
import statistics
import sys
import time

import bench
from bench import BOX_DIR, BenchError, log

SETTLE = 15
# Two titles outside the engine (ffprobe: no Dolby Vision configuration record).
SDR = {"title": "Airplane! (1980)", "file": "Airplane! (1980)/Airplane! (1980).mkv",
       "start": "0:20:00", "expect": "SDR, H.264 1080p, 23.976 fps", "engine": False}
HDR10 = {"title": "Alien (1979)", "file": "Alien (1979)/Alien (1979).mkv",
         "start": "0:20:00", "expect": "HDR10 without Dolby Vision, HEVC 2160p, 23.976 fps",
         "engine": False}


# ---------------------------------------------------------------- the box

def mark(box):
    """Where Kodi's log, the journal and the kernel log are now."""
    out = box.ssh("wc -l < /storage/.kodi/temp/kodi.log; date +%s; dmesg | wc -l").split()
    return {"line": int(out[0]), "epoch": int(out[1]), "dmesg": int(out[2])}


def logs_since(box, m, raw):
    """Kodi's log, Kodi's journal (the engine writes there) and the kernel log since mark()."""
    os.makedirs(raw, exist_ok=True)
    text = {
        "kodi.log": box.ssh(f"tail -n +{m['line'] + 1} /storage/.kodi/temp/kodi.log"),
        "journal.txt": box.ssh("journalctl -u kodi -o short-unix --no-pager "
                               f"--since @{m['epoch']}", check=False),
        "dmesg.txt": box.ssh(f"dmesg | tail -n +{m['dmesg'] + 1}"),
    }
    for name, t in text.items():
        with open(os.path.join(raw, name), "w") as f:
            f.write(t)
    return text


def steps_script(out, steps):
    """A busybox script doing `steps` [(at_s, name, action)] with a trace marker each.

    action: None, ("rpc", method, params) or ("send", builtin). The marker is
    written just before the action; steps.txt has the box's clock for both
    ends of it."""
    lines = [
        "#!/bin/sh", f"OUT='{out}'", "T=/sys/kernel/tracing/trace_marker",
        "start=$(date +%s%N)",
        "at() {",
        "  rem=$((($1 * 1000000 + start - $(date +%s%N)) / 1000000))",
        "  [ \"${rem}\" -gt 0 ] && sleep \"$((rem / 1000)).$(printf %03d $((rem % 1000)))\"",
        "}",
        "step() {",
        "  echo \"bench:$1\" > \"${T}\"",
        "  echo \"$1 $(date +%s.%N)\" >> \"${OUT}/steps.txt\"",
        "}",
        "done_at() {",
        "  echo \"$1.done $(date +%s.%N)\" >> \"${OUT}/steps.txt\"",
        "}",
    ]
    requests = {}
    for at, name, action in steps:
        lines.append(f"at {int(at * 1000)}")
        lines.append(f"step {name}")
        if action and action[0] == "rpc":
            requests[name] = {"jsonrpc": "2.0", "id": 1, "method": action[1],
                              "params": action[2]}
            lines.append(f"curl -s -m 20 -u {bench.RPC_AUTH} -H 'Content-Type: application/json' "
                         f"-d \"@${{OUT}}/req/{name}.json\" http://127.0.0.1:8080/jsonrpc "
                         f"> \"${{OUT}}/reply/{name}.json\"")
            lines.append(f"done_at {name}")
        elif action and action[0] == "send":
            lines.append(f"kodi-send --action='{action[1]}' > /dev/null 2>&1")
            lines.append(f"done_at {name}")
    return "\n".join(lines) + "\n", requests


def timeline(box, name, raw, seconds, steps):
    """Trace the flips for `seconds` while the box performs `steps`; fetches the raw files."""
    remote = f"{BOX_DIR}/run/{name}"
    script, requests = steps_script(remote, steps)
    box.ssh(f"rm -rf '{remote}'; mkdir -p '{remote}/req' '{remote}/reply'")
    box.write(f"{remote}/steps.sh", script)
    for step, request in requests.items():
        box.write(f"{remote}/req/{step}.json", json.dumps(request))
    box.ssh(f"sh {BOX_DIR}/sample.sh '{remote}' {seconds + 4} & sleep 2; "
            f"sh '{remote}/steps.sh'; wait", timeout=seconds + 90)
    box.fetch(remote, raw)
    return read_timeline(raw)


def read_timeline(raw):
    marks, flips, lost, period_ms = bench.trace(raw)
    t0 = bench.snapshot(raw, "t0")
    epochs = {}
    for line in bench.read(f"{raw}/steps.txt", "").splitlines():
        k, v = line.split()
        epochs[k] = float(v)
    replies = {}
    folder = os.path.join(raw, "reply")
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        try:
            with open(os.path.join(folder, f)) as fh:
                replies[f[:-5]] = json.load(fh)
        except ValueError:
            replies[f[:-5]] = None
    return {"marks": marks, "flips": flips, "lost": lost, "period_ms": period_ms,
            "epochs": epochs, "replies": replies, "log_offset": t0["log_offset"]}


def window_numbers(raw):
    """GPU, flips and CPU between sample.sh's two snapshots."""
    a, b = bench.snapshot(raw, "t0"), bench.snapshot(raw, "t1")
    seconds = b["epoch"] - a["epoch"]
    marks, flips, lost, period_ms = bench.trace(raw)
    inside = [f for f in flips if marks["t0"] < f[0] <= marks["t1"]]
    render = video = 0.0
    for key, ns in b["engines"].items():
        d = (ns - a["engines"].get(key, ns)) / 1e6
        if key[1] in ("render", "gfx", "compute"):
            render += d
        elif key[1] in ("video", "dec", "video-enhance"):
            video += d
    threads = {tid: t for tid, (_, t) in b["threads"].items()}
    main = (threads.get(a["pid"], 0) - a["threads"].get(a["pid"], ("", 0))[1])
    power = {}
    for zone, (uj, wrap) in b["rapl"].items():
        if zone in a["rapl"]:
            d = uj - a["rapl"][zone][0]
            power[zone] = round((d + wrap if d < 0 else d) / 1e6 / seconds, 2)
    gaps = [y[1] - x[1] for x, y in zip(inside, inside[1:])]
    return {"window_s": round(seconds, 2), "flips": len(inside),
            "flips_per_s": round(len(inside) / seconds, 3),
            "refresh_hz": round(1000 / period_ms, 3) if period_ms else None,
            "gap_histogram": {str(k): v for k, v in sorted(collections.Counter(gaps).items())},
            "render_busy_pct": round(100 * render / (seconds * 1000), 2),
            "render_ms": round(render, 1), "video_busy_pct": round(100 * video / (seconds * 1000), 2),
            "render_ms_per_flip": round(render / len(inside), 3) if inside else None,
            "render_thread_pct": round(100 * main / bench.CLK_TCK / seconds, 1),
            "process_pct": round(100 * (b["process_ticks"] - a["process_ticks"]) /
                                 bench.CLK_TCK / seconds, 1),
            "power_w": power, "trace_events_lost": lost}


# ---------------------------------------------------------------- reading logs

POOL = "decoded surfaces come from a new pool"
STAMP = bench.STAMP
FLIP_LINE = re.compile(r"DV flip: fb=(\d+) vblank_ns=(\d+) refreshes_since_last=(-?\d+) "
                       r"queued_to_vblank_ms=([\d.-]+)")
FLIPS_LINE = re.compile(r"DV flips queued=(\d+): on_time=(\d+) late=(\d+) blocking=(\d+) busy=(\d+) "
                        r"timeouts=(\d+) queued_to_vblank_ms mean=([\d.]+) max=([\d.]+)")
CLOSED = re.compile(r"Private source renderer closed: processed=(\d+) submissions=(\d+) "
                    r"presented=(\d+) held=(\d+)")
VERIFY = re.compile(r"dvvk verify: (\d+) frames checked, (\d+) differed")
PROFILE = re.compile(r"^(\d+\.\d+) .*dvvk profile: gpu ([\d.]+) ms \(p95 ([\d.]+), max ([\d.]+)\) = "
                     r"reconstruction ([\d.]+) \+ overlay prepare ([\d.]+) \((\d+) of (\d+) frames\) "
                     r"\+ pack ([\d.]+)")
KERNEL_BAD = re.compile(r"\*ERROR\*|WARNING:|BUG:|Call Trace|flip_done timed out|underrun|"
                        r"\[drm\].*(fail|error|timed out)|i915.*(fail|error|timed out|reset)|"
                        r"amdgpu.*(fail|error|timed out|timeout|reset)|ring \S+ timeout|"
                        r"GPU HANG|hung task", re.I)
# Known noise of this profile on every image (the skin's and add-ons' own).
BENIGN = re.compile(r"Texture manager unable to load file|service\.webostv|custom_sort_train|"
                    r"Could not parse type \"Setting\.Details|ValidateOutputDevices")


def facts(text, offset=None):
    """What the logs of one check say. `text`: logs_since()'s dictionary."""
    out = {"pool_resets": [], "errors": collections.Counter(), "warnings": collections.Counter(),
           "fel": [], "engine_failures": [], "commit_failures": [], "closed": [],
           "held_lines": 0, "flip_summaries": [], "flip_trace": [], "signals": [],
           "engine_started": [], "health": []}
    for line in text["kodi.log"].splitlines():
        m = STAMP.match(line)
        when = bench.log_epoch(m.group(1), offset) if m and offset is not None else None
        body = line.split(">: ", 1)[-1]
        if POOL in line:
            out["pool_resets"].append({"epoch": when, "line": body})
        if "Dolby Vision FEL:" in line or "DV FEL:" in line:
            out["fel"].append(body)
        if "the Vulkan engine failed" in line or "did not complete" in line or \
                "Vulkan engine reset failed" in line or "renderer rejected frame" in line:
            out["engine_failures"].append(body)
        if "flip-pending" in line or "atomic commit failed" in line or \
                "native-atomic-commit" in line or "DVBridge output failure" in line or \
                "cannot wait for the out-fence" in line or "gave no out-fence" in line:
            out["commit_failures"].append(body)
        if "frame held:" in line:
            out["held_lines"] += 1
        m = CLOSED.search(line)
        if m:
            out["closed"].append(dict(zip(("processed", "submissions", "presented", "held"),
                                          map(int, m.groups()))))
        m = FLIPS_LINE.search(line)
        if m:
            g = m.groups()
            out["flip_summaries"].append({"epoch": when, "queued": int(g[0]), "on_time": int(g[1]),
                                          "late": int(g[2]), "blocking": int(g[3]),
                                          "busy": int(g[4]), "timeouts": int(g[5]),
                                          "mean_ms": float(g[6]), "max_ms": float(g[7])})
        m = FLIP_LINE.search(line)
        if m:
            out["flip_trace"].append((when, int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                      float(m.group(4))))
        if "DVBridge signal committed" in line:
            out["signals"].append(body.split("committed: ")[-1])
        if "Vulkan engine started" in line:
            out["engine_started"].append(body)
        m = bench.HEALTH.match(line)
        if m:
            kv = dict(x.split("=", 1) for x in m.group(2).split() if "=" in x)
            out["health"].append((when, kv))
        level = re.search(r" T:\d+ +(error|warning|fatal) <", line)
        if level and not BENIGN.search(line):
            key = re.sub(r"\d+", "N", body)[:160]
            out["errors" if level.group(1) != "warning" else "warnings"][key] += 1
    out["errors"], out["warnings"] = dict(out["errors"]), dict(out["warnings"])
    out["verify"] = [(int(a), int(b)) for a, b in VERIFY.findall(text["journal.txt"])]
    out["verify_differs"] = [l.split("dvvk verify: ")[1] for l in text["journal.txt"].splitlines()
                             if "differs from the reference" in l or "no reference pack" in l]
    out["profile"] = []
    for line in text["journal.txt"].splitlines():
        m = PROFILE.match(line)
        if m:
            g = m.groups()
            out["profile"].append({"epoch": float(g[0]), "gpu_ms": float(g[1]), "p95": float(g[2]),
                                   "max": float(g[3]), "reconstruction": float(g[4]),
                                   "overlay_prepare_ms": float(g[5]), "overlay_frames": int(g[6]),
                                   "frames": int(g[7]), "pack": float(g[8])})
    out["journal_other"] = sorted({re.sub(r"\d+", "N", l.split("]: ", 1)[-1])[:160]
                                   for l in text["journal.txt"].splitlines()
                                   if "]: " in l and "dvvk profile" not in l and "dvvk verify" not in l
                                   and "dvvk damage" not in l and "libva info" not in l})
    out["kernel"] = [l for l in text["dmesg.txt"].splitlines() if KERNEL_BAD.search(l)]
    if out["health"]:
        a, b = out["health"][0][1], out["health"][-1][1]
        out["dropped"] = int(b["drop_total"]) - int(a["drop_total"])
        out["skipped"] = int(b["skip_total"]) - int(a["skip_total"])
        out["health_lines"] = len(out["health"])
    del out["health"]
    return out


def flip_trace_facts(trace):
    """DV_PRIVATE_FLIP_TRACE's lines: the order of the queued flips."""
    if not trace:
        return None
    backwards = sum(1 for a, b in zip(trace, trace[1:]) if b[2] <= a[2])
    same_fb = sum(1 for a, b in zip(trace, trace[1:]) if b[1] == a[1])
    since = collections.Counter(t[3] for t in trace)
    waits = [t[4] for t in trace]
    return {"flips": len(trace), "vblank_not_increasing": backwards,
            "same_framebuffer_twice_running": same_fb,
            "framebuffers": sorted({t[1] for t in trace}),
            "refreshes_since_last": {str(k): v for k, v in sorted(since.items())},
            "queued_to_vblank_ms_mean": round(statistics.mean(waits), 2),
            "queued_to_vblank_ms_max": max(waits)}


def clean(f):
    """The problems the logs alone show, for any check."""
    problems = []
    if f["engine_failures"]:
        problems.append(f"engine failures: {f['engine_failures'][:3]}")
    if f["commit_failures"]:
        problems.append(f"commit failures: {f['commit_failures'][:3]}")
    if f["errors"]:
        problems.append(f"errors in Kodi's log: {f['errors']}")
    if f["kernel"]:
        problems.append(f"kernel log: {f['kernel'][:3]}")
    if f["verify_differs"]:
        problems.append(f"verify: {f['verify_differs'][:3]}")
    return problems


# ---------------------------------------------------------------- playing

def play(box, cfg, film, subtitles_off=True):
    bench.require_idle(box)
    request = bench.open_request(cfg["source"], film)
    box.rpc("Player.Open", request["params"])
    bench.wait_playing(box, bench.hms(film["start"]))
    if subtitles_off:
        box.rpc("Player.SetSubtitle", {"playerid": 1, "subtitle": "off"})


def wait_title(box, start):
    """Playing near `start`: also when another title was playing before the open."""
    deadline = time.time() + 60
    while time.time() < deadline:
        if box.rpc("Player.GetActivePlayers"):
            try:
                t, speed = bench.player_time(box)
            except BenchError:
                t, speed = 0, 0
            if speed == 1 and start + 1 <= t <= start + 90:
                return
        time.sleep(0.5)
    raise BenchError("playback did not start within 60 s")


def position(reply):
    try:
        t = reply["result"]["time"]
        return t["hours"] * 3600 + t["minutes"] * 60 + t["seconds"] + t["milliseconds"] / 1000
    except (KeyError, TypeError):
        return None


def flips_in(tl, a, b):
    """Flips between two markers (names) or trace times."""
    a = tl["marks"][a] if isinstance(a, str) else a
    b = tl["marks"][b] if isinstance(b, str) else b
    return [f for f in tl["flips"] if a < f[0] <= b]


def holes(flips, a, b, least=0.25):
    """Stretches without a flip between trace times a and b: [(start - a, length)]."""
    inside = [a] + [f[0] for f in flips if a < f[0] <= b] + [b]
    return [(round(x - a, 3), round(y - x, 3)) for x, y in zip(inside, inside[1:]) if y - x > least]


def cadence(flips, expected):
    gaps = [y[1] - x[1] for x, y in zip(flips, flips[1:])]
    return {"flips": len(flips), "gaps": {str(k): v for k, v in sorted(collections.Counter(gaps).items())},
            "off_cadence": sum(1 for g in gaps if g != expected)}


TIME = ("rpc", "Player.GetProperties", {"playerid": 1, "properties": ["time", "speed"]})


def check_pause(box, cfg, key, out, raw):
    """Pause, ten frame steps, resume, a short pause; then 30 s paused."""
    film = cfg["films"][key]
    m = mark(box)
    play(box, cfg, film)
    time.sleep(SETTLE)
    steps = [(0.5, "before", None),
             (10, "pause", ("rpc", "Player.PlayPause", {"playerid": 1, "play": False})),
             (15, "t_paused", TIME)]
    for i in range(10):
        steps.append((19 + i, f"step{i:02d}", ("send", "PlayerControl(FrameAdvance(1))")))
        steps.append((19.8 + i, f"t_step{i:02d}", TIME))
    steps += [(31, "resume", ("rpc", "Player.PlayPause", {"playerid": 1, "play": True})),
              (41, "pause2", ("rpc", "Player.PlayPause", {"playerid": 1, "play": False})),
              (42.5, "resume2", ("rpc", "Player.PlayPause", {"playerid": 1, "play": True})),
              (52, "t_end", TIME)]
    tl = timeline(box, f"pause-{key}", f"{raw}/steps", 53, steps)
    box.rpc("Player.PlayPause", {"playerid": 1, "play": False})
    time.sleep(8)  # the skin's seek bar has gone
    remote = bench.sample(box, f"paused-{key}", 30)
    box.fetch(remote, f"{raw}/paused")
    paused = window_numbers(f"{raw}/paused")
    booleans = box.rpc("XBMC.GetInfoBooleans", {"booleans": ["Player.Paused",
                                                              "Window.IsVisible(seekbar)"]})
    box.rpc("Player.PlayPause", {"playerid": 1, "play": True})
    time.sleep(12)
    bench.stop(box)
    f = facts(logs_since(box, m, raw), tl["log_offset"])
    period = tl["period_ms"] / 1000
    expected = 1
    marks = tl["marks"]
    positions = [position(tl["replies"].get("t_paused"))] + \
        [position(tl["replies"].get(f"t_step{i:02d}")) for i in range(10)]
    advances = [round(b - a, 4) if a is not None and b is not None else None
                for a, b in zip(positions, positions[1:])]
    step_flips = [len(flips_in(tl, f"step{i:02d}", f"step{i + 1:02d}" if i < 9 else "resume"))
                  for i in range(10)]
    ev = {
        "refresh_hz": round(1 / period, 3),
        "playing_before_pause": cadence(flips_in(tl, "before", "pause"), expected),
        "flips_while_paused_before_steps": len(flips_in(tl, marks["pause"] + 2, "step00")),
        "flips_in_the_4s_before_the_steps": len(flips_in(tl, marks["step00"] - 4, "step00")),
        "flips_per_step": step_flips,
        "position_advance_per_step_s": advances,
        "first_flip_after_resume_ms": None, "holes_after_resume": holes(
            tl["flips"], marks["resume"], marks["resume"] + 5, 4 * period + 0.02),
        "playing_between_resume_and_pause2": cadence(
            flips_in(tl, marks["resume"] + 2, "pause2"), expected),
        "playing_after_resume2": cadence(flips_in(tl, marks["resume2"] + 2, "t_end"), expected),
        "holes_after_resume2": holes(tl["flips"], marks["resume2"], marks["resume2"] + 5,
                                     4 * period + 0.02),
        "paused_30s": paused, "paused_state": booleans,
        "position_end": position(tl["replies"].get("t_end")),
        "trace_events_lost": tl["lost"], "logs": f,
    }
    after = [x for x in tl["flips"] if x[0] > marks["resume"]]
    if after:
        ev["first_flip_after_resume_ms"] = round((after[0][0] - marks["resume"]) * 1000, 1)
    ev["flip_trace"] = flip_trace_facts(f.pop("flip_trace"))
    problems = clean(f)
    if any(n < 1 for n in step_flips):
        problems.append(f"a frame step without a flip: {step_flips}")
    good = [a for a in advances if a is not None]
    if len(good) < 10 or any(a <= 0 for a in good):
        problems.append(f"the position did not advance with every frame step: {advances}")
    # As regular as before the pause (60p on the blocking path is not on cadence at all).
    before = ev["playing_before_pause"]
    share = before["off_cadence"] / max(before["flips"], 1)
    for name in ("playing_between_resume_and_pause2", "playing_after_resume2"):
        c = ev[name]
        if c["flips"] < 100 or c["off_cadence"] > (share + 0.03) * c["flips"]:
            problems.append(f"{name}: {c} (before the pause: {before})")
    if not booleans.get("Player.Paused"):
        problems.append("not paused in the paused window")
    # The pool changes at a start (and may at a seek): never at a pause, a step or a resume.
    if len(f["pool_resets"]) > 1:
        problems.append(f"{len(f['pool_resets'])} surface pool resets without a seek")
    return ev, problems


def check_seek(box, cfg, key, out, raw):
    """Relative seeks forward and back, chapter seeks, an absolute seek."""
    film = cfg["films"][key]
    start = bench.hms(film["start"])
    m = mark(box)
    play(box, cfg, film)
    time.sleep(SETTLE)
    seeks = [
        ("fwd30", ("rpc", "Player.Seek", {"playerid": 1, "value": {"seconds": 30}})),
        ("back30", ("rpc", "Player.Seek", {"playerid": 1, "value": {"seconds": -30}})),
        ("fwd600", ("rpc", "Player.Seek", {"playerid": 1, "value": {"seconds": 600}})),
        ("back600", ("rpc", "Player.Seek", {"playerid": 1, "value": {"seconds": -600}})),
        ("chapter_next", ("rpc", "Input.ExecuteAction", {"action": "chapterorbigstepforward"})),
        ("chapter_prev", ("rpc", "Input.ExecuteAction", {"action": "chapterorbigstepback"})),
        ("absolute", ("rpc", "Player.Seek", {"playerid": 1,
                                             "value": {"time": bench.as_time(start + 300)}})),
        ("back10", ("rpc", "Player.Seek", {"playerid": 1, "value": {"seconds": -10}})),
    ]
    steps = [(2, "t_before", TIME)]
    for i, (name, action) in enumerate(seeks):
        steps.append((4 + 10 * i, name, action))
        steps.append((4 + 10 * i + 8, f"t_{name}", TIME))
    end = 4 + 10 * len(seeks)
    steps.append((end, "end", None))
    tl = timeline(box, f"seek-{key}", f"{raw}/steps", end + 1, steps)
    time.sleep(3)
    bench.stop(box)
    f = facts(logs_since(box, m, raw), tl["log_offset"])
    marks, epochs = tl["marks"], tl["epochs"]
    period = tl["period_ms"] / 1000
    rows, problems = [], clean(f)
    names = [s[0] for s in seeks]
    for i, name in enumerate(names):
        a = marks[name]
        b = marks[names[i + 1]] if i + 1 < len(names) else marks["end"]
        hs = holes(tl["flips"], a, b, 4 * period + 0.02)
        longest = max(hs, key=lambda h: h[1]) if hs else None
        resumed = round(longest[0] + longest[1], 3) if longest else 0.0
        steady = cadence([x for x in tl["flips"] if a + resumed + 1 < x[0] <= b], 1)
        resets = [p for p in f["pool_resets"]
                  if p["epoch"] is not None and epochs[name] <= p["epoch"] <
                  epochs.get(names[i + 1] if i + 1 < len(names) else "end", 1e12)]
        row = {"seek": name, "position_8s_later": position(tl["replies"].get(f"t_{name}")),
               "request_took_s": round(epochs.get(f"{name}.done", 0) - epochs[name], 3),
               "pictures_back_after_s": resumed, "holes": hs, "pool_resets": len(resets),
               "then_playing": steady}
        rows.append(row)
        if row["position_8s_later"] is None:
            problems.append(f"{name}: no position")
        if resumed > 5:
            problems.append(f"{name}: no pictures for {resumed} s")
        if steady["flips"] < 60 or steady["off_cadence"] > 3:
            problems.append(f"{name}: presentation after the seek {steady}")
    ev = {"refresh_hz": round(1 / period, 3),
          "position_before": position(tl["replies"].get("t_before")), "seeks": rows,
          "pool_resets_total": len(f["pool_resets"]), "trace_events_lost": tl["lost"]}
    ev["flip_trace"] = flip_trace_facts(f.pop("flip_trace"))
    ev["logs"] = f
    if f["fel"]:
        problems.append(f"FEL messages: {f['fel'][:3]}")
    # One reset at the start and at most one per seek; more is a pool mistaken for a new one.
    if len(f["pool_resets"]) > 1 + len(seeks):
        problems.append(f"{len(f['pool_resets'])} surface pool resets for {len(seeks)} seeks")
    return ev, problems


def check_gui(box, cfg, key, out, raw):
    """OSD opened and closed, a subtitle coming and going, with the engine's GPU timing on:
    how many frames scanned the GUI again, and what a frame cost in each phase."""
    film = cfg["films"][key]
    box.rpc("Settings.SetSettingValue", {"setting": "dvbridge.gputiming", "value": True})
    try:
        m = mark(box)
        play(box, cfg, film)
        path = f"{BOX_DIR}/subs/{key}.srt"
        box.write(path, bench.srt(bench.hms(film["start"]), key))
        box.rpc("Player.AddSubtitle", {"playerid": 1, "subtitle": path})
        time.sleep(1)
        subs = box.rpc("Player.GetProperties", {"playerid": 1, "properties": ["subtitles"]})["subtitles"]
        box.rpc("Player.SetSubtitle", {"playerid": 1, "subtitle": "off"})
        time.sleep(SETTLE)
        gui = ("rpc", "XBMC.GetInfoBooleans", {"booleans": [
            "Window.IsVisible(videoosd)", "VideoPlayer.SubtitlesEnabled",
            "Window.IsActive(fullscreenvideo)"]})
        steps = [
            (0.5, "plain", None), (10, "g_plain", gui),
            (20, "osd_open", ("rpc", "Input.ShowOSD", {})), (30, "g_osd", gui),
            (45, "osd_close", ("rpc", "Input.Back", {})), (55, "g_closed", gui),
            (65, "sub_on", ("rpc", "Player.SetSubtitle", {"playerid": 1, "subtitle": subs[-1]["index"],
                                                          "enable": True})),
            (75, "g_sub", gui),
            (90, "sub_off", ("rpc", "Player.SetSubtitle", {"playerid": 1, "subtitle": "off"})),
            (100, "osd_open2", ("rpc", "Input.ShowOSD", {})),
            (103, "osd_close2", ("rpc", "Input.Back", {})),
            (106, "osd_open3", ("rpc", "Input.ShowOSD", {})),
            (109, "osd_close3", ("rpc", "Input.Back", {})),
            (118, "g_end", gui), (120, "end", None),
        ]
        tl = timeline(box, f"gui-{key}", f"{raw}/steps", 121, steps)
        time.sleep(11)
        bench.stop(box)
    finally:
        try:
            bench.stop(box)
        finally:
            box.rpc("Settings.SetSettingValue", {"setting": "dvbridge.gputiming", "value": False})
    f = facts(logs_since(box, m, raw), tl["log_offset"])
    marks, epochs = tl["marks"], tl["epochs"]
    phases = [("plain", "plain", "osd_open"), ("OSD open", "osd_open", "osd_close"),
              ("OSD closed again", "osd_close", "sub_on"), ("subtitle on", "sub_on", "sub_off"),
              ("subtitle off", "sub_off", "osd_open2"), ("OSD toggled twice", "osd_open2", "end")]
    rows = []
    for name, a, b in phases:
        # A profile line covers the 120 frames before it: only lines wholly inside the phase.
        span = 120 / (60 if key == "gemini" else 24) + 0.5
        lines = [p for p in f["profile"] if epochs[a] + span <= p["epoch"] <= epochs[b]]
        flips = flips_in(tl, marks[a] + 1, b)
        row = {"phase": name, "seconds": round(marks[b] - marks[a], 1),
               "cadence": cadence(flips, 1), "profile_lines": len(lines)}
        if lines:
            frames = sum(p["frames"] for p in lines)
            row.update({
                "frames_profiled": frames,
                "frames_that_scanned_the_gui": sum(p["overlay_frames"] for p in lines),
                "engine_gpu_ms_mean": round(statistics.mean(p["gpu_ms"] for p in lines), 2),
                "engine_gpu_ms_max": max(p["max"] for p in lines),
                "overlay_prepare_ms_mean": round(statistics.mean(p["overlay_prepare_ms"]
                                                                 for p in lines), 3),
                "pack_ms_mean": round(statistics.mean(p["pack"] for p in lines), 2)})
        rows.append(row)
    states = {k: (tl["replies"].get(k) or {}).get("result") for k in
              ("g_plain", "g_osd", "g_closed", "g_sub", "g_end")}
    ev = {"refresh_hz": round(1000 / tl["period_ms"], 3), "phases": rows, "gui_states": states,
          "trace_events_lost": tl["lost"]}
    ev["flip_trace"] = flip_trace_facts(f.pop("flip_trace"))
    del f["profile"]
    ev["logs"] = f
    problems = clean(f)
    want = {"g_plain": (False, False), "g_osd": (True, False), "g_closed": (False, False),
            "g_sub": (False, True), "g_end": (False, False)}
    for k, (osd, sub) in want.items():
        s = states.get(k) or {}
        if s.get("Window.IsVisible(videoosd)") != osd or s.get("VideoPlayer.SubtitlesEnabled") != sub:
            problems.append(f"GUI state at {k}: {s}")
    by = {r["phase"]: r for r in rows}
    plain, osd = by["plain"], by["OSD open"]
    if plain.get("frames_that_scanned_the_gui", 0) > 0.05 * plain.get("frames_profiled", 1):
        problems.append("the GUI was scanned during plain playback")
    if osd.get("frames_profiled") and \
            osd["frames_that_scanned_the_gui"] >= 0.9 * osd["frames_profiled"]:
        problems.append("with the OSD open nearly every frame scanned the GUI again: nothing skipped")
    return ev, problems


def check_verify(box, cfg, key, out, raw, what="plain", seconds=None):
    """DVVK_VERIFY (Kodi's Verify output setting: every 60th frame rendered again by the
    engine's reference route and compared on the GPU) through a scenario."""
    film = cfg["films"][key]
    fast = key == "gemini"
    # The engine prints its count every 120 checked frames: 7200 frames.
    seconds = seconds or (132 if fast else 312)
    box.rpc("Settings.SetSettingValue", {"setting": "dvbridge.verify", "value": True})
    if what == "hdr10":
        box.rpc("Settings.SetSettingValue", {"setting": "dvbridge.outputmode", "value": 1})
    done = []
    try:
        m = mark(box)
        play(box, cfg, film)
        start = time.time()
        if what == "subtitle":
            bench.apply_scenario(box, "C", key, film)
        n = 0
        while time.time() - start < seconds:
            n += 1
            if what == "osd":
                # Open 10 s, closed 5 s: frames with the OSD, without it and at both changes.
                box.rpc("Input.ShowOSD")
                time.sleep(10)
                box.rpc("Input.Back")
                time.sleep(5)
                done.append("osd open/close")
            elif what == "transport":
                # Pause, frame steps, resume, seeks: the engine is reset and restarted.
                time.sleep(12)
                box.rpc("Player.PlayPause", {"playerid": 1, "play": False})
                time.sleep(3)
                for _ in range(5):
                    box.ssh("kodi-send --action='PlayerControl(FrameAdvance(1))' >/dev/null 2>&1",
                            check=False)
                    time.sleep(0.5)
                box.rpc("Player.PlayPause", {"playerid": 1, "play": True})
                time.sleep(10)
                box.rpc("Player.Seek", {"playerid": 1, "value": {"seconds": 30 if n % 2 else -30}})
                time.sleep(10)
                done.append("pause, 5 steps, resume, seek")
            else:
                time.sleep(5)
        state = box.rpc("XBMC.GetInfoBooleans", {"booleans": [
            "Window.IsVisible(videoosd)", "VideoPlayer.SubtitlesEnabled", "Player.Paused"]})
        bench.stop(box)
    finally:
        try:
            bench.stop(box)
        finally:
            box.rpc("Settings.SetSettingValue", {"setting": "dvbridge.verify", "value": False})
            if what == "hdr10":
                box.rpc("Settings.SetSettingValue", {"setting": "dvbridge.outputmode", "value": 0})
    f = facts(logs_since(box, m, raw))
    f.pop("flip_trace")
    closed = f["closed"][-1] if f["closed"] else {}
    checked, differed = f["verify"][-1] if f["verify"] else (0, 0)
    ev = {"scenario": what, "played_s": seconds, "actions": len(done),
          "frames_processed": closed.get("processed"),
          "engine_reported": {"checked": checked, "differed": differed},
          "differing_frames_logged": len(f["verify_differs"]),
          # Every 60th frame of each engine: the count restarts when the engine does.
          "checked_estimate": (closed.get("processed") or 0) // 60,
          "state_at_end": state, "signal": f["signals"][-1] if f["signals"] else None, "logs": f}
    problems = clean(f)
    if not checked and ev["checked_estimate"] < 60:
        problems.append("too few frames checked")
    if differed:
        problems.append(f"{differed} of {checked} checked frames differed")
    return ev, problems


def check_cadence(box, cfg, key, out, raw):
    """A 24p film on the menu's 60 Hz mode (refresh rate switching off): each picture
    rendered once, the repeats held."""
    setting = "videoplayer.adjustrefreshrate"
    old = box.rpc("Settings.GetSettingValue", {"setting": setting})["value"]
    box.rpc("Settings.SetSettingValue", {"setting": setting, "value": 0})
    try:
        m = mark(box)
        bench.run_window(box, cfg, "A", key, 1, raw)
    finally:
        box.rpc("Settings.SetSettingValue", {"setting": setting, "value": old})
    d = bench.analyse(raw, {"image": cfg["image"]}, cfg)
    f = facts(logs_since(box, m, f"{raw}/logs"))
    f.pop("flip_trace")
    closed = f["closed"][-1] if f["closed"] else {}
    p, g = d["presentation"], d["gpu"]
    ev = {"refresh_hz": p["refresh_hz"], "source_fps": d["source_fps"],
          "presented_fps": p["presented_fps"], "gap_histogram": p["gap_histogram"],
          "gap_sequence_head": p["gap_sequence_head"],
          "render_ms_per_presented_frame": g["render_ms_per_presented_frame"],
          "render_ms_per_source_frame": g["render_ms_per_source_frame"],
          "render_busy_pct": g["render_busy_pct"], "kodi_dropped": d["kodi"].get("dropped"),
          "kodi_skipped": d["kodi"].get("skipped"), "render_thread_pct": d["cpu"]["render_thread_pct"],
          "process_pct": d["cpu"]["process_pct"], "gpu_mhz": d["gpu_clock"].get("awake_mhz_mean"),
          "package_w": d["power"].get("package_0_w"), "measured_pass": closed,
          "signal": d["kodi"].get("signal"), "checks": d["checks"], "logs": f}
    problems = clean(f)
    if not (55 < (p["refresh_hz"] or 0) < 61):
        problems.append(f"the display was at {p['refresh_hz']} Hz, not the menu's 60")
    if abs(p["presented_fps"] - d["source_fps"]) > 0.5:
        problems.append(f"{p['presented_fps']} pictures per second for a {d['source_fps']} fps film")
    # Each picture rendered once: as many frames processed as the film has in the pass
    # (settle, window, the seconds after it), and the refreshes between them held.
    if closed and not closed["held"]:
        problems.append(f"no repeat was held: {closed}")
    played = bench.SETTLE + cfg["window_s"] + bench.POST
    ev["frames_processed_per_s_of_pass"] = round(closed.get("processed", 0) / played, 2)
    if closed and closed["processed"] > (played + 4) * d["source_fps"]:
        problems.append(f"more frames rendered than the film has: {closed}")
    return ev, problems


def check_sequence(box, cfg, key, out, raw):
    """Titles stopped and started in a row: SDR, Dolby Vision straight after it, plain HDR10,
    60p, Profile 8, then one title opened over another without a stop."""
    films = cfg["films"]
    order = [("sdr", SDR, True), ("1917", films["1917"], True), ("hdr10", HDR10, True),
             ("gemini", films["gemini"], True), ("sdr-2", SDR, True), ("28yl", films["28yl"], True),
             ("spr", films["spr"], False), ("1917-over-spr", films["1917"], True)]
    rows, problems = [], []
    stop_before = True
    m_all = mark(box)
    for name, film, stop_after in order:
        m = mark(box)
        request = bench.open_request(cfg["source"], film)
        t = time.time()
        box.rpc("Player.Open", request["params"])
        wait_title(box, bench.hms(film["start"]))
        started = round(time.time() - t, 1)
        box.rpc("Player.SetSubtitle", {"playerid": 1, "subtitle": "off"})
        time.sleep(8)
        remote = bench.sample(box, f"sequence-{name}", 12)
        box.fetch(remote, f"{raw}/{name}")
        w = window_numbers(f"{raw}/{name}")
        labels = box.rpc("XBMC.GetInfoLabels", {"labels": bench.LABELS})
        booleans = box.rpc("XBMC.GetInfoBooleans", {"booleans": ["Player.Passthrough"]})
        if stop_after:
            bench.stop(box)
        f = facts(logs_since(box, m, f"{raw}/{name}"))
        f.pop("flip_trace")
        fps = float(labels.get("Player.Process(videofps)") or 0)
        row = {"title": film["title"], "expect": film["expect"], "stopped_before_next": stop_after,
               "open_to_playing_s": started, "hdr_type": labels.get("VideoPlayer.HdrType"),
               "decoder": labels.get("Player.Process(videodecoder)"),
               "pixel_format": labels.get("Player.Process(pixformat)"), "fps": fps,
               "audio": labels.get("Player.Process(audiodecoder)"),
               "passthrough": booleans.get("Player.Passthrough"),
               "display": bench.read(f"{raw}/{name}/display.txt", "").splitlines()[5:7],
               "window_12s": w, "engine_started": bool(f["engine_started"]),
               "signals": f["signals"],
               "pool_resets": len(f["pool_resets"]), "closed": f["closed"],
               "dropped": f.get("dropped"), "skipped": f.get("skipped"),
               "errors": f["errors"], "warnings": f["warnings"], "kernel": f["kernel"],
               "engine_failures": f["engine_failures"], "commit_failures": f["commit_failures"]}
        rows.append(row)
        for p in clean(f):
            problems.append(f"{name}: {p}")
        # 60p on the blocking path presents two pictures in three refreshes (as 0.4 did).
        if fps and w["flips_per_s"] < (fps - 0.5 if fps < 30 else 0.6 * fps):
            problems.append(f"{name}: {w['flips_per_s']} flips/s for {fps} fps")
        # A title opened over another keeps the engine: its surface pool is reset instead.
        engine = bool(f["engine_started"]) or (not stop_before and bool(f["pool_resets"]))
        if film.get("engine", True) != engine:
            problems.append(f"{name}: engine started = {bool(f['engine_started'])}")
        stop_before = stop_after
    bench.stop(box)
    f = facts(logs_since(box, m_all, raw))
    f.pop("flip_trace")
    return {"titles": rows, "logs_whole_sequence": f}, problems


CHECKS = {
    "pause": (check_pause, ["1917", "gemini", "spr", "28yl"]),
    "seek": (check_seek, ["1917", "spr"]),
    "gui": (check_gui, ["1917", "gemini"]),
    "cadence": (check_cadence, ["1917"]),
    "sequence": (check_sequence, ["all"]),
    "verify": (check_verify, ["1917", "spr", "28yl", "gemini"]),
    "verify-osd": (lambda *a: check_verify(*a, what="osd"), ["1917", "gemini"]),
    "verify-subtitle": (lambda *a: check_verify(*a, what="subtitle"), ["1917", "gemini"]),
    "verify-transport": (lambda *a: check_verify(*a, what="transport"), ["1917"]),
    "verify-hdr10": (lambda *a: check_verify(*a, what="hdr10"), ["1917"]),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--image", required=True, help="the bench profile's name (bench-name)")
    ap.add_argument("--label", help="results folder, for a variant of the profile")
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--matrix", default=os.path.join(bench.HERE, "matrix.json"))
    ap.add_argument("--only", help=f"comma-separated, of: {', '.join(CHECKS)}")
    ap.add_argument("--films", help="comma-separated, default: each check's own")
    ap.add_argument("--force", action="store_true", help="do again what has a result")
    args = ap.parse_args()
    with open(args.matrix) as f:
        cfg = json.load(f)
    cfg["window_s"] = bench.WINDOW
    cfg["image"] = args.label or args.image
    out = os.path.join(args.out, args.label or args.image, "checks")
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    box = bench.Box(args.host, args.image, args.port)
    name = box.ssh(bench.BENCH_NAME_SH, check=False).strip()
    if name != args.image:
        raise BenchError(f"the box runs bench image {name!r}, not {args.image!r}")
    with open(os.path.join(bench.HERE, "box", "sample.sh")) as f:
        box.write(f"{BOX_DIR}/sample.sh", f.read())
    box.open_tunnel()
    failed = 0
    try:
        bench.require_idle(box)
        env = box.ssh(f"cat {bench.ENV_FILE}", check=False).split()
        for check in (args.only.split(",") if args.only else list(CHECKS)):
            function, films = CHECKS[check]
            for key in films:
                if args.films and key not in args.films.split(","):
                    continue
                run = f"{check}-{key}"
                result = os.path.join(out, run + ".json")
                if os.path.exists(result) and not args.force:
                    continue
                raw = os.path.join(out, "raw", run)
                os.system(f"rm -rf '{raw}'")
                os.makedirs(raw)
                log(f"{run}: {(function.__doc__ or check).strip().splitlines()[0]}")
                try:
                    evidence, problems = function(box, cfg, key, out, raw)
                except (BenchError, OSError, KeyError, ValueError, IndexError,
                        bench.subprocess.SubprocessError) as e:
                    evidence, problems = {}, [f"the check did not finish: {e!r}"]
                    try:
                        bench.stop(box)
                    except BenchError:
                        pass
                data = {"check": check, "film": key, "image": args.label or args.image,
                        "env_override": env, "passed": not problems, "problems": problems,
                        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "evidence": evidence}
                with open(result, "w") as f:
                    json.dump(data, f, indent=1)
                failed += bool(problems)
                log(f"{run}: {'PASS' if not problems else 'FAIL: ' + '; '.join(problems)[:600]}")
    finally:
        try:
            bench.stop(box)
        except BenchError:
            pass
        box.close()
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BenchError as e:
        print(f"checks: {e}", file=sys.stderr)
        sys.exit(1)
