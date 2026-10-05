"""Sequential local VA probe runner; no SSH, tuning, clamps or media frames."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time

import hardware_scaling_vectors as vectors
import scaling_oracle
import scaling_probe

FLAGS = {"default": 0, "fast": 256, "hq": 512}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _verified_bundle(bundle):
    manifest = json.loads((bundle/"hardware-probes.json").read_bytes())
    width, height = manifest["input_size"]
    vectors.dimensions(width, height)
    if width > 128 or height > 128:
        raise ValueError("synthetic runner limits inputs to 128x128")
    expected = manifest["expected_included"]
    if type(expected) is not bool:
        raise ValueError("expected_included must be a boolean")
    # Regenerate a complete canonical contract, including current source pins
    # and optional expectations. Do not trust a self-consistent tampered hash.
    with tempfile.TemporaryDirectory() as temp:
        canonical_root = Path(temp)/"canonical"
        canonical = vectors.generate(canonical_root, width, height, expected)
        if manifest != canonical:
            raise ValueError("bundle contract differs from canonical current sources")
        for case in canonical["cases"].values():
            records = [case["input"]]+list(case.get("expected", {}).values())
            for record in records:
                data = (bundle/record["file"]).read_bytes()
                if (len(data) != record["bytes"] or sha(data) != record["sha256"]
                        or data != (canonical_root/record["file"]).read_bytes()):
                    raise ValueError("bundle file differs from canonical bytes")
    return manifest, vectors.patterns(width, height)


def _invocation(stdout, input_size, output_size, mode):
    value = json.loads(stdout)
    copy = mode == "copy"
    required = {"schema": "yblod.vaapi-scaler-invocation.v1", "status": "complete",
                "input_size": input_size, "output_size": output_size,
                "filter_flags": 0 if copy else FLAGS[mode],
                "input_chroma_siting": None if copy else 6,
                "output_chroma_siting": None if copy else 6,
                "colour_standard": None if copy else 12,
                "colour_range": None if copy else 2,
                "vpp_submitted": not copy, "hardware_engine_verified": False}
    for key, expected in required.items():
        actual = value.get(key)
        if actual != expected or type(actual) is not type(expected):
            raise ValueError(f"invalid invocation declaration: {key}")
    if not isinstance(value.get("vendor"), str) or not value["vendor"].strip():
        raise ValueError("missing VA vendor")
    version = value.get("va_version")
    if not isinstance(version, list) or len(version) != 2 or any(type(v) is not int or v < 0 for v in version):
        raise ValueError("missing VA version")
    return value


def run(binary, bundle, destination, modes=("default", "fast", "hq"), repeats=2,
        *, device="/dev/dri/renderD128"):
    """Return report; failures retain evidence and never report completion.

    A fresh destination is mandatory. Copies and 1:1 VPP ALL must pass before
    ANY scaling. Each subprocess has a 30-second timeout and runs sequentially.
    """
    root = Path(destination).resolve()
    root.mkdir(exist_ok=False)
    started = time.monotonic()
    before_self = resource.getrusage(resource.RUSAGE_SELF)
    before_child = resource.getrusage(resource.RUSAGE_CHILDREN)
    uname = os.uname()
    report = {"schema": "yblod.hardware-el-scaling-run.v1", "status": "failed",
              "hardware_engine_verified": False, "invocations": [], "scaling": {},
              "kernel": dict(zip(("system", "node", "release", "version", "machine"), uname)),
              "device": str(device),
              "runner_sha256": sha(Path(__file__).read_bytes()),
              "vectors_sha256": sha(Path(vectors.__file__).read_bytes()),
              "oracle_sha256": sha(Path(scaling_oracle.__file__).read_bytes()),
              "transport_sha256": sha(Path(scaling_probe.__file__).read_bytes())}

    def call(name, stage, mode, input_size, output_size, repetition=0):
        stem = f"{stage}-{mode}-{name}-{repetition}"
        output = root/f"{stem}.p010"
        argv = [str(executable), str(device), str(bundle_root/manifest["cases"][name]["input"]["file"]),
                str(output), *map(str, input_size), *map(str, output_size), mode]
        entry = {"stage": stage, "mode": mode, "pattern": name,
                 "repetition": repetition, "argv": argv, "output_file": output.name}
        report["invocations"].append(entry)
        try:
            result = subprocess.run(argv, capture_output=True, timeout=30, check=False)
            stdout, stderr = result.stdout, result.stderr
            entry["exit_status"] = result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            entry.update(exit_status=None, timed_out=True)
        except OSError as error:
            stdout, stderr = b"", str(error).encode()
            entry.update(exit_status=None, spawn_error=type(error).__name__)
        # Capture exact output bytes before interpreting them.
        for kind, data in (("stdout", stdout), ("stderr", stderr)):
            path = root/f"{stem}.{kind}.log"
            with path.open("xb") as handle:
                handle.write(data)
            entry[kind] = {"file": path.name, "bytes": len(data), "sha256": sha(data)}
        if output.exists():
            entry["output_sha256"] = sha(output.read_bytes())
        if entry["exit_status"] != 0:
            raise ValueError(f"probe failed or timed out: {stem}")
        entry["invocation"] = _invocation(stdout, input_size, output_size, mode)
        data = output.read_bytes()
        # Strict P010 layout/low-bit checks occur inside both scorers.
        return data, entry

    try:
        if isinstance(modes, (str, bytes)):
            raise ValueError("modes must be a sequence, not a string")
        modes = tuple(modes)
        if not modes or len(set(modes)) != len(modes) or any(m not in FLAGS for m in modes):
            raise ValueError("select unique supported modes default, fast, hq")
        if type(repeats) is not int or not 2 <= repeats <= 10:
            raise ValueError("between 2 and 10 repeats required for stability")
        executable, bundle_root = Path(binary).resolve(), Path(bundle).resolve()
        report.update(binary=str(executable), binary_sha256=sha(executable.read_bytes()),
                      modes=list(modes), repeats=repeats,
                      probe_manifest_sha256=sha((bundle_root/"hardware-probes.json").read_bytes()))
        manifest, inputs = _verified_bundle(bundle_root)
        size = manifest["input_size"]
        report.update(input_size=size, output_size=manifest["output_size"])
        for stage, mode in (("copy", "copy"), ("identity-vpp", "default")):
            for name, planes in inputs.items():
                data, entry = call(name, stage, mode, size, size)
                entry["identity"] = vectors.check_identity(planes, data)
                if not entry["identity"]["exact"]:
                    raise ValueError(f"native-code identity failed: {stage}/{name}")
        report["identity_checks_complete"] = True
        score_cache = {}
        for mode in modes:
            cases = report["scaling"].setdefault(mode, {})
            for name, planes in inputs.items():
                first, hashes = None, []
                for repetition in range(repeats):
                    data, entry = call(name, "scale", mode, size, manifest["output_size"], repetition)
                    # Check every repetition for invalid low bits even if data
                    # is unstable; no silent conversion or repair is allowed.
                    from scaling_probe import unpack_p010
                    unpack_p010(data, *manifest["output_size"])
                    hashes.append(sha(data))
                    if first is None:
                        first = data
                cache_key = (manifest["cases"][name]["input"]["sha256"], hashes[0])
                if cache_key not in score_cache:
                    score_cache[cache_key] = vectors.score_scaled(planes, first)
                result = copy.deepcopy(score_cache[cache_key])
                result.update(repeat_sha256=hashes, repeat_stable=len(set(hashes)) == 1)
                cases[name] = result
                if not result["repeat_stable"]:
                    raise ValueError(f"unstable repeated scaling: {mode}/{name}")
        report["status"] = "complete"
        report["interpretation"] = "stable native-code probe results, not certified Dolby accuracy or verified hardware-engine routing"
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    after_self = resource.getrusage(resource.RUSAGE_SELF)
    after_child = resource.getrusage(resource.RUSAGE_CHILDREN)
    report["resources"] = {"elapsed_seconds": time.monotonic()-started,
                           "self_peak_rss_native": after_self.ru_maxrss,
                           "children_peak_rss_native": after_child.ru_maxrss,
                           "rss_native_unit": "bytes" if sys.platform == "darwin" else "KiB",
                           "self_swap_delta": after_self.ru_nswap-before_self.ru_nswap,
                           "children_swap_delta": after_child.ru_nswap-before_child.ru_nswap,
                           "interpretation": "process lifetime high-water RSS; run elapsed includes CPU reference and subprocesses, not playback performance"}
    with (root/"run-report.json").open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--modes", nargs="+", default=list(FLAGS), choices=list(FLAGS))
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--device", default="/dev/dri/renderD128")
    args = parser.parse_args()
    result = run(args.binary, args.bundle, args.destination, args.modes, args.repeats, device=args.device)
    raise SystemExit(0 if result["status"] == "complete" else 1)
