#!/usr/bin/env python3
"""Temporarily hide the mesondrmfb GUI plane around a paused-picture capture.

Requires an operator to confirm the GUI is initially visible. Restores blank=0
in finally, but reports only completion of that write, not proven hardware
state. Capture files are placed in OUTPUT/capture; the orchestration record is
OUTPUT/gui-plane-orchestration.json. No playback or precision changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import signal
import sys
import time

import capture_repeat


class GuiBackend:
    name = Path("/sys/class/graphics/fb0/name")
    control = Path("/sys/class/graphics/fb0/blank")

    def inspect(self):
        return {"name": self.name.read_text().strip(), "name_path": str(self.name),
                "control_path": str(self.control), "blank_readback": self.control.read_text()}

    def write(self, value):
        self.control.write_text(f"{value}\n")


def validate_output(output):
    output = Path(output).resolve()
    if (not output.is_relative_to(Path("/storage")) or
            not re.fullmatch(r"[A-Za-z0-9_./-]+", str(output))):
        raise ValueError("fresh output must be a whitespace-free path under /storage")
    return output


def source_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(output, *, confirm_visible_gui=False, cycles=3,
        allow_unverified_dma_sync=False, backend=None, hardware=None):
    if confirm_visible_gui is not True:
        raise ValueError("explicit --confirm-visible-gui required; initial blank state is not inferred")
    if type(cycles) is not int or not 1 <= cycles <= 3:
        raise ValueError("one to three capture cycles required")
    output = validate_output(output)
    backend, hardware = backend or GuiBackend(), hardware or capture_repeat.Hardware()
    inspected = backend.inspect()
    if inspected["name"] != "mesondrmfb":
        raise ValueError("unsupported framebuffer backend; exact mesondrmfb required")
    initial = hardware.snapshot()
    # Retain a record even if capture_repeat cannot create its own directory.
    output.mkdir(parents=True, exist_ok=False)
    record = {"schema": "yblod.clean-capture.v1", "status": "incomplete",
              "operation": "temporarily hide mesondrmfb framebuffer GUI plane",
              "backend": inspected, "hide_value": 1, "restore_value": 0,
              "initial_state_basis": "operator explicitly confirmed GUI visibly present; not inferred from blank readback",
              "operator_confirmed_visible_gui": True,
              "source_basis": "reviewed drivers/drm/meson_fbdev.c am_meson_drm_fb_blank handler; framebuffer-plane disable/enable, not a video precision control",
              "video_precision_settings_changed": False, "playback_commands_sent": False,
              "hide_write_attempted": False, "hide_write_completed": False,
              "gui_restore_write_attempted": False, "gui_restore_write_completed": False,
              "restoration_scope": "write completion only; no independent hardware/register readback or post-restore visual verification",
              "capture_directory": "capture", "initial_paused_state": initial,
              "allow_unverified_dma_sync": allow_unverified_dma_sync,
              "implementation_sha256": source_hash(__file__),
              "capture_repeat_sha256": source_hash(capture_repeat.__file__),
              "python_version": sys.version,
              "limitations": ["Caller must visually verify the captured picture has no GUI overlay.",
                              "Hide/restore writes do not independently prove actual plane state.",
                              "Process kill, power loss or repeated interruption can prevent restoration."]}
    errors = []
    try:
        # A failed write can be partial; restoration is attempted in that case too.
        record["hide_write_attempted"] = True
        backend.write(1)
        record["hide_write_completed"] = True
        time.sleep(1)
        after_hide = hardware.snapshot()
        capture_repeat.same_picture(initial, after_hide)
        record["paused_state_after_hide"] = after_hide
        captured = capture_repeat.run(output / "capture", cycles=cycles, hardware=hardware,
                                      allow_unverified_dma_sync=allow_unverified_dma_sync)
        record["capture_status"] = captured["status"]
        record["capture_cleanup"] = captured.get("cleanup", {})
        if captured["status"] != "complete":
            errors.append("capture failed: " + captured.get("error", "no error detail"))
    except BaseException as failure:
        errors.append(f"{type(failure).__name__}: {failure}")
    finally:
        if record["hide_write_attempted"]:
            record["gui_restore_write_attempted"] = True
            try:
                backend.write(0)
                record["gui_restore_write_completed"] = True
            except BaseException as failure:
                record["restore_error"] = f"{type(failure).__name__}: {failure}"
                errors.append("GUI restoration failed: " + record["restore_error"])
        record["status"] = "failed" if errors else "complete"
        if errors:
            record["errors"] = errors
        with (output / "gui-plane-orchestration.json").open("x") as target:
            json.dump(record, target, indent=2)
            target.write("\n")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--confirm-visible-gui", action="store_true", required=True,
                        help="confirm by observation that GUI is initially visible; establishes restore-to-visible basis")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--allow-unverified-dma-sync", action="store_true",
                        help="allow missing driver dump; stable reads cannot rule out stale cached data")
    args = parser.parse_args(argv)
    def interrupted(number, _frame):
        raise RuntimeError(f"capture interrupted by signal {number}")
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), interrupted)
    try:
        record = run(args.output, confirm_visible_gui=args.confirm_visible_gui,
                     cycles=args.cycles, allow_unverified_dma_sync=args.allow_unverified_dma_sync)
    except (OSError, ValueError) as failure:
        parser.exit(1, f"clean capture: {failure}\n")
    print(json.dumps({"directory": str(args.output), "status": record["status"],
                      "gui_restore_write_completed": record["gui_restore_write_completed"]}), flush=True)
    if record["status"] != "complete":
        parser.exit(1, "; ".join(record["errors"])+"\n")


if __name__ == "__main__":
    main()
