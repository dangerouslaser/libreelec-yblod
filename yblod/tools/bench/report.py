#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Turn bench.py result folders into a Markdown comparison and a summary JSON.

  report.py RESULTS/IMAGE [RESULTS/IMAGE ...] [--md FILE] [--json FILE]

Rows are film x scenario, columns are images (in the order given). A cell is
the median over the repetitions, with the lowest and highest repetition in
brackets when they differ. Python 3.9+, standard library only.
"""

import argparse
import glob
import json
import os
import statistics
import sys

SCENARIO_NAMES = {
    "A": "plain", "B": "OSD open", "C": "subtitle", "D": "paused",
    "E": "DV to HDR10", "F": "start", "P": "plain + engine log",
}
FILM_ORDER = ["1917", "spr", "28yl", "gemini"]


def load(directory):
    with open(os.path.join(directory, "session.json")) as f:
        session = json.load(f)
    runs = {}
    for path in sorted(glob.glob(os.path.join(directory, "*-r*.json"))):
        with open(path) as f:
            d = json.load(f)
        runs.setdefault((d["film"], d["scenario"]), []).append(d)
    return session, runs


def compact(d):
    """The numbers of one run that the tables and the summary use."""
    if d["scenario"] == "F":
        return {"rep": d["rep"], "valid": d["valid"], "start_s": d["start_s_median"],
                "starts_s": [s.get("start_s") for s in d["starts"]],
                "kodi_first_frame_s": [s.get("kodi_first_frame_s") for s in d["starts"]]}
    g, p, k, c = d["gpu"], d["presentation"], d["kodi"], d["cpu"]
    out = {
        "rep": d["rep"], "valid": d["valid"],
        "failed_checks": [n for n, ok in d["checks"].items() if not ok],
        "window_s": d["window_s"], "source_fps": d["source_fps"],
        "ms_per_frame": g["render_ms_per_presented_frame"],
        "ms_per_source_frame": g["render_ms_per_source_frame"],
        "engine_client_ms_per_frame": g["engine_client_ms_per_presented_frame"],
        "video_decode_ms_per_frame": g["video_ms_per_presented_frame"],
        "render_busy_pct": g["render_busy_pct"],
        "presented_fps": p["presented_fps"], "refresh_hz": p["refresh_hz"],
        "gap_histogram": p["gap_histogram"], "gaps_off_cadence": p.get("gaps_off_cadence"),
        "longest_gap_refreshes": p["longest_gap_refreshes"],
        "kodi_dropped": k.get("dropped"), "kodi_skipped": k.get("skipped"),
        "render_thread_pct": c["render_thread_pct"], "process_cpu_pct": c["process_pct"],
        "gpu_awake_mhz_mean": d["gpu_clock"].get("awake_mhz_mean"),
        "gpu_share_asleep": d["gpu_clock"].get("share_asleep"),
        "package_w": d["power"].get("package_0_w"),
        "signal": k.get("signal"), "stream": k.get("stream"), "engine": k.get("engine"),
        "enhancement_layer": k.get("enhancement_layer"), "audio_stream": k.get("audio_stream"),
        "output": k.get("output"),
    }
    if d.get("engine_profile"):
        out["engine_profile"] = d["engine_profile"]
    return out


def spread(values):
    """Median, lowest, highest, and half the range as a share of the median."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    med = statistics.median(values)
    return {"median": round(med, 3), "min": min(values), "max": max(values), "n": len(values),
            "half_range_pct": round(50 * (max(values) - min(values)) / med, 2) if med else 0.0}


def summarise(session, runs):
    rows = {}
    for (film, scenario), reps in sorted(runs.items()):
        c = [compact(d) for d in sorted(reps, key=lambda d: d["rep"])]
        row = {"film": film, "scenario": scenario, "title": reps[0]["title"],
               "start": reps[0]["start"], "reps": c}
        keys = ["start_s"] if scenario == "F" else [
            "ms_per_frame", "ms_per_source_frame", "presented_fps", "render_busy_pct",
            "render_thread_pct", "process_cpu_pct", "gpu_awake_mhz_mean", "package_w",
            "kodi_dropped", "kodi_skipped", "gaps_off_cadence"]
        for k in keys:
            row[k] = spread([r.get(k) for r in c])
        rows[f"{film}-{scenario}"] = row
    keep = ["image", "os_version", "os_build_id", "kernel", "kernel_build", "cpu", "gpu_pci",
            "gl_version", "kodi_version", "engine_sha256", "kodi_sha256", "kernel_md5",
            "system_md5", "env_override", "sinks", "display_note", "recorded", "harness",
            "gt_RP0_freq_mhz", "gt_min_freq_mhz", "gt_max_freq_mhz", "rapl_long_term_uw",
            "rapl_short_term_uw", "dv_prepare_marker", "outputmode_options", "settings",
            "profile", "env_image"]
    return {"session": {k: session.get(k) for k in keep}, "rows": rows}


