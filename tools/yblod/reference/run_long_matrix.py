"""Private lab controller: bounded matched playback and clean service restarts.

Kodi runs in its own service; this controller does not change its memory cap.
On any unexpected failure, leave state for diagnosis rather than force cleanup.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request


def command(*args, timeout=45):
    return subprocess.check_output(args, text=True, timeout=timeout)


def wait_rpc():
    for _ in range(30):
        try:
            data = json.dumps(dict(jsonrpc="2.0", id=1,
                                   method="Player.GetActivePlayers")).encode()
            request = urllib.request.Request("http://127.0.0.1:8080/jsonrpc", data,
                                             {"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=2) as response:
                result = json.load(response)
            if result.get("result") == []:
                return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("Kodi did not become idle and reachable")


def identity(service):
    return {key: value for key, value in
            (line.split("=", 1) for line in service.splitlines() if "=" in line)
            if key in ("MainPID", "ActiveEnterTimestampMonotonic")}


def playback_cases(start_case_index):
    """Only explicitly resume after the controller-qualified first pair."""
    if start_case_index not in (0, 2):
        raise ValueError("start case index must be 0 or explicitly requested 2")
    cases = []
    for movie_id, title in ((51, "1917"), (3391, "Saving Private Ryan")):
        for seek in (0, 1200):
            routes = ("integer", "fp32") if seek == 0 else ("fp32", "integer")
            cases.extend((movie_id, title, seek, route) for route in routes)
    return cases[start_case_index:]


def argument_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary-sha256", required=True)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--observer", required=True, type=Path)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--start-case-index", type=int, choices=(0, 2), default=0,
                        help="2 explicitly resumes after the already-qualified first pair; "
                             "no reports or filenames are used to infer skipped cases")
    return parser


def main():
    args = argument_parser().parse_args()
    cases = playback_cases(args.start_case_index)
    if not 75 <= args.seconds <= 900:
        raise ValueError("bounded playback duration required")
    if not args.root.is_dir() or any(args.root.iterdir()):
        raise ValueError("fresh output directory required")
    service = command("systemctl", "show", "kodi", "-p", "ActiveState", "--value").strip()
    if service != "inactive":
        raise RuntimeError("controller must start with Kodi cleanly stopped")
    if command("systemctl", "show", "kodi", "-p", "Result", "--value").strip() != "success":
        raise RuntimeError("previous service shutdown was not clean")
    configuration = Path("/run/systemd/system/kodi.service.d/yblod-native-playback.conf")
    original = configuration.read_bytes()
    completed = []
    try:
        for movie_id, title, seek, route in cases:
            label = f"movie{movie_id}-seek{seek}-{route}"
            shutil.copyfile(Path(__file__).parent / f"kodi-native-playback-{route}.conf",
                            configuration)
            command("systemctl", "daemon-reload")
            run_started = int(time.time())
            command("systemctl", "start", "kodi")
            wait_rpc()
            print(f"BEGIN {label}", flush=True)
            observer = ["/usr/bin/python3", str(args.observer), "--seconds", str(args.seconds),
                        "--report", label + ".json", "--output-dir", str(args.root),
                        "--label", label, "--expected-binary-sha256", args.binary_sha256,
                        "--movie-id", str(movie_id), "--expected-title", title,
                        "--seek-seconds", str(seek), "--expected-route", route,
                        "--stop-on-complete"]
            with (args.root / (label + ".observer.log")).open("x") as log:
                subprocess.run(observer, stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=args.seconds + 100)
            report = json.loads((args.root / (label + ".json")).read_text())
            if report["failure_marker"]:
                raise RuntimeError(f"observer qualification failed: {label}")
            after_stop = json.loads((args.root / (label + ".json.stop.json")).read_text())
            if after_stop["active_players"]:
                raise RuntimeError("player stop incomplete")
            if identity(after_stop["runtime"]["service"]) != identity(report["runtime_after"]["service"]):
                raise RuntimeError("service identity changed during player stop")
            command("systemctl", "stop", "kodi")
            status = dict(line.split("=", 1) for line in command(
                "systemctl", "show", "kodi", "-p", "Result", "-p", "ActiveState",
                "-p", "MainPID", "-p", "ExecMainCode", "-p", "ExecMainStatus").splitlines())
            shutil.copyfile("/storage/.kodi/temp/kodi.log", args.root / (label + ".kodi.log"))
            journal = command("journalctl", "-u", "kodi", "--since", f"@{run_started}", "--no-pager")
            (args.root / (label + ".journal.log")).write_text(journal)
            (args.root / (label + ".shutdown.json")).write_text(json.dumps(status))
            if (status.get("Result") != "success" or status.get("ActiveState") != "inactive"
                    or status.get("MainPID") != "0" or status.get("ExecMainCode") != "1"
                    or status.get("ExecMainStatus") != "0"):
                raise RuntimeError(f"unclean service shutdown: {label}: {status}")
            if re.search(r"core dumped|dumped core|corrupted size|segfault|ABRT|Aborted|SIGABRT",
                         journal, re.IGNORECASE):
                raise RuntimeError(f"child crash marker: {label}")
            completed.append(label)
            print(f"PASS playback/stop/shutdown {label}", flush=True)
        print(json.dumps(dict(status="complete", start_case_index=args.start_case_index,
                              requested_cases=len(cases), completed=completed)), flush=True)
    finally:
        # Restore only the original override. Do not restart/kill on failure.
        configuration.write_bytes(original)
        command("systemctl", "daemon-reload")


if __name__ == "__main__":
    main()
