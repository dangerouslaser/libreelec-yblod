"""Emit sanitized measured checkpoint JSON; never emit media paths or hashes."""
import json
from pathlib import Path
import statistics
import sys


def fields(path):
    return {line.split()[0]: int(line.split()[1]) for line in path.read_text().splitlines()}


def record(directory):
    result = json.loads((directory / "result.json").read_text())
    assert result["status"] == "complete" and result["all_output_codes_compared"]
    assert result["cleanup_succeeded"] and result["cpu_full_frame_gate"]
    assert (directory / "before-hashes.txt").read_bytes() == (directory / "after-hashes.txt").read_bytes()
    assert (directory / "before-kodi-startticks.txt").read_bytes() == (directory / "after-kodi-startticks.txt").read_bytes()
    events = fields(directory / "after-memory.events")
    assert all(value == 0 for value in events.values())
    assert int((directory / "after-memory.swap.current").read_text()) == 0
    result["median_wall_ms"] = statistics.median(result["wall_ns"]) / 1e6
    result["resource_snapshot"] = {
        "memory_max_bytes": int((directory / "after-memory.max").read_text()),
        "memory_peak_bytes_before_wrapper_exit": int((directory / "after-memory.peak").read_text()),
        "memory_events": events,
        "swap_bytes": 0,
        "cpu_stat": fields(directory / "after-cpu.stat"),
        "software_hashes_and_kodi_service_start_unchanged": True,
    }
    return result


if __name__ == "__main__":
    public = Path(sys.argv[1])
    private = Path(sys.argv[2])
    data = {
        "schema": "yblod.libplacebo-reshape-checkpoint.v1",
        "status": "experiment-not-adopted",
        "reference": "native-integer-composer-not-licensed-hardware",
        "libplacebo": "7.372.0/e2972fdd09adacd383656738d7d280f0cd84a761 plus repository patches",
        "pixel_input_and_pivot_domain": "native 10-bit code / 1024; not default libplacebo / 1023",
        "unchanged": ["sampling", "integer NLQ", "final quantization", "production Kodi"],
        "public_cases": {d.name: record(d) for d in sorted(public.iterdir()) if d.is_dir()},
        "private_4k_frame_aggregate_only": {d.name: record(d) for d in sorted(private.iterdir()) if d.is_dir()},
        "limitations": [
            "Resident uploaded diagnostic textures, not live VA-API playback.",
            "Constant-coefficient candidate permits compile-time optimization.",
            "Runtime R1 initializes decoded coefficient arrays per pixel; conservative nonoptimized adapter.",
            "Compilation, new-frame preparation, scaling, colour conversion and display excluded from warm timing.",
            "Output-pivot clamp differs from native output limits; not a float-precision-only comparison.",
            "No film pixels, RPU payloads, private shader literals, or media hashes are published.",
        ],
    }
    json.dump(data, sys.stdout, indent=2)
    print()
