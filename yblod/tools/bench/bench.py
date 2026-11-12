#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Kodi Dolby Vision playback benchmark for a YBLOD bench image (see README.md).

Runs on the workstation; talks to the box over ssh (one connection, with
Kodi's JSON-RPC forwarded) and leaves all timing-critical sampling to
box/sample.sh. Python 3.9+, standard library only.

  bench.py prepare --host root@BOX --image NAME
  bench.py env     --host root@BOX --image NAME [KEY=VALUE ...]
  bench.py run     --host root@BOX --image NAME --out RESULTS [--scenarios A,B]
                   [--films 1917,spr] [--reps 2] [--force] [--label VARIANT]
  bench.py analyse RESULTS/NAME          (recompute the JSON from the raw files)
"""

import argparse
import base64
import collections
import datetime
import gzip
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BOX_DIR = "/storage/yblod-bench"
RPC_AUTH = "kodi:bench"
# The bench profile's name: /flash/bench-name on the N150 (le-switch.sh writes
# it); on a box that boots profiles from btrfs subvolumes (ryzen-fella), the
# subvolume of the SYSTEM image on the kernel's command line, @bench-NAME.
BENCH_NAME_SH = ("cat /flash/bench-name 2>/dev/null || "
                 "sed -n 's|.* SYSTEM_IMAGE=/@bench-\\([^/ ]*\\)/SYSTEM.*|\\1|p' /proc/cmdline")

SETTLE = 15         # s of playback before the window opens
WINDOW = 60         # s measured
POST = 11           # s of playback after the window (Kodi's next health line)
START_OBSERVE = 12  # s traced after Player.Open in the start scenario
STARTS = 3          # measured starts per film and repetition
STEADY_GAP = 0.25   # s: a longer hole between flips is "not yet playing"
PAUSE_AT = 20       # s into the passage: the frame the paused scenario holds
CLK_TCK = 100

SCENARIOS = {
    "A": "plain playback: no OSD, subtitles off",
    "B": "video OSD held open for the whole window",
    "C": "a text subtitle (generated SRT) on",
    "D": "paused on a film frame",
    "E": "Dolby Vision -> HDR10 output mode",
    "F": "playback start: Player.Open to uninterrupted presentation",
    "P": "as A with the engine's GPU timing log on (cross-check of A)",
}

BOOLEANS = [
    "Window.IsActive(fullscreenvideo)", "Window.IsVisible(videoosd)",
    "Window.IsVisible(seekbar)", "Window.IsVisible(notification)",
    "Window.IsVisible(busydialog)", "System.HasActiveModalDialog", "Player.ShowInfo",
    "Player.Paused", "Player.Passthrough", "VideoPlayer.SubtitlesEnabled",
]
LABELS = [
    "VideoPlayer.HdrType", "VideoPlayer.VideoCodec", "VideoPlayer.VideoResolution",
    "Player.Process(videofps)", "Player.Process(videodecoder)",
    "Player.Process(pixformat)", "Player.Process(audiodecoder)",
    "Player.Process(audiochannels)", "System.ScreenResolution",
]
SETTINGS = [
    "videoplayer.adjustrefreshrate", "videoplayer.usedisplayasclock",
    "videoplayer.usevaapi", "videoplayer.prefervaapirender",
    "videoscreen.resolution", "videoscreen.screenmode", "videoscreen.limitguisize",
    "videoscreen.whitelist", "videoscreen.noofbuffers", "videoscreen.10bitsurfaces",
    "audiooutput.audiodevice", "audiooutput.passthroughdevice",
    "audiooutput.passthrough", "audiooutput.channels", "audiooutput.truehdpassthrough",
    "audiooutput.eac3passthrough", "audiooutput.dtshdpassthrough",
    "locale.subtitlelanguage", "lookandfeel.skin", "services.webserver",
    "dvbridge.outputmode", "dvbridge.hdr10plussources", "dvbridge.elupscaler",
    "dvbridge.dvmetadata", "dvbridge.tvpeak", "dvbridge.removel2",
    "dvbridge.enhancedinfo", "dvbridge.menumode", "dvbridge.guicache",
    "dvbridge.homecache", "dvbridge.halfgui", "dvbridge.verify",
    "dvbridge.frametrace", "dvbridge.gputiming",
]

SESSION_SCRIPT = r"""
. /etc/os-release
echo "os_version=${VERSION}"
echo "os_build_id=${BUILD_ID:-}"
echo "bench_name=$(cat /flash/bench-name 2>/dev/null ||
  sed -n 's|.* SYSTEM_IMAGE=/@bench-\([^/ ]*\)/SYSTEM.*|\1|p' /proc/cmdline)"
echo "kernel=$(uname -r)"
echo "kernel_build=$(uname -v)"
echo "cmdline=$(cat /proc/cmdline)"
echo "cpu=$(sed -n 's/^model name[^:]*: //p' /proc/cpuinfo | head -n 1)"
echo "cores=$(grep -c ^processor /proc/cpuinfo)"
echo "mem_total_kb=$(sed -n 's/^MemTotal: *\([0-9]*\).*/\1/p' /proc/meminfo)"
for d in /sys/class/drm/card?; do
  [ -r "${d}/gt_RP0_freq_mhz" ] || continue
  echo "gpu_pci=$(cat "${d}/device/vendor"):$(cat "${d}/device/device")"
  for f in RP0 RP1 RPn min max boost; do
    echo "gt_${f}_freq_mhz=$(cat "${d}/gt_${f}_freq_mhz")"
  done
done
for d in /sys/class/drm/card?; do
  [ -r "${d}/device/gpu_busy_percent" ] || continue
  echo "gpu_pci=$(cat "${d}/device/vendor"):$(cat "${d}/device/device")"
  echo "amd_sclk_levels=$(tr '\n' ' ' < "${d}/device/pp_dpm_sclk")"
  echo "amd_mclk_levels=$(tr '\n' ' ' < "${d}/device/pp_dpm_mclk")"
  echo "amd_dpm_level=$(cat "${d}/device/power_dpm_force_performance_level")"
  echo "amd_power_profile=$(sed -n 's/^ *[0-9]* *\([A-Z_0-9]*\) *\*.*/\1/p' "${d}/device/pp_power_profile_mode")"
  echo "amd_vbios=$(cat "${d}/device/vbios_version" 2>/dev/null)"
  echo "amdgpu_enable_dv_lab=$(cat /sys/module/amdgpu/parameters/enable_dv_lab 2>/dev/null)"
