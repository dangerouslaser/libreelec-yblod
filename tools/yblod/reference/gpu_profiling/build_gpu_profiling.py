#!/usr/bin/env python3
"""Build isolated, content-pinned diagnostic executables; never modify the engine."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine_repo", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    root = args.engine_repo.resolve(strict=True)
    out = args.output_dir.resolve()
    if out == root or out.is_relative_to(root / "engine"):
        parser.error("output must not overwrite the canonical engine directory")
    here = Path(__file__).resolve().parent
    exp = root / "engine/experimental"
    pins = json.loads((here / "source-pins.json").read_text())
    for name, expected in pins["content_hashes"].items():
        data = (exp / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise SystemExit(f"source pin mismatch: {name}; review/rebase diagnostics first")
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="profiling-source-", dir=out))
    for name in pins["content_hashes"]:
        shutil.copyfile(exp / name, work / name)
    shutil.copyfile(exp / "native_gpu_composer_fp32_backend.c", work / "native_gpu_composer_fp32_backend.c")
    for name in ("native_gpu_diag_timer.h", "native_gpu_diag_timer_records.c",
                 "native_gpu_diag_workgroup.h", "test_gpu_diag_timer.c",
                 "test_gpu_diag_workgroup.c", "native_gpu_ycc_frame_timer_probe.c"):
        shutil.copyfile(here / name, work / name)
    subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-d", str(work),
                    "-i", str(here / "backend-diagnostics.patch")], check=True)
    print(f"Diagnostic sources: {work}", flush=True)
    if args.prepare_only:
        return
    cc = shlex.split(os.environ.get("CC", "cc"))
    flags = ["-std=c11", "-O2", "-fno-lto", "-Wall", "-Wextra", "-Werror",
             "-Wconversion", "-Wshadow", "-fno-fast-math", "-ffp-contract=off"]
    common = cc + shlex.split(os.environ.get("CPPFLAGS", "")) + flags + [
        "-I" + str(work), "-I" + str(exp), "-I" + str(root / "engine/include")]
    ldflags = shlex.split(os.environ.get("LDFLAGS", ""))
    targets = {
        "test-gpu-diag-timer": ([work / "test_gpu_diag_timer.c"], []),
        "test-gpu-diag-workgroup": ([work / "test_gpu_diag_workgroup.c"], []),
        "ycc-frame-timer-probe": ([work / "native_gpu_ycc_frame_timer_probe.c",
            work / "native_gpu_ycc_backend.c", work / "native_gpu_diag_timer_records.c"], ["-lEGL"]),
        "fp32-timer-compare-probe": ([work / "native_gpu_composer_fp32_compare_probe.c",
            work / "native_gpu_composer_backend.c", work / "native_gpu_composer_fp32_backend.c",
            work / "native_gpu_diag_timer_records.c"] + [exp / n for n in (
            "native_gpu_composer_fp32.c", "native_libplacebo_reshape.c", "native_gpu_guard.c",
            "native_scaled_surface.c", "native_decoder_frame_bridge.c", "native_mmr_composer.c",
            "native_integration_probe.c", "native_sampling_probe.c")] + [root / "engine/src/native_composer.c"],
            ["-lplacebo", "-lEGL", "-lm"]),
    }
    for name, (sources, libraries) in targets.items():
        destination = work / name
        subprocess.run(common + [str(p) for p in sources] + ["-o", str(destination)] + ldflags + libraries, check=True)
        print(f"{name}: {hashlib.sha256(destination.read_bytes()).hexdigest()}", flush=True)


if __name__ == "__main__":
    main()
