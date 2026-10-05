#!/usr/bin/env python3
"""Read-only, on-device Kodi CPU/i915 busy-time sampling. Does not control playback."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request


def rpc(method, params):
    data = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request("http://127.0.0.1:8080/jsonrpc", data,
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.load(response)
    if "error" in result:
        raise RuntimeError(result["error"])
    return result["result"]


def snapshot(pid):
    clients = {}
    for path in Path(f"/proc/{pid}/fdinfo").iterdir():
        try:
            fields = dict(line.split(":", 1) for line in path.read_text().splitlines() if ":" in line)
        except FileNotFoundError:
            continue
        if fields.get("drm-driver", "").strip() != "i915":
            continue
        key = fields["drm-pdev"].strip() + "/" + fields["drm-client-id"].strip()
        client = clients.setdefault(key, {})
        for name, value in fields.items():
            if name.startswith("drm-engine-") and not name.startswith("drm-engine-capacity-"):
                engine = name[len("drm-engine-"):]
                client[engine] = max(client.get(engine, 0), int(value.split()[0]))
    stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    clocks = {}
    for path in Path("/sys/class/drm").glob("card*/gt_act_freq_mhz"):
        clocks[path.parent.name] = int(path.read_text())
    return {"monotonic": time.monotonic(), "clients_ns": clients,
            "cpu_ticks": int(stat[11]) + int(stat[12]), "gpu_mhz": clocks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--at", type=float, help="wait for this playback time in seconds")
    args = parser.parse_args()
    if not 10 <= args.seconds <= 300:
        parser.error("duration must be between 10 and 300 seconds")
    pid = int(subprocess.check_output(["pidof", "kodi.bin"], text=True).strip())
    properties = {"playerid": 1, "properties": ["time", "speed", "subtitleenabled"]}
    if args.at is not None:
        deadline = time.monotonic() + 30
        while True:
            current = rpc("Player.GetProperties", properties)["time"]
            position = current["hours"]*3600 + current["minutes"]*60 + current["seconds"] + current["milliseconds"]/1000
            if position > args.at + 1:
                raise SystemExit("missed benchmark start; seek back and retry")
            if position >= args.at:
                break
            if time.monotonic() > deadline:
                raise SystemExit("timed out waiting for benchmark start")
            time.sleep(.2)
    before = rpc("Player.GetProperties", properties)
    settings = {key: rpc("Settings.GetSettingValue", {"setting": key})["value"]
                for key in ("dvbridge.directconversion", "dvbridge.qsvmode", "dvbridge.matchhardware")}
    log = Path("/storage/.kodi/temp/kodi.log")
    start_log = log.stat().st_size
    samples = [snapshot(pid)]
    for _ in range(args.seconds):
        time.sleep(1)
        samples.append(snapshot(pid))
    after = rpc("Player.GetProperties", properties)
    first, last = samples[0], samples[-1]
    elapsed = last["monotonic"] - first["monotonic"]
    stable = all(set(s["clients_ns"]) == set(first["clients_ns"]) for s in samples)
    busy = {}
    for client in first["clients_ns"]:
        for engine, start in first["clients_ns"][client].items():
            end = last["clients_ns"].get(client, {}).get(engine, start)
            busy[engine] = busy.get(engine, 0) + (end-start)/elapsed/1e7
    cpu = (last["cpu_ticks"]-first["cpu_ticks"])/os.sysconf("SC_CLK_TCK")/elapsed*100
    with log.open() as stream:
        stream.seek(start_log)
        events = [line.strip() for line in stream if "DVBridge" in line and
                  any(word in line for word in ("conversion:", "summary:", "fail", "graphics:"))]
    print(json.dumps({"label": args.label, "seconds": elapsed, "settings": settings,
                      "player_before": before, "player_after": after,
                      "stable_gpu_clients": stable, "cpu_percent_one_core": cpu,
                      "gpu_engine_busy_percent": busy, "events": events, "samples": samples}, indent=2))
    if not stable or before["speed"] != 1 or after["speed"] != 1:
        raise SystemExit("invalid measurement: playback or GPU clients changed")


if __name__ == "__main__":
    main()