done
z=/sys/class/powercap/intel-rapl:0
for c in 0 1 2; do
  [ -r "${z}/constraint_${c}_name" ] &&
    echo "rapl_$(cat "${z}/constraint_${c}_name")_uw=$(cat "${z}/constraint_${c}_power_limit_uw")"
done
echo "engine_sha256=$(sha256sum /usr/lib/libdv_engine_vk.so.1 | cut -d' ' -f1)"
echo "kodi_sha256=$(sha256sum /usr/lib/kodi/kodi.bin | cut -d' ' -f1)"
echo "kernel_md5=$(md5sum /flash/KERNEL | cut -d' ' -f1)"
echo "system_md5=$(md5sum /flash/SYSTEM | cut -d' ' -f1)"
echo "dv_prepare=$(systemctl is-active yblod-dv-prepare 2>/dev/null)"
echo "dv_prepare_marker=$(cat /storage/.cache/dv-engine-vk/.prepared 2>/dev/null)"
echo "pipeline_cache=$(ls -l /storage/.cache/dv-engine-vk/*.bin 2>/dev/null | awk '{print $5, $NF}' | tr '\n' ' ')"
echo "env_image=$(grep -v '^#' /usr/lib/kodi/native-dv.env | grep . | tr '\n' ' ')"
echo "env_override=$(grep -v '^#' /storage/.config/native-dv.env 2>/dev/null | grep . | tr '\n' ' ')"
echo "gl_version=$(sed -n 's/.*: GL_VERSION = //p' /storage/.kodi/temp/kodi.log | head -n 1)"
echo "kodi_version=$(sed -n 's/.*Starting Kodi (\(.*\)). Platform.*/\1/p' /storage/.kodi/temp/kodi.log | head -n 1)"
echo "sinks=$(grep -h monitor_name /proc/asound/card*/eld* 2>/dev/null | awk '{$1=""; print}' | tr '\n' ';')"
for c in /sys/class/drm/card?-*; do
  echo "connector_${c##*/}=$(cat "${c}/status")"
done
"""


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class BenchError(Exception):
    pass


class Box:
    """One ssh connection to the box, with Kodi's web server forwarded."""

    def __init__(self, host, image, port):
        state = os.path.expanduser("~/.cache/yblod-bench")
        os.makedirs(state, exist_ok=True)
        self.host = host
        self.port = port
        # A bench profile is a fresh /storage, so it has its own host key.
        self.opts = [
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=15",
            # YBLOD_BENCH_KNOWN_HOSTS=/dev/null: no host key kept (ryzen-fella).
            "-o", "UserKnownHostsFile=" + os.environ.get(
                "YBLOD_BENCH_KNOWN_HOSTS", f"{state}/known_hosts.{image}"),
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"ControlPath={state}/cm-%C",
        ]
        self.tunnel = None

    def ssh(self, command, stdin=None, timeout=120, check=True):
        r = subprocess.run(["ssh", *self.opts, self.host, command], input=stdin,
                           capture_output=True, timeout=timeout)
        if check and r.returncode != 0:
            raise BenchError(f"ssh {command[:60]!r}: {r.stderr.decode(errors='replace').strip()}")
        return r.stdout.decode(errors="replace")

    def write(self, path, data):
        self.ssh(f"mkdir -p '{os.path.dirname(path)}' && cat > '{path}'", stdin=data.encode())

    def fetch(self, remote_dir, local_dir):
        os.makedirs(local_dir, exist_ok=True)
        tar = subprocess.run(["ssh", *self.opts, self.host, f"tar -C '{remote_dir}' -cf - ."],
                             capture_output=True, timeout=120, check=True)
        subprocess.run(["tar", "-C", local_dir, "-xf", "-"], input=tar.stdout, check=True)
        self.ssh(f"rm -rf '{remote_dir}'")

    def open_tunnel(self):
        # The tunnel is the connection every later ssh command shares. The
        # network may be away for a moment: a minute of attempts.
        command = ["ssh", *self.opts, "-M", "-N", "-o", "ExitOnForwardFailure=yes",
                   "-L", f"{self.port}:127.0.0.1:8080", self.host]
        self.tunnel = subprocess.Popen(command)
        for _ in range(30):
            try:
                if self.rpc("JSONRPC.Ping", retries=1) == "pong":
                    return
            except (OSError, BenchError):
                if self.tunnel.poll() is not None:
                    self.tunnel = subprocess.Popen(command)
                time.sleep(2)
        raise BenchError("no JSON-RPC through the ssh tunnel: is the box up and prepared?")

    def close(self):
        if self.tunnel:
            self.tunnel.terminate()
            self.tunnel.wait()

    def rpc(self, method, params=None, timeout=30, retries=3):
        body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1})
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/jsonrpc", data=body.encode(),
            headers={"Content-Type": "application/json", "Authorization":
                     "Basic " + base64.b64encode(RPC_AUTH.encode()).decode()})
        last = None
        for _ in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as f:
                    reply = json.load(f)
                if "error" in reply:
                    raise BenchError(f"{method}: {reply['error']}")
                return reply["result"]
            except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
                last = e
                time.sleep(1)
                if self.tunnel and self.tunnel.poll() is not None and retries > 1:
                    self.open_tunnel()  # the connection dropped: once more through a new one
        raise BenchError(f"{method}: {last}")


# ---------------------------------------------------------------- Kodi

def hms(text):
    h, m, s = (int(x) for x in text.split(":"))
    return h * 3600 + m * 60 + s


def as_time(seconds):
    s = int(seconds)
    return {"hours": s // 3600, "minutes": s % 3600 // 60, "seconds": s % 60,
            "milliseconds": int(round((seconds - s) * 1000))}


def player_time(box):
    p = box.rpc("Player.GetProperties", {"playerid": 1, "properties": ["time", "speed"]})
    t = p["time"]
    return t["hours"] * 3600 + t["minutes"] * 60 + t["seconds"] + t["milliseconds"] / 1000, p["speed"]


def require_idle(box):
    if box.rpc("Player.GetActivePlayers") != []:
        raise BenchError("something is playing on the box: not touching it")


