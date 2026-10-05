#!/usr/bin/env python3
"""Private orchestration: temporarily hide a previously visible Kodi GUI plane.

Not a precision/Dolby setting. Keep video paused, restore GUI in finally.
The blank attribute has no readable initial state on this device; unblank=0
restores the empirically visible initial GUI, not a read-back register state.
"""
import importlib.util
import json
from pathlib import Path
import sys
import time

spec = importlib.util.spec_from_file_location("capture_repeat", "/storage/capture_repeat_20261005.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)
output = Path(sys.argv[1])
control = Path("/sys/class/graphics/fb0/blank")
record = {"operation": "temporarily hide Kodi framebuffer GUI plane only", "control": str(control),
          "initial_state_basis": "Kodi paused GUI visibly present in prior capture; blank attr read is empty",
          "hide_value": 1, "restore_value": 0, "video_precision_settings_changed": False,
          "gui_restore_write_completed": False}
initial = capture.Hardware().snapshot()
try:
    control.write_text("1\n")
    record["hide_write_completed"] = True
    time.sleep(1)
    capture.same_picture(initial, capture.Hardware().snapshot())
    report = capture.run(output, cycles=3, allow_unverified_dma_sync=True)
finally:
    control.write_text("0\n")
    record["gui_restore_write_completed"] = True
    record["restoration_scope"] = "write completed; source-reviewed enable action, no independent register readback"
    if output.exists():
        with (output / "gui-plane-orchestration.json").open("x") as handle:
            json.dump(record, handle, indent=2)
            handle.write("\n")
print(json.dumps({"directory": str(output), "status": report["status"], "gui_restored": True}))
if report["status"] != "complete":
    raise SystemExit(report.get("error", "capture failed"))
