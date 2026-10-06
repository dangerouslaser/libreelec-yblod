"""Sanitized uniform-candidate evidence; excludes raw files and media hashes."""
import json
from pathlib import Path
import statistics
import sys
from collect_libplacebo_checkpoint import record


if __name__ == "__main__":
    public, private, sequence = map(Path, sys.argv[1:4])
    measured = {directory.name: record(directory) for directory in sorted(private.iterdir()) if directory.is_dir()}
    a = [value for name in ("LA1", "LA2") for value in measured[name]["wall_ns"]]
    b = [value for name in ("LB1", "LB2") for value in measured[name]["wall_ns"]]
    data = {
        "schema": "yblod.libplacebo-uniform-qualification.v1",
        "status": "standalone-hybrid-not-adopted-in-Kodi",
        "reference": "native-integer-model-not-SK4-or-Dolby-conformance",
        "libplacebo": "7.372.0/e2972fdd09adacd383656738d7d280f0cd84a761 plus repository patches",
        "domain": "input/pivots code/1024; customized output-range control matches native Q16 limits",
        "longer_abba": {
            "order": ["LA1", "LB1", "LB2", "LA2"],
            "warmups": 8, "samples_per_run": 12,
            "native_pooled_median_ms": statistics.median(a) / 1e6,
            "candidate_pooled_median_ms": statistics.median(b) / 1e6,
            "median_wall_reduction_percent": 100 * (1 - statistics.median(b) / statistics.median(a)),
            "scope": "resident composer submit/finish including CPU uniform preparation/upload; not playback",
        },
        "public_cases": {directory.name: record(directory) for directory in sorted(public.iterdir()) if directory.is_dir()},
        "private_4k_aggregate_records_only": measured,
        "same_context_sequence": record(sequence),
        "limitations": [
            "One real 4K frame, not broad metadata/frame coverage.",
            "Topology changes require regeneration and production cache/fallback handling is not implemented.",
            "Default upstream mapped-pivot limits differ from customized native-range control.",
            "No new-frame upload/scaling/colour/display/decode/compilation cost is included in warm timings.",
            "No private layers, instructions, shader literals or media hashes are published.",
            "Whole-scope CPU/resource snapshots are not exclusive timing-window measurements.",
        ],
    }
    json.dump(data, sys.stdout, indent=2)
    print()