def state(box):
    s = {"booleans": box.rpc("XBMC.GetInfoBooleans", {"booleans": BOOLEANS}),
         "labels": box.rpc("XBMC.GetInfoLabels", {"labels": LABELS}),
         "window": box.rpc("GUI.GetProperties", {"properties": ["currentwindow"]})["currentwindow"]}
    if box.rpc("Player.GetActivePlayers"):
        p = box.rpc("Player.GetProperties", {"playerid": 1, "properties": [
            "time", "speed", "subtitleenabled", "currentsubtitle", "currentaudiostream",
            "currentvideostream"]})
        t = p.pop("time")
        p["time_s"] = t["hours"] * 3600 + t["minutes"] * 60 + t["seconds"] + t["milliseconds"] / 1000
        s["player"] = p
    return s


def open_request(source, film):
    return {"jsonrpc": "2.0", "id": 1, "method": "Player.Open", "params": {
        "item": {"file": f"{source}/{film['file']}"},
        "options": {"resume": as_time(hms(film["start"]))}}}


def wait_playing(box, start):
    deadline = time.time() + 60
    while time.time() < deadline:
        if box.rpc("Player.GetActivePlayers"):
            t, speed = player_time(box)
            if speed == 1 and t >= start + 1:
                return
        time.sleep(0.5)
    raise BenchError("playback did not start within 60 s")


def stop(box):
    if box.rpc("Player.GetActivePlayers"):
        box.rpc("Player.Stop", {"playerid": 1})
    deadline = time.time() + 30
    while time.time() < deadline and box.rpc("Player.GetActivePlayers"):
        time.sleep(0.5)
    time.sleep(6)  # the refresh rate and the signal go back to the menu's


def srt(start, name):
    """A subtitle line of ordinary length on screen 3 s in every 4."""
    def stamp(t):
        return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"
    cues = []
    for i, t in enumerate(range(start - 8, start + 240, 4)):
        cues.append(f"{i + 1}\n{stamp(t)},000 --> {stamp(t + 3)},000\n"
                    f"Benchmark subtitle line {i + 1} for {name},\n"
                    f"two lines of ordinary dialogue length.\n")
    return "\n".join(cues)


def apply_scenario(box, scenario, film_key, film):
    """The state a scenario plays in; called once playback runs."""
    if scenario == "C":
        path = f"{BOX_DIR}/subs/{film_key}.srt"
        box.write(path, srt(hms(film["start"]), film_key))
        box.rpc("Player.AddSubtitle", {"playerid": 1, "subtitle": path})
        time.sleep(1)
        subs = box.rpc("Player.GetProperties",
                       {"playerid": 1, "properties": ["subtitles"]})["subtitles"]
        box.rpc("Player.SetSubtitle",
                {"playerid": 1, "subtitle": subs[-1]["index"], "enable": True})
    else:
        box.rpc("Player.SetSubtitle", {"playerid": 1, "subtitle": "off"})
    if scenario == "B":
        box.rpc("Input.ShowOSD")


def set_scenario_settings(box, scenario, on):
    if scenario == "E":
        box.rpc("Settings.SetSettingValue",
                {"setting": "dvbridge.outputmode", "value": 1 if on else 0})
    if scenario == "P":
        box.rpc("Settings.SetSettingValue", {"setting": "dvbridge.gputiming", "value": on})


def sample(box, name, seconds, request=None):
    """Run box/sample.sh for one window; returns the folder it filled."""
    remote = f"{BOX_DIR}/run/{name}"
    arg = ""
    if request:
        box.write(f"{remote}.request.json", json.dumps(request))
        arg = f" '{remote}.request.json'"
    box.ssh(f"sh {BOX_DIR}/sample.sh '{remote}' {seconds}{arg}", timeout=seconds + 60)
    return remote


def collect(box, remote, raw, since_line, since_epoch):
    """Kodi's log and journal for the pass, then the sampler's files."""
    box.ssh(f"tail -n +{since_line + 1} /storage/.kodi/temp/kodi.log > '{remote}/kodi.log'; "
            f"journalctl -u kodi -o short-unix --no-pager --since @{int(since_epoch)} "
            f"| grep -E 'dvvk|DVVK' > '{remote}/journal.txt'; true")
    box.fetch(remote, raw)
    box.ssh(f"rm -f '{remote}.request.json'")


def log_position(box):
    out = box.ssh("wc -l < /storage/.kodi/temp/kodi.log; date +%s").split()
    return int(out[0]), int(out[1])


# ---------------------------------------------------------------- runs

def run_window(box, cfg, scenario, film_key, rep, raw):
    """Warm-up pass, then the measured pass with one 60 s window."""
    film = cfg["films"][film_key]
    start = hms(film["start"])
    request = open_request(cfg["source"], film)
    driver = {"scenario": scenario, "film": film_key, "rep": rep, "passes": []}
    set_scenario_settings(box, scenario, True)
    try:
        for kind in ("warm-up", "measured"):
            require_idle(box)
            line, epoch = log_position(box)
            box.rpc("Player.Open", request["params"])
            wait_playing(box, start)
            apply_scenario(box, scenario, film_key, film)
            time.sleep(SETTLE)
            if scenario == "D":
                box.rpc("Player.PlayPause", {"playerid": 1, "play": False})
                time.sleep(1)
                box.rpc("Player.Seek", {"playerid": 1,
                                        "value": {"time": as_time(start + PAUSE_AT)}})
                time.sleep(5)
            p = {"kind": kind, "opened_epoch": epoch, "before": state(box)}
            if kind == "warm-up":
                time.sleep(cfg["window_s"])
            else:
                remote = sample(box, f"{film_key}-{scenario}-r{rep}", cfg["window_s"])
            p["after"] = state(box)
            if scenario != "D":
                time.sleep(POST)
            stop(box)
            driver["passes"].append(p)
            if kind == "measured":
                collect(box, remote, raw, line, epoch)
    finally:
        try:
            stop(box)
        finally:
            set_scenario_settings(box, scenario, False)
    with open(os.path.join(raw, "driver.json"), "w") as f:
        json.dump(driver, f, indent=1)


