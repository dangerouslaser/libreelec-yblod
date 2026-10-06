#!/usr/bin/env python3
"""Verify canonical source pins and apply private diagnostic copies only."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

PINS = {
    "native_gpu_composer_backend_libplacebo.c": "01567f78f07df4732e44fb5a1cb5bd25d80a7553ff683e84af9f6c3e97386439",
    "native_gpu_composer_fp32.c": "5309ab1f5c9f1886763f03a0ee2ce9899846d06db072dc175b915dc0d90a5528",
    "native_gpu_composer_fp32_compare_probe.c": "52c7511dae03261a444a6ccb836c1d47df42c81e694286480e6b09487850af96",
}
def main():
    if len(sys.argv) != 3: raise SystemExit("usage: stage_diagnostic.py REPO FRESH_OUTPUT")
    source = Path(sys.argv[1]).resolve()/"engine"/"experimental"
    output = Path(sys.argv[2]).resolve(); output.mkdir(exist_ok=False)
    package = Path(__file__).resolve().parent
    for name, expected in PINS.items():
        data = (source/name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected: raise SystemExit("canonical source pin mismatch: "+name)
        (output/name).write_bytes(data)
    shutil.copyfile(source/"native_gpu_composer_fp32_backend.c", output/"native_gpu_composer_fp32_backend.c")
    for name in ("native_gpu_diag_nlq_lut.h", "native_gpu_diag_nlq_lut.c", "test_native_gpu_diag_nlq_lut.c",
                 "build_nlq_lut_diagnostic.sh", "run_nlq_lut_guard.py", "prepare_nlq_lut_guard_config.py", "test_nlq_lut_guard.py"):
        shutil.copyfile(package/name, output/name)
    subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(package/"diagnostic.patch")], cwd=output, check=True)
    print("Pinned diagnostic copies staged; canonical repository unchanged.")
if __name__ == "__main__": main()