def num(s, digits=2):
    """'17.85' or '17.85 (17.80-17.90)'."""
    if s is None:
        return "-"
    text = f"{s['median']:.{digits}f}"
    if s["n"] > 1 and s["min"] != s["max"]:
        text += f" ({s['min']:.{digits}f}-{s['max']:.{digits}f})"
    return text


def total(s):
    """Counters: the repetitions' values, e.g. '0, 0'."""
    return "-" if s is None else f"{s['max']:.0f}" if s["min"] == s["max"] else \
        f"{s['min']:.0f}-{s['max']:.0f}"


def row_keys(summaries, scenarios):
    keys = []
    for scenario in scenarios:
        for film in FILM_ORDER + sorted({r["film"] for s in summaries
                                         for r in s["rows"].values()} - set(FILM_ORDER)):
            key = f"{film}-{scenario}"
            if any(key in s["rows"] for s in summaries):
                keys.append(key)
    return keys


def flag(row):
    return "" if all(r["valid"] for r in row["reps"]) else " (!)"


def table(header, lines):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    out += ["| " + " | ".join(line) + " |" for line in lines]
    return "\n".join(out) + "\n"


def markdown(summaries):
    names = [s["session"]["image"] for s in summaries]
    md = ["# Kodi playback benchmark\n"]
    md.append("Made by `yblod/tools/bench/report.py`; the method and every definition are in "
              "`yblod/tools/bench/README.md`. A cell is the median of the repetitions, the "
              "lowest and highest repetition in brackets. `(!)`: a repetition failed one of "
              "its checks (listed at the end).\n")
    lines = []
    # A variant (bench.py --label) is a profile measured with another native-dv.env.
    variants = any(s["session"].get("profile") not in (None, s["session"]["image"])
                   for s in summaries)
    for s in summaries:
        x = s["session"]
        line = [f"`{x['image']}`", str(x["os_version"]), str(x["kernel"]),
                str(x["cpu"]), str(x["gl_version"]), str(x["recorded"]),
                str(x["display_note"])]
        if variants:
            line.insert(1, f"`{str(x.get('env_override')).strip()}`")
        lines.append(line)
    header = ["image", "version", "kernel", "CPU", "GL", "recorded (UTC)", "display"]
    if variants:
        header.insert(1, "profile's native-dv.env")
    md.append(table(header, lines))

    md.append("## Films\n")
    md.append("What Kodi and the engine said each stream is (first image; the layer from the "
              "engine's log in scenario P: FEL has a reconstruction stage, a MEL's enhancement "
              "layer is not decoded, Profile 8 has none).\n")
    lines = []
    first = summaries[0]
    for key in row_keys([first], "A"):
        r = first["rows"][key]
        a = r["reps"][0]
        p = first["rows"].get(key[:-1] + "P")
        prof = p["reps"][0].get("engine_profile") if p else None
        layer = "not measured"
        if a.get("enhancement_layer"):
            layer = "MEL (not decoded)"
        elif prof:
            layer = "FEL" if prof.get("fel_stages_last_line") else "none"
        lines.append([r["film"], r["title"], r["start"], str(a["stream"]), layer,
                      str(a["source_fps"]), str(a["audio_stream"]),
                      str(a["signal"]).split(" mode=")[-1].split(" flags")[0]])
    md.append(table(["film", "title", "passage from", "stream", "enhancement layer",
                     "fps", "audio", "output mode"], lines))

    md.append("## Frame time and presentation\n")
    md.append("GPU render time per presented picture (ms; the headline) and per source "
              "frame (the same unless pictures are missing), pictures presented per second, "
              "Kodi's dropped/skipped frames around the window, and the flips that were not "
              "one source frame after the one before (\"late\").\n")
    header = ["film", "scenario"]
    for n in names:
        header += [f"{n} ms/frame", f"{n} ms/source frame", f"{n} fps", f"{n} drop/skip",
                   f"{n} late"]
    lines = []
    for key in row_keys(summaries, "ABCE"):
        film, scenario = key.rsplit("-", 1)
        line = [film, SCENARIO_NAMES[scenario]]
        for s in summaries:
            r = s["rows"].get(key)
            if not r:
                line += ["-"] * 5
                continue
            line += [num(r["ms_per_frame"]) + flag(r), num(r["ms_per_source_frame"]),
                     num(r["presented_fps"]),
                     f"{total(r['kodi_dropped'])} / {total(r['kodi_skipped'])}",
                     total(r["gaps_off_cadence"])]
        lines.append(line)
    md.append(table(header, lines))

    if len(summaries) > 1:
        base = summaries[0]
        md.append(f"## Change against {names[0]}\n")
        md.append("The same numbers as a difference from the first image: GPU time per source "
                  "frame (the work a second of film costs, whatever was presented), GPU time per "
                  "presented picture, and pictures presented per second. A frame-time difference "
                  "under 3 % is noise (see the spread table).\n")
        header = ["film", "scenario"]
        for n in names[1:]:
            header += [f"{n} ms/source frame", f"{n} ms/frame", f"{n} fps"]
        lines = []
        for key in row_keys(summaries, "ABCE"):
            film, scenario = key.rsplit("-", 1)
            b = base["rows"].get(key)
            line = [film, SCENARIO_NAMES[scenario]]
            for s in summaries[1:]:
                r = s["rows"].get(key)
                if not r or not b:
                    line += ["-"] * 3
                    continue
                for k in ("ms_per_source_frame", "ms_per_frame"):
                    line.append(f"{100 * (r[k]['median'] / b[k]['median'] - 1):+.1f} %")
                line.append(f"{b['presented_fps']['median']:.2f} to "
                            f"{r['presented_fps']['median']:.2f}")
            lines.append(line)
        md.append(table(header, lines))

    md.append("## Flip gaps\n")
    md.append("Gaps between flips in refresh periods, summed over the repetitions "
              "(`1: n` only is perfect), and the display's refresh rate.\n")
    header = ["film", "scenario"] + [f"{n} gaps (Hz)" for n in names]
    lines = []
    for key in row_keys(summaries, "ABCE"):
        film, scenario = key.rsplit("-", 1)
        line = [film, SCENARIO_NAMES[scenario]]
        for s in summaries:
            r = s["rows"].get(key)
            if not r:
                line.append("-")
                continue
            hist = {}
            for rep in r["reps"]:
                for g, n in rep["gap_histogram"].items():
                    hist[int(g)] = hist.get(int(g), 0) + n
            line.append(", ".join(f"{g}: {n}" for g, n in sorted(hist.items())) +
                        f" ({r['reps'][0]['refresh_hz']})")
        lines.append(line)
    md.append(table(header, lines))

    md.append("## CPU, GPU clock and power\n")
    md.append("Kodi's render (main) thread and whole process in % of one core, the GPU's "
              "actual clock while awake (MHz, not pinned), package power (W, RAPL).\n")
    header = ["film", "scenario"]
    for n in names:
        header += [f"{n} render thread %", f"{n} process %", f"{n} GPU MHz", f"{n} W"]
    lines = []
    for key in row_keys(summaries, "ABCDE"):
        film, scenario = key.rsplit("-", 1)
        line = [film, SCENARIO_NAMES[scenario]]
        for s in summaries:
            r = s["rows"].get(key)
            if not r:
                line += ["-"] * 4
                continue
            line += [num(r["render_thread_pct"], 1), num(r["process_cpu_pct"], 1),
                     num(r["gpu_awake_mhz_mean"], 0), num(r["package_w"], 1)]
        lines.append(line)
    md.append(table(header, lines))

    md.append("## Paused\n")
    md.append("60 s paused on a film frame: GPU render busy (% of wall time) and pictures "
              "flipped per second.\n")
    header = ["film"]
    for n in names:
        header += [f"{n} GPU busy %", f"{n} flips/s", f"{n} render thread %"]
    lines = []
    for key in row_keys(summaries, "D"):
        line = [key.rsplit("-", 1)[0]]
        for s in summaries:
            r = s["rows"].get(key)
            line += ["-"] * 3 if not r else [
                num(r["render_busy_pct"], 1) + flag(r), num(r["presented_fps"]),
                num(r["render_thread_pct"], 1)]
        lines.append(line)
    md.append(table(header, lines))

    md.append("## Playback start\n")
    md.append("Seconds from `Player.Open` to the first flip of uninterrupted presentation "
              "(median of the repetitions' medians; lowest and highest single start).\n")
    header = ["film"] + [f"{n} start s" for n in names]
    lines = []
    for key in row_keys(summaries, "F"):
        line = [key.rsplit("-", 1)[0]]
        for s in summaries:
            r = s["rows"].get(key)
            if not r:
                line.append("-")
                continue
            starts = [x for rep in r["reps"] for x in rep["starts_s"] if x is not None]
            line.append(f"{r['start_s']['median']:.2f} ({min(starts):.2f}-{max(starts):.2f}, "
                        f"n={len(starts)})" + flag(r))
        lines.append(line)
    md.append(table(header, lines))

    md.append("## The two frame-time sources\n")
    md.append("Plain playback: DRM fdinfo (ms per presented picture, all of Kodi's render "
              "work) against the engine's own GPU timestamps (`DVVK_PROFILE`, mean of the "
              "120-frame means; worst p95 and maximum), taken in a separate pass.\n")
    header = ["image", "film", "fdinfo, log off", "fdinfo, log on", "engine mean",
              "engine p95 / max", "engine vs fdinfo (same pass)"]
    lines = []
    for s in summaries:
        for key in row_keys([s], "P"):
            r = s["rows"][key]
            film = key.rsplit("-", 1)[0]
            a = s["rows"].get(f"{film}-A")
            prof = [rep["engine_profile"] for rep in r["reps"] if rep.get("engine_profile")]
            if not prof:
                continue
            mean = statistics.mean(p["gpu_ms_mean"] for p in prof)
            lines.append([s["session"]["image"], film, num(a["ms_per_frame"]) if a else "-",
                          num(r["ms_per_frame"]), f"{mean:.2f}",
                          f"{max(p['gpu_ms_p95_worst'] for p in prof):.2f} / "
                          f"{max(p['gpu_ms_max'] for p in prof):.2f}",
                          f"{100 * (mean / r['ms_per_frame']['median'] - 1):+.1f} %"])
    md.append(table(header, lines))

    md.append("## Run-to-run spread\n")
    md.append("Half the range between the repetitions as a share of the median, for the "
              "frame time. A difference between two images smaller than this is noise. The "
              "last rows pool plain playback with the engine-log passes (scenario P), which "
              "measure the same thing when the log costs nothing.\n")
    header = ["film", "scenario"] + [f"{n} repetitions (ms/frame)" for n in names] + \
        [f"{n} +/- %" for n in names]
    lines = []
    for key in row_keys(summaries, "ABCE"):
        film, scenario = key.rsplit("-", 1)
        values, pct = [], []
        for s in summaries:
            r = s["rows"].get(key)
            values.append(", ".join(f"{rep['ms_per_frame']:.2f}" for rep in r["reps"])
                          if r else "-")
            pct.append(f"{r['ms_per_frame']['half_range_pct']:.1f}" if r else "-")
        lines.append([film, SCENARIO_NAMES[scenario]] + values + pct)
    # Plain playback was measured in scenario P as well: more windows of the same thing.
    for key in row_keys(summaries, "A"):
        film = key.rsplit("-", 1)[0]
        values, pct = [], []
        for s in summaries:
            reps = [rep["ms_per_frame"] for k in (key, f"{film}-P") if k in s["rows"]
                    for rep in s["rows"][k]["reps"] if rep["ms_per_frame"]]
            sp = spread(reps)
            values.append(", ".join(f"{v:.2f}" for v in reps) if reps else "-")
            pct.append(f"{sp['half_range_pct']:.1f}" if sp else "-")
        lines.append([film, "plain, with the engine-log passes"] + values + pct)
    md.append(table(header, lines))

    bad = [(s["session"]["image"], key, rep["rep"], rep.get("failed_checks", ["start"]))
           for s in summaries for key, r in s["rows"].items() for rep in r["reps"]
           if not rep["valid"]]
    if bad:
        md.append("## Failed checks\n")
        md.append("\n".join(f"- `{i}` {k} repetition {n}: {', '.join(c)}"
                            for i, k, n, c in bad) + "\n")
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", help="RESULTS/IMAGE folders, in column order")
    ap.add_argument("--md", help="write the Markdown here (default: stdout)")
    ap.add_argument("--json", help="write the summary JSON here")
    args = ap.parse_args()
    summaries = [summarise(*load(d)) for d in args.dirs]
    text = markdown(summaries)
    if args.md:
        with open(args.md, "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    if args.json:
        with open(args.json, "w") as f:
            json.dump({s["session"]["image"]: s for s in summaries}, f, indent=1)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