def run_starts(box, cfg, film_key, rep, raw):
    """One discarded start, then STARTS traced starts."""
    film = cfg["films"][film_key]
    start = hms(film["start"])
    request = open_request(cfg["source"], film)
    driver = {"scenario": "F", "film": film_key, "rep": rep, "starts": []}
    try:
        for n in range(STARTS + 1):
            require_idle(box)
            line, epoch = log_position(box)
            if n == 0:
                box.rpc("Player.Open", request["params"])
                time.sleep(START_OBSERVE)
            else:
                remote = sample(box, f"{film_key}-F-r{rep}-s{n}", START_OBSERVE, request)
            wait_playing(box, start)
            if n:
                driver["starts"].append({"n": n, "opened_epoch": epoch, "after": state(box)})
            stop(box)
            if n:
                collect(box, remote, os.path.join(raw, f"s{n}"), line, epoch)
    finally:
        stop(box)
    with open(os.path.join(raw, "driver.json"), "w") as f:
        json.dump(driver, f, indent=1)


def session_info(box, args):
    info = {}
    for line in box.ssh(SESSION_SCRIPT).splitlines():
        k, _, v = line.partition("=")
        info[k] = v.strip()
    settings = {}
    for s in SETTINGS:
        try:
            settings[s] = box.rpc("Settings.GetSettingValue", {"setting": s})["value"]
        except BenchError:
            settings[s] = None
    options = box.rpc("Settings.GetSettings", {"level": "expert", "filter": {
        "section": "player", "category": "dolbyvision"}})["settings"]
    info["outputmode_options"] = next(
        ([o["label"] for o in s.get("options", [])] for s in options
         if s["id"] == "dvbridge.outputmode"), [])
    info["settings"] = settings
    # A variant (--label) is the same profile measured with another environment.
    info["image"] = args.label or args.image
    info["profile"] = args.image
    info["display_note"] = args.display_note
    info["harness"] = {"settle_s": SETTLE, "window_s": args.window, "post_s": POST,
                       "start_observe_s": START_OBSERVE, "starts": STARTS}
    info["recorded"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return info


def cmd_prepare(args):
    box = Box(args.host, args.image, args.port)
    box.ssh(f"mkdir -p {BOX_DIR}")
    for name in ("prepare-profile.sh", "sample.sh"):
        with open(os.path.join(HERE, "box", name)) as f:
            box.write(f"{BOX_DIR}/{name}", f.read())
    name = box.ssh(BENCH_NAME_SH, check=False).strip()
    if name != args.image:
        raise BenchError(f"the box runs bench image {name!r}, not {args.image!r}")
    print(box.ssh(f"sh {BOX_DIR}/prepare-profile.sh", timeout=300), end="")
    log("waiting for yblod-dv-prepare (the engine's pipeline cache)")
    while box.ssh("systemctl is-active yblod-dv-prepare", check=False).strip() == "activating":
        time.sleep(5)
    print(box.ssh("journalctl -u yblod-dv-prepare --no-pager | grep dv-prepare: | tail -n 1; "
                  "cat /storage/.cache/dv-engine-vk/.prepared", check=False), end="")


ENV_FILE = "/storage/.config/native-dv.env"
# The profile's own line (prepare-profile.sh) stays in every variant.
ENV_PROFILE = "DVBRIDGE_DIAGNOSTICS=1"
IDLE_REPLY = '{"id":1,"jsonrpc":"2.0","result":[]}'


def set_env(box, pairs, restart=False):
    """The profile's native-dv.env becomes the profile's line plus `pairs`.

    Kodi reads the file when it starts, so Kodi is restarted, on the box in
    one command with the check that nothing is playing. Returns False when
    the file already held exactly this (nothing is restarted then, unless
    `restart`: for a change Kodi reads at start, advancedsettings.xml say)."""
    for p in pairs:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*=[A-Za-z0-9_.,:/-]*", p):
            raise BenchError(f"not KEY=VALUE: {p!r}")
    want = "\n".join([ENV_PROFILE, *pairs]) + "\n"
    if box.ssh(f"cat {ENV_FILE}", check=False) == want and not restart:
        return False
    box.ssh(f"""players=$(curl -s -m 5 -u {RPC_AUTH} -H 'Content-Type: application/json' \
  -d '{{"jsonrpc":"2.0","method":"Player.GetActivePlayers","id":1}}' http://127.0.0.1:8080/jsonrpc)
[ "$players" = '{IDLE_REPLY}' ] || {{ echo "Kodi is playing or does not answer: $players" >&2; exit 1; }}
cat > {ENV_FILE}.new && mv {ENV_FILE}.new {ENV_FILE} && systemctl restart kodi""", stdin=want.encode())
    return True


def wait_home(box):
    """Kodi answers and shows its home screen (after a restart)."""
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            if box.rpc("GUI.GetProperties", {"properties": ["currentwindow"]}, retries=1)[
                    "currentwindow"]["id"] == 10000:
                time.sleep(10)  # add-on services and the audio engine settle
                return
        except BenchError:
            pass
        time.sleep(2)
    raise BenchError("Kodi did not come back to its home screen in 120 s")


def cmd_env(args):
    box = Box(args.host, args.image, args.port)
    name = box.ssh(BENCH_NAME_SH, check=False).strip()
    if name != args.image:
        raise BenchError(f"the box runs bench image {name!r}, not {args.image!r}")
    changed = set_env(box, args.pairs, args.restart)
    if changed:
        box.open_tunnel()
        try:
            wait_home(box)
        finally:
            box.close()
    log(("Kodi restarted with " if changed else "unchanged: ") +
        box.ssh(f"cat {ENV_FILE}").replace("\n", " "))


def cmd_run(args):
    with open(args.matrix) as f:
        cfg = json.load(f)
    cfg["window_s"] = args.window
    out = os.path.join(args.out, args.label or args.image)
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    box = Box(args.host, args.image, args.port)
    name = box.ssh(BENCH_NAME_SH, check=False).strip()
    if name != args.image:
        raise BenchError(f"the box runs bench image {name!r}, not {args.image!r}")
    if box.ssh("systemctl is-active yblod-dv-prepare", check=False).strip() == "activating":
        raise BenchError("yblod-dv-prepare is still building the pipeline cache: run 'prepare'")
    box.open_tunnel()
    failures = 0
    try:
        require_idle(box)
        session = session_info(box, args)
        session_path = os.path.join(out, "session.json")
        if not os.path.exists(session_path):
            with open(session_path, "w") as f:
                json.dump(session, f, indent=1)
        scenarios = args.scenarios.split(",") if args.scenarios else list(cfg["scenarios"])
        for rep in range(args.first_rep, args.first_rep + args.reps):
            for scenario in scenarios:
                for film_key in cfg["scenarios"][scenario]:
                    if args.films and film_key not in args.films.split(","):
                        continue
                    run = f"{film_key}-{scenario}-r{rep}"
                    result = os.path.join(out, run + ".json")
                    if os.path.exists(result) and not args.force:
                        continue
                    raw = os.path.join(out, "raw", run)
                    subprocess.run(["rm", "-rf", raw], check=True)
                    os.makedirs(raw)
                    log(f"{run}: {SCENARIOS[scenario]}")
                    try:
                        if scenario == "F":
                            run_starts(box, cfg, film_key, rep, raw)
                        else:
                            run_window(box, cfg, scenario, film_key, rep, raw)
                        data = analyse(raw, session, cfg)
                        with open(result, "w") as f:
                            json.dump(data, f, indent=1)
                        if os.path.exists(os.path.join(out, run + ".failed.txt")):
                            os.remove(os.path.join(out, run + ".failed.txt"))
                        log(f"{run}: {headline(data)}")
                    except (BenchError, subprocess.SubprocessError, OSError, KeyError,
                            ValueError) as e:
                        failures += 1
                        log(f"{run}: FAILED: {e}")
                        with open(os.path.join(out, run + ".failed.txt"), "w") as f:
                            f.write(f"{e}\n")
    finally:
        try:
            stop(box)
        except BenchError:
            pass
        box.close()
    return 1 if failures else 0


# ---------------------------------------------------------------- analysis

def read(path, default=None):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        if default is None:
            raise
        return default


def snapshot(raw, n):
    """One of sample.sh's two snapshots, parsed."""
    lines = read(f"{raw}/{n}.time").split("\n")
    before, after = float(lines[0]), float(lines[2])
    local = datetime.datetime.strptime(lines[1], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=datetime.timezone.utc).timestamp()
    snap = {"epoch": (before + after) / 2, "read_ms": (after - before) * 1000,
            # Kodi's log is in the box's local time: its offset from the epoch.
            "log_offset": round(local - int(before))}
    engines = {}
    for line in read(f"{raw}/{n}.fdinfo").splitlines():
        f = line.split()
        if len(f) >= 3 and f[0]:
            key = (f[0], f[1].rstrip(":").replace("drm-engine-", ""))
            engines[key] = max(engines.get(key, 0), int(f[2]))  # several fds per client
    snap["engines"] = engines

    def ticks(line):
        f = line[line.rindex(")") + 2:].split()
        return int(f[11]) + int(f[12])
    stat = read(f"{raw}/{n}.stat")
    snap["pid"] = int(stat.split()[0])
    snap["process_ticks"] = ticks(stat)
    snap["threads"] = {}
    for line in read(f"{raw}/{n}.tasks", "").splitlines():
        if ")" in line:
            name = line[line.index("(") + 1:line.rindex(")")]
            snap["threads"][int(line.split()[0])] = (name, ticks(line))
    cpu = [int(x) for x in read(f"{raw}/{n}.cpustat").split()[1:]]
    snap["cpu_total"], snap["cpu_idle"] = sum(cpu[:8]), cpu[3] + cpu[4]
    snap["rapl"] = {}
    for line in read(f"{raw}/{n}.rapl", "").splitlines():
        f = line.split()
        if len(f) == 3 and f[0] not in snap["rapl"]:
            snap["rapl"][f[0]] = (int(f[1]), int(f[2]))
    snap["temp"] = {}
    for line in read(f"{raw}/{n}.temp", "").splitlines():
        f = line.rsplit(" ", 1)
        snap["temp"][f[0]] = int(f[1]) / 1000
    return snap


MARK = re.compile(r"\s(\d+\.\d+): tracing_mark_write: bench:(\w+)")
FLIP = re.compile(r"\s(\d+\.\d+): drm_vblank_event_delivered: .*crtc=(\d+), seq=(\d+)")
VBLANK = re.compile(r"\s(\d+\.\d+): drm_vblank_event: crtc=(\d+), seq=(\d+), time=(\d+)")


def trace(raw):
    """Markers, flips (trace time, vblank sequence, vblank ns) and loss."""
    marks, flips, vblank, lost = {}, [], {}, None
    with gzip.open(f"{raw}/trace.txt.gz", "rt") as f:
        for line in f:
            if line.startswith("# entries-in-buffer"):
                a, b = re.search(r"(\d+)/(\d+)", line).groups()
                lost = int(b) - int(a)
                continue
            m = FLIP.search(line)
            if m:
                flips.append((float(m.group(1)), int(m.group(2)), int(m.group(3))))
                continue
            m = VBLANK.search(line)
            if m:
                vblank[(int(m.group(2)), int(m.group(3)))] = int(m.group(4))
                continue
            m = MARK.search(line)
            if m:
                marks[m.group(2)] = float(m.group(1))
    crtcs = collections.Counter(c for _, c, _ in flips)
    crtc = crtcs.most_common(1)[0][0] if crtcs else 0
    flips = [(t, s) for t, c, s in flips if c == crtc]
    # The refresh period, from the vertical blanks that had an interrupt.
    v = sorted((s, t) for (c, s), t in vblank.items() if c == crtc)
    periods = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(v, v[1:]) if 0 < b[0] - a[0] <= 4]
    period_ms = statistics.median(periods) / 1e6 if periods else None
    if period_ms is None and len(flips) > 1 and flips[-1][1] > flips[0][1]:
        # No vertical blank was traced with its timestamp (queued flips complete
        # without one): the flips' own trace times over their sequence numbers.
        period_ms = (flips[-1][0] - flips[0][0]) * 1000 / (flips[-1][1] - flips[0][1])
    return marks, flips, lost, period_ms


def presentation(marks, flips, period_ms, source_fps):
    """Flips between the two markers and the gaps between them in refreshes."""
    inside = [f for f in flips if marks["t0"] < f[0] <= marks["t1"]]
    seconds = marks["t1"] - marks["t0"]
    gaps = [b[1] - a[1] for a, b in zip(inside, inside[1:])]
    out = {
        "flips": len(inside),
        "presented_fps": round(len(inside) / seconds, 3),
        "refresh_hz": round(1000 / period_ms, 3) if period_ms else None,
        "gap_histogram": {str(k): v for k, v in sorted(collections.Counter(gaps).items())},
        "longest_gap_refreshes": max(gaps) if gaps else None,
        "longest_gap_ms": round(max(b[0] - a[0] for a, b in zip(inside, inside[1:])) * 1000, 1)
        if gaps else None,
        "gap_sequence_head": " ".join(str(g) for g in gaps[:24]),
    }
    if period_ms and source_fps:
        expected = max(1, round(1000 / period_ms / source_fps))
        out["expected_gap"] = expected
        out["gaps_off_cadence"] = sum(1 for g in gaps if g != expected)
        out["presented_share_of_source"] = round(out["presented_fps"] / source_fps, 4)
    return out


FLIPS = re.compile(r"DV flips queued=(\d+): on_time=(\d+) late=(\d+) blocking=(\d+) busy=(\d+) "
                   r"timeouts=(\d+) queued_to_vblank_ms mean=([\d.]+) max=([\d.]+)")
HEALTH = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) .*DVBridge playback health: (.*)")
STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) ")


def log_epoch(stamp, offset):
    t = datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S.%f").replace(
        tzinfo=datetime.timezone.utc).timestamp()
    return t - offset


def kodi_log(raw, t0, t1, offset):
    """What Kodi's own log says about the pass."""
    out = {"health_lines": 0}
    health = []
    opened = None
    for line in read(f"{raw}/kodi.log", "").splitlines():
        m = STAMP.match(line)
        when = log_epoch(m.group(1), offset) if m else None
        if "VideoPlayer::OpenFile" in line and opened is None:
            opened = when
            out["openfile_epoch"] = when
        m = HEALTH.match(line)
        if m:
            kv = dict(x.split("=", 1) for x in m.group(2).split() if "=" in x)
            health.append((when, kv))
        elif "DVBridge stream candidate" in line and "native_eligible=true" in line:
            out.setdefault("stream", line.split("candidate: ")[1].split(" native_")[0])
        elif "Vulkan engine started" in line:
            out["engine"] = line.split("): ", 1)[-1]
        elif "Dolby Vision MEL: " in line:
            out["enhancement_layer"] = line.split("<general>: ")[-1]
        elif "DVBridge signal committed" in line and opened is not None:
            if "signal_s" not in out:
                out["signal_s"] = round(when - opened, 3)
                out["signal"] = line.split("committed: ")[1]
            if t1 is not None and when <= t1:  # the signal the window ran in
                out["signal"] = line.split("committed: ")[1]
        elif "Private source frame: serial=1 " in line and opened is not None:
            out.setdefault("first_frame_s", round(when - opened, 3))
        elif "DVBridge output: " in line or "Vulkan engine output: " in line:
            out.setdefault("output", []).append(line.split("<general>: ")[-1])
        elif "Private source renderer closed" in line:
            out["renderer_closed"] = line.split("closed: ")[1]
        elif "Creating audio stream" in line:
            out["audio_stream"] = line.split("Creating audio stream ")[1]
        elif FLIPS.search(line):
            # Non-blocking presentation: cumulative since Kodi started, every 600 queued flips.
            g = FLIPS.search(line).groups()
            out["flips_summary_last"] = dict(zip(
                ("queued", "on_time", "late", "blocking", "busy", "timeouts"), map(int, g[:6])))
            out["flips_summary_lines"] = out.get("flips_summary_lines", 0) + 1
    if health and t0 is not None:
        out["source_fps"] = float(health[-1][1]["source_fps"])
        inside = [h for h in health if t0 <= h[0] <= t1]
        out["health_lines"] = len(inside)
        before = [h for h in health if h[0] <= t0]
        after = [h for h in health if h[0] >= t1]
        if before and after:
            a, b = before[-1], after[0]
            out["dropped"] = int(b[1]["drop_total"]) - int(a[1]["drop_total"])
            out["skipped"] = int(b[1]["skip_total"]) - int(a[1]["skip_total"])
            out["counter_span_s"] = round(b[0] - a[0], 1)
        full = [h for h in inside if h[0] - int(h[1]["interval_ms"]) / 1000 >= t0]
        if full:
            out["output_attempts_per_s"] = round(
                sum(int(h[1]["output_attempts"]) for h in full) /
                sum(int(h[1]["interval_ms"]) / 1000 for h in full), 2)
    return out


PROFILE = re.compile(r"^(\d+\.\d+) .*dvvk profile: gpu ([\d.]+) ms \(p95 ([\d.]+), max ([\d.]+)\)(.*)")


def engine_profile(raw, t0, t1):
    """The engine's own GPU timestamps (DVVK_PROFILE), 120 frames per line."""
    rows, stages, fel = [], None, None
    for line in read(f"{raw}/journal.txt", "").splitlines():
        if "dvvk profile: staged FEL" in line:
            fel = line.split("dvvk profile: ")[1]
        m = PROFILE.match(line)
        if m and t0 <= float(m.group(1)) <= t1:
            rows.append((float(m.group(2)), float(m.group(3)), float(m.group(4))))
            stages = m.group(5).strip(" =")
    if not rows:
        return None
    return {"lines": len(rows), "frames": 120 * len(rows),
            "gpu_ms_mean": round(statistics.mean(r[0] for r in rows), 3),
            "gpu_ms_p95_worst": max(r[1] for r in rows),
            "gpu_ms_max": max(r[2] for r in rows),
            "stages_last_line": stages, "fel_stages_last_line": fel}


def window_metrics(raw, driver):
    a, b = snapshot(raw, "t0"), snapshot(raw, "t1")
    seconds = b["epoch"] - a["epoch"]
    kodi = kodi_log(raw, a["epoch"], b["epoch"], a["log_offset"])
    labels = driver["passes"][-1]["before"]["labels"]
    try:
        source_fps = kodi.get("source_fps") or float(labels["Player.Process(videofps)"])
    except ValueError:
        source_fps = None
    marks, flips, lost, period_ms = trace(raw)
    present = presentation(marks, flips, period_ms, source_fps)
    present["trace_events_lost"] = lost

    clients = {}
    for (client, engine), ns in b["engines"].items():
        if (client, engine) in a["engines"]:
            d = (ns - a["engines"][(client, engine)]) / 1e6
            if d > 0:
                clients.setdefault(client, {})[engine] = round(d, 2)
    render = sum(sum(v for e, v in c.items() if e in ("render", "gfx", "compute"))
                 for c in clients.values())
    video = sum(sum(v for e, v in c.items() if e in ("video", "dec", "video-enhance"))
                for c in clients.values())
    largest = max((sum(v for e, v in c.items() if e in ("render", "gfx", "compute"))
                   for c in clients.values()), default=0)
    n = present["flips"]
    busy_before = {c for (c, e), ns in a["engines"].items() if ns}
    busy_after = {c for (c, e), ns in b["engines"].items() if ns}
    gpu = {
        # The same DRM clients at both ends: no engine restarted in between.
        "clients_complete": bool(busy_before) and busy_after <= busy_before,
        "render_ms_per_presented_frame": round(render / n, 3) if n else None,
        "render_ms_per_source_frame": round(render / (seconds * source_fps), 3)
        if source_fps else None,
        "engine_client_ms_per_presented_frame": round(largest / n, 3) if n else None,
        "video_ms_per_presented_frame": round(video / n, 3) if n else None,
        "render_busy_pct": round(100 * render / (seconds * 1000), 2),
        "video_busy_pct": round(100 * video / (seconds * 1000), 2),
        "clients_ms": clients,
    }

    threads = []
    for tid, (name, t) in b["threads"].items():
        if tid in a["threads"]:
            threads.append((100 * (t - a["threads"][tid][1]) / CLK_TCK / seconds, name, tid))
    threads.sort(reverse=True)
    cores = (b["cpu_total"] - a["cpu_total"]) / CLK_TCK / seconds
    cpu = {
        "process_pct": round(100 * (b["process_ticks"] - a["process_ticks"]) / CLK_TCK / seconds, 1),
        "render_thread_pct": round(next((p for p, _, tid in threads if tid == a["pid"]), 0), 1),
        "top_threads_pct": [[name, round(p, 1)] for p, name, _ in threads[:6]],
        "system_busy_pct_of_all_cores": round(100 * (1 - (b["cpu_idle"] - a["cpu_idle"]) /
                                                      (b["cpu_total"] - a["cpu_total"])), 1),
        "cores": round(cores),
    }

    lines = [x.split() for x in read(f"{raw}/freq.txt", "").splitlines()]
    freq = [int(f[1]) for f in lines if len(f) == 3 and f[1].isdigit()]
    # amdgpu: "time sclk_mhz amd busy_pct". The shader clock never reads 0
    # (GFXOFF does not show in it): no share asleep, the busy % instead.
    amd = [(int(f[1]), int(f[3])) for f in lines if len(f) == 4 and f[2] == "amd"]
    clock = {"samples": len(freq) + len(amd)}
    awake = [x for x in freq if x]  # 0: the GPU was asleep (RC6) at that sample
    if freq:
        clock["share_asleep"] = round(freq.count(0) / len(freq), 3)
    if amd:
        awake = [mhz for mhz, _ in amd]
        clock["amd_busy_pct_mean"] = round(statistics.mean(b for _, b in amd), 1)
        clock["amd_profile"] = [read(f"{raw}/{n}.amdpm", "").split() for n in ("t0", "t1")]
    if awake:
        clock.update({"awake_mhz_mean": round(statistics.mean(awake)),
                      "awake_mhz_median": statistics.median(awake),
                      "awake_mhz_min": min(awake), "awake_mhz_max": max(awake)})
    power = {}
    for zone, (uj, wrap) in b["rapl"].items():
        if zone in a["rapl"]:
            d = uj - a["rapl"][zone][0]
            power[zone.replace("-", "_") + "_w"] = round((d + wrap if d < 0 else d) / 1e6 / seconds, 2)

    return {"window_s": round(seconds, 3), "source_fps": source_fps, "gpu": gpu,
            "presentation": present, "kodi": kodi, "cpu": cpu, "gpu_clock": clock,
            "power": power, "temperature_c": {"start": a["temp"], "end": b["temp"]},
            "engine_profile": engine_profile(raw, a["epoch"], b["epoch"]),
            "audio": read(f"{raw}/audio.txt", "").strip(),
            "display": read(f"{raw}/display.txt", "").strip().splitlines(),
            "window_start": datetime.datetime.fromtimestamp(
                a["epoch"], datetime.timezone.utc).isoformat(timespec="seconds")}


def checks(scenario, m, driver):
    """What must hold for the window to be the scenario it claims to be."""
    p = driver["passes"][-1]
    before, after = p["before"], p["after"]
    bb, ab = before["booleans"], after["booleans"]
    osd = scenario == "B"
    advanced = after["player"]["time_s"] - before["player"]["time_s"]
    signal = m["kodi"].get("signal", "")
    c = {
        "fullscreen_video": bb["Window.IsActive(fullscreenvideo)"] and
        ab["Window.IsActive(fullscreenvideo)"],
        "osd_as_scenario": bb["Window.IsVisible(videoosd)"] == osd and
        ab["Window.IsVisible(videoosd)"] == osd,
        # The video OSD is itself a modal dialog.
        "no_dialog": not (bb["Window.IsVisible(notification)"]
                          or ab["Window.IsVisible(notification)"]
                          or (not osd and (bb["System.HasActiveModalDialog"]
                                           or ab["System.HasActiveModalDialog"]))),
        "subtitles_as_scenario": (before["player"]["subtitleenabled"] ==
                                  after["player"]["subtitleenabled"] == (scenario == "C")),
        "passthrough": bb["Player.Passthrough"] and
        before["labels"]["Player.Process(audiodecoder)"].startswith("pt-") and
        "S16_LE" in m["audio"],
        "trace_complete": m["presentation"]["trace_events_lost"] == 0,
        "fdinfo_complete": m["gpu"]["clients_complete"],
        # The tunnel carries Dolby Vision without an HDR10 metadata blob,
        # and the engine's HDR10 (scenario E) with one.
        "tunnel_signal": " dv=1 " in f" {signal} ",
        "output_as_scenario": (" hdr_blob=0 " not in f" {signal} ") == (scenario == "E"),
    }
    if scenario == "D":
        c["paused"] = bb["Player.Paused"] and ab["Player.Paused"] and abs(advanced) < 0.1
    else:
        c["played_through"] = abs(advanced - m["window_s"]) < 2.5
    return c


def start_metrics(raw):
    marks, flips, lost, _ = trace(raw)
    t = marks.get("request", marks["t0"])
    after = [f for f in flips if f[0] > t]
    first = None
    for i in range(len(after) - 1, 0, -1):
        if after[i][0] - after[i - 1][0] > STEADY_GAP:
            first = after[i]
            break
    else:
        first = after[0] if after else None
    a = snapshot(raw, "t0")
    kodi = kodi_log(raw, None, None, a["log_offset"])
    out = {"flips_traced": len(after), "trace_events_lost": lost,
           "kodi_signal_s": kodi.get("signal_s"), "kodi_first_frame_s": kodi.get("first_frame_s"),
           "signal": kodi.get("signal")}
    if first and marks["t1"] - first[0] >= 3:
        out["start_s"] = round(first[0] - t, 3)
        out["steady_s_observed"] = round(marks["t1"] - first[0], 1)
    return out


def analyse(raw, session, cfg):
    with open(f"{raw}/driver.json") as f:
        driver = json.load(f)
    scenario, film = driver["scenario"], driver["film"]
    data = {"image": session["image"], "os_version": session.get("os_version"),
            "kernel": session.get("kernel"), "film": film, "scenario": scenario,
            "scenario_text": SCENARIOS[scenario], "rep": driver["rep"],
            "title": cfg["films"][film]["title"], "start": cfg["films"][film]["start"],
            "expect": cfg["films"][film]["expect"]}
    if scenario == "F":
        data["starts"] = [start_metrics(f"{raw}/s{s['n']}") for s in driver["starts"]]
        good = [s["start_s"] for s in data["starts"] if "start_s" in s]
        data["start_s_median"] = statistics.median(good) if good else None
        data["start_s_min"], data["start_s_max"] = (min(good), max(good)) if good else (None, None)
        data["valid"] = len(good) == len(data["starts"])
        return data
    m = window_metrics(raw, driver)
    data.update(m)
    last = driver["passes"][-1]
    data["player"] = {"labels": last["before"]["labels"],
                      "time_start_s": last["before"]["player"]["time_s"],
                      "time_end_s": last["after"]["player"]["time_s"],
                      "audio": last["before"]["player"]["currentaudiostream"],
                      "subtitle": last["before"]["player"]["currentsubtitle"]
                      if last["before"]["player"]["subtitleenabled"] else None,
                      "booleans_start": last["before"]["booleans"],
                      "booleans_end": last["after"]["booleans"]}
    if scenario == "C":
        data["subtitle_note"] = "generated SRT: a two-line cue on screen 3 s in every 4"
    data["checks"] = checks(scenario, m, driver)
    data["valid"] = all(data["checks"].values())
    return data


def headline(d):
    if d["scenario"] == "F":
        return f"start {d['start_s_median']} s (median of {len(d['starts'])})"
    g, p, k = d["gpu"], d["presentation"], d["kodi"]
    text = (f"{g['render_ms_per_presented_frame']} ms/frame, {p['presented_fps']} fps at "
            f"{p['refresh_hz']} Hz, gaps {p['gap_histogram']}, drops {k.get('dropped')} "
            f"skips {k.get('skipped')}, render thread {d['cpu']['render_thread_pct']}%, "
            f"GPU {d['gpu_clock'].get('awake_mhz_mean')} MHz")
    if d.get("engine_profile"):
        text += f", engine {d['engine_profile']['gpu_ms_mean']} ms"
    if not d["valid"]:
        text += "  INVALID: " + ", ".join(k for k, v in d["checks"].items() if not v)
    return text


def cmd_analyse(args):
    with open(args.matrix) as f:
        cfg = json.load(f)
    with open(os.path.join(args.dir, "session.json")) as f:
        session = json.load(f)
    for run in sorted(os.listdir(os.path.join(args.dir, "raw"))):
        raw = os.path.join(args.dir, "raw", run)
        if not os.path.exists(f"{raw}/driver.json"):
            continue
        data = analyse(raw, session, cfg)
        with open(os.path.join(args.dir, run + ".json"), "w") as f:
            json.dump(data, f, indent=1)
        print(run, headline(data))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("prepare", "env", "run"):
        p = sub.add_parser(name)
        p.add_argument("--host", required=True, help="root@BOX")
        p.add_argument("--image", required=True, help="the bench profile's name (bench-name)")
        p.add_argument("--port", type=int, default=18080, help="local port for Kodi's JSON-RPC")
        if name == "prepare":
            continue
        if name == "env":
            p.add_argument("pairs", nargs="*", metavar="KEY=VALUE",
                           help="the profile's native-dv.env besides its own line (none: only that)")
            p.add_argument("--restart", action="store_true",
                           help="restart Kodi also when the file is unchanged")
            continue
    p.add_argument("--out", required=True, help="results directory (a folder per image)")
    p.add_argument("--label", help="the results folder and the image's name in the report, for a "
                   "variant of the profile (another native-dv.env); default: --image")
    p.add_argument("--matrix", default=os.path.join(HERE, "matrix.json"))
    p.add_argument("--scenarios", help="comma-separated, default: all in the matrix")
    p.add_argument("--films", help="comma-separated, default: all of each scenario")
    p.add_argument("--reps", type=int, default=2)
    p.add_argument("--window", type=int, default=WINDOW,
                   help="measured seconds (60: shorter only to try the harness)")
    p.add_argument("--first-rep", type=int, default=1)
    p.add_argument("--force", action="store_true", help="measure again what has a result")
    p.add_argument("--display-note", default="not recorded",
                   help="what the TV was doing (on, standby, input), for the record")
    p = sub.add_parser("analyse")
    p.add_argument("dir", help="RESULTS/IMAGE")
    p.add_argument("--matrix", default=os.path.join(HERE, "matrix.json"))
    args = ap.parse_args()
    try:
        return {"prepare": cmd_prepare, "env": cmd_env, "run": cmd_run,
                "analyse": cmd_analyse}[args.command](args)
    except BenchError as e:
        print(f"bench: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
