#!/usr/bin/env python3
"""Private 4K fixture guard. Run inside fresh 512MiB/no-swap/one-CPU service."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import urllib.request

ROLES = ("binary", "shader", "instructions", "bl_y", "bl_cb", "bl_cr", "guide", "p010")
SIZES = {"instructions": 9216, "bl_y": 16588800, "bl_cb": 4147200,
         "bl_cr": 4147200, "guide": 4147200, "p010": 24883200}
LIBRARIES = ("/usr/lib/libplacebo.so.372", "/usr/lib/libEGL.so.1", "/usr/lib/libEGL_mesa.so.0",
             "/usr/lib/libGLdispatch.so.0", "/usr/lib/libgallium-26.2.4.so",
             "/usr/lib/libgbm.so.1", "/usr/lib/libdrm.so.2", "/usr/lib/libm.so.6",
             "/usr/lib/libc.so.6", "/usr/lib/ld-linux-x86-64.so.2")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            data = stream.read(65536)
            if not data:
                break
            value.update(data)
    return value.hexdigest()


def proc_identity(pid):
    process = Path("/proc") / str(pid)
    fields = (process / "stat").read_text().rsplit(")", 1)[1].split()
    require(fields[0] != "Z", "zombie process")
    return dict(pid=pid, start_ticks=int(fields[19]), executable=os.readlink(process / "exe"),
                executable_sha256=digest(process / "exe"))


def check_kodi_state(service, wrapper, processes, expected):
    require(expected in ("active", "inactive") and service == expected, "Kodi service state differs from requested mode")
    if expected == "inactive":
        require(wrapper == 0 and not processes, "inactive Kodi requires MainPID0 and no actual kodi.bin")
    else:
        require(wrapper > 0 and len(processes) == 1, "active Kodi requires service PID and one actual kodi.bin")


def kodi_identity(expected="active"):
    service = subprocess.check_output(["systemctl", "show", "kodi", "-p", "ActiveState", "--value"], text=True).strip()
    wrapper = int(subprocess.check_output(["systemctl", "show", "kodi", "-p", "MainPID", "--value"], text=True))
    processes = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if (process / "comm").read_text().strip() == "kodi.bin":
                processes.append(proc_identity(int(process.name)))
        except FileNotFoundError:
            continue
    check_kodi_state(service, wrapper, processes, expected)
    if expected == "inactive":
        return dict(mode=expected, service_state=service, main_pid=0, actual_kodi_bin_count=0,
                    identity_scope="intentionally inactive service; no process identity or RPC idle claim")
    return dict(mode=expected, service_state=service, main_pid=wrapper, actual_kodi_bin_count=1,
                wrapper=proc_identity(wrapper), kodi_bin=processes[0])


def idle_players():
    payload = json.dumps(dict(jsonrpc="2.0", method="Player.GetActivePlayers", id=1)).encode()
    request = urllib.request.Request("http://127.0.0.1:8080/jsonrpc", payload,
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.load(response)
    require(result.get("result") == [] and "error" not in result, "Kodi playback active or RPC unavailable")
    return result


def player_state(expected):
    if expected == "inactive":
        return dict(queried=False, reason="Kodi intentionally inactive; no RPC idle assertion")
    return idle_players()


def cgroup_path():
    rows = [line.split(":", 2) for line in Path("/proc/self/cgroup").read_text().splitlines()]
    groups = [row[2] for row in rows if row[0] == "0"]
    require(len(groups) == 1 and groups[0].startswith("/"), "unified cgroup required")
    return Path("/sys/fs/cgroup") / groups[0].lstrip("/")


def resources(group):
    fields = ("memory.max", "memory.peak", "memory.events", "memory.swap.current", "memory.swap.max", "cpu.max", "cpu.stat")
    result = {name: (group / name).read_text().strip() for name in fields}
    require(result["memory.max"] == "536870912", "512MiB memory cap required")
    require(result["memory.swap.max"] == "0" and result["memory.swap.current"] == "0", "no extra swap required")
    require(all(int(line.split()[1]) == 0 for line in result["memory.events"].splitlines()), "memory pressure/OOM events")
    quota, period = result["cpu.max"].split()
    require(quota != "max" and 0 < int(quota) <= int(period), "at most one CPU quota required")
    return result


def artifact_snapshot(config):
    output = {}
    for name, entry in config["artifacts"].items():
        path = Path(entry["path"])
        require(path.is_absolute() and not path.is_symlink(), "absolute regular artifacts required")
        state = path.stat()
        require(stat.S_ISREG(state.st_mode) and not state.st_mode & 0o022, "non-writable regular artifact required")
        require(re.fullmatch("[0-9a-f]{64}", entry["sha256"]) is not None and digest(path) == entry["sha256"], "artifact pin differs")
        if name in SIZES:
            require(state.st_size == SIZES[name], "4K artifact extent differs")
        output[name] = dict(path=str(path), sha256=entry["sha256"], device=state.st_dev, inode=state.st_ino,
                            bytes=state.st_size, mtime_ns=state.st_mtime_ns, ctime_ns=state.st_ctime_ns)
    for entry in config["libraries"]:
        path = Path(entry["path"])
        require(str(path) in LIBRARIES and path.is_file(), "unexpected or missing qualified library")
        require(digest(path) == entry["sha256"], "library pin differs")
        state = path.stat()
        output[str(path)] = dict(resolved=str(path.resolve()), sha256=entry["sha256"], inode=state.st_ino,
                                 device=state.st_dev, bytes=state.st_size, mtime_ns=state.st_mtime_ns, ctime_ns=state.st_ctime_ns)
    return output


def validate_result(record, lut, sequence, warmups=8, samples=12, frequency=False):
    require(type(warmups) is int and type(samples) is int and 1 <= warmups <= 32 and 1 <= samples <= 32 and (not sequence or warmups >= 2), "bounded iteration configuration required")
    submits = 1 + warmups + samples
    require(record["schema"] == "yblod.native-gpu-composer-compare-probe.v1" and record["status"] == "complete", "probe incomplete")
    for flag in ("gpu_attempted", "cpu_full_frame_gate", "device_binding_verified", "cleanup_succeeded",
                 "fp32_selected", "all_output_codes_compared", "whole_frame_resident"):
        require(record[flag] is True, "required output/route/cleanup gate failed: " + flag)
    require(record["observed_gl_error"] == 0 and record["observed_egl_error"] == 12288, "GL/EGL error")
    require(record["backend_route"] == "actual-playback-fp32-wrapper", "wrong composer route")
    counts = [8294400, 2073600, 2073600]
    require(record["counts"] == counts and record["output_depth"] == 12, "wrong 4K plane geometry/depth")
    oracles = 3 if sequence else 1
    require(record["nlq_lut_metadata_sequence"] is sequence and record["nlq_lut_gpu_full_frame_oracles"] == oracles, "metadata oracle sequence differs")
    require(record["gpu_verified_output_planes"] == 3 * oracles and record["gpu_verified_reconstructed_values"] == sum(counts) * oracles, "incomplete full-frame GPU oracle")
    require(record["cpu_chunk_samples"] == 65536, "unexpected CPU oracle chunk extent")
    chunk = record["cpu_chunk_samples"]
    require(record["gpu_oracle_dispatches"] == sum((count + chunk - 1) // chunk for count in counts) * oracles, "incomplete CPU reference dispatches")
    require(record["nlq_lut_restored_a_bit_exact"] is sequence and record["nlq_lut_restored_a_values"] == (sum(counts) if sequence else 0), "restored A differs from original GPU output")
    require(record["raw_dump_scope"] == "original-A-only", "dump metadata scope differs")
    require(record["warmups"] == warmups and record["samples"] == samples, "sample configuration differs")
    route = record["route_stats"]
    require(route["accepted_fp32"] == submits and route["accepted_integer"] == 0 and route["cache_misses"] == 1 and route["cache_hits"] == submits - 1,
            "requested FP32 route not selected throughout")
    require(route["shader_compile_failed"] == 0 and route["generate_failed"] == 0, "shader generation/compile failure")
    require(record["nlq_lut_options_api"] is True and record["nlq_lut_stats_version"] == 1, "explicit playback options API not qualified")
    require(record["nlq_lut_accepted_frames"] == (submits if lut else 0), "actual accepted LUT route differs")
    require(record["nlq_lut_requested"] is bool(lut), "LUT flag differs")
    for key in ("nlq_lut_compiled_shaders", "nlq_lut_builds", "nlq_lut_cache_hits", "nlq_lut_uploads"):
        expected = (1 if key == "nlq_lut_compiled_shaders" else (submits - oracles if key == "nlq_lut_cache_hits" else oracles)) if lut else 0
        require(type(record[key]) is int and record[key] == expected, "LUT route/cache/upload assertion failed: " + key)
    require(record["nlq_lut_bytes_per_table"] == 12288 and record["nlq_lut_entries_per_table"] == 3072, "LUT ABI differs")
    require(len(record["difference_metrics"]) == 3, "plane metrics absent")
    for c, metrics in enumerate(record["difference_metrics"]):
        require(metrics["plane"] == c and metrics["count"] == counts[c] * oracles and metrics["over_one"] == 0 and metrics["max_abs"] <= 1,
                "FP32/integer oracle exceeds qualified one-code bound")
    for key in ("wall_ns", "cpu_ns"):
        require(len(record[key]) == samples and all(type(v) is int and v > 0 for v in record[key]), "invalid host timing samples")
    require(record["dispatch_timing_is_device_kernel_time"] is False and "gpu_elapsed_ns" not in record, "unsupported GPU-exclusive timing")
    require(record["raw_dump_requested"] is True and record["raw_dump_format"] == "u16le-native-grid-Y-then-Cb-then-Cr-no-padding", "missing original-A output dump")
    if frequency or "gpu_frequency_requested" in record:
        require(record["gpu_frequency_requested"] is frequency, "frequency observation mode differs")
        observations=record["gpu_frequency_samples"]
        require(len(observations)==(samples if frequency else 0), "frequency sample count differs")
        if frequency:
            require(record["gpu_frequency_device_verified"] is True, "frequency card0 differs from bound render device")
            fields={"before_act_mhz","before_cur_mhz","after_act_mhz","after_cur_mhz"}
            require(all(set(item)==fields and all(type(v) is int and -1<=v<=10000 for v in item.values()) for item in observations), "invalid frequency observations")


def main():
    require(len(sys.argv) == 4, "usage: guard TASK_DIR PRIVATE_CONFIG EXPECTED_CONFIG_SHA256")
    job = Path(sys.argv[1]); config_path = Path(sys.argv[2])
    require(job.is_absolute() and config_path.is_absolute(), "absolute paths required")
    require(not job.is_symlink() and not config_path.is_symlink() and config_path.is_file(), "regular job/config paths required")
    state = job.stat()
    require(stat.S_ISDIR(state.st_mode) and state.st_uid == os.geteuid() and not state.st_mode & 0o077 and not any(job.iterdir()), "fresh owned0700 private job directory required")
    require(re.fullmatch("[0-9a-f]{64}", sys.argv[3]) is not None and digest(config_path) == sys.argv[3], "private config pin differs")
    config = json.loads(config_path.read_text())
    require(config["schema"] == "yblod.nlq-lut-playback-options-private-guard.v1" and set(config["artifacts"]) == set(ROLES), "guard config schema/roles differ")
    require(type(config["lut_mode"]) is int and config["lut_mode"] in (0, 1) and type(config["metadata_sequence"]) is bool, "invalid LUT/sequence flags")
    warmups=config.get("warmups",8); samples=config.get("samples",12)
    frequency=config.get("frequency",False); require(type(frequency) is bool, "frequency option must be boolean")
    kodi_state=config.get("kodi_state","active"); require(type(kodi_state) is str and kodi_state in ("active","inactive"), "Kodi state must be active or inactive")
    require(type(warmups) is int and type(samples) is int and 1 <= warmups <= 32 and 1 <= samples <= 32 and (not config["metadata_sequence"] or warmups >= 2), "bounded iteration configuration required")
    require({item["path"] for item in config["libraries"]} == set(LIBRARIES) and len(config["libraries"]) == len(LIBRARIES), "exact qualified library pins required")
    for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "MESA_LOADER_DRIVER_OVERRIDE", "LIBGL_ALWAYS_SOFTWARE", "YB_VALIDATE_ONLY",
                 "INTEL_DEBUG", "INTEL_SIMD_DEBUG", "MESA_GLSL", "MESA_DEBUG",
                 "INTEL_SHADER_ASM_READ_PATH", "INTEL_SHADER_OPTIMIZER_PATH",
                 "INTEL_SHADER_BIN_DUMP_PATH", "INTEL_SHADER_DUMP_FILTER", "MESA_SHADER_CACHE_DISABLE"):
        require(not os.environ.get(name), "unqualified environment: " + name)
    node = Path("/dev/dri/renderD128"); require(not node.is_symlink(), "render node symlink")
    device = node.stat(); require(stat.S_ISCHR(device.st_mode) and os.major(device.st_rdev) == 226 and os.minor(device.st_rdev) == 128, "render node identity differs")
    os.umask(0o077)
    group = cgroup_path()
    before = dict(resources=resources(group), artifacts=artifact_snapshot(config), kodi=kodi_identity(kodi_state), idle_players=player_state(kodi_state),
                  config_sha256=sys.argv[3], guard_sha256=digest(__file__))
    (job / "before.json").write_text(json.dumps(before, indent=2, sort_keys=True))
    environment = os.environ.copy()
    environment.update(YB_GPU_DIAG_TIMER="0", YB_GPU_DIAG_NLQ_LUT=str(config["lut_mode"]),
                       YB_GPU_DIAG_NLQ_LUT_SEQUENCE="1" if config["metadata_sequence"] else "0",
                       YB_GPU_DIAG_FREQUENCY="1" if frequency else "0",
                       YB_COMPARE_WARMUPS=str(warmups), YB_COMPARE_SAMPLES=str(samples))
    artifact = config["artifacts"]
    command = [artifact["binary"]["path"], str(node), artifact["shader"]["path"], "3840", "2160"] + [artifact[key]["path"] for key in ROLES[2:]] + [str(job / "output.u16le")]
    with (job / "result.json").open("x") as output, (job / "stderr.txt").open("x") as error:
        result = subprocess.run(command, env=environment, stdout=output, stderr=error, check=False)
    (job / "probe-exit.txt").write_text(str(result.returncode) + "\n")
    after = dict(resources=resources(group), artifacts=artifact_snapshot(config), kodi=kodi_identity(kodi_state), idle_players=player_state(kodi_state),
                 config_sha256=digest(config_path), guard_sha256=digest(__file__))
    (job / "after.json").write_text(json.dumps(after, indent=2, sort_keys=True))
    require(result.returncode == 0, "probe exit failed; inspect private stderr")
    for key in ("artifacts", "kodi", "config_sha256", "guard_sha256"):
        require(before[key] == after[key], "before/after identity/pin differs: " + key)
    for key in ("memory.max", "memory.swap.max", "cpu.max"):
        require(before["resources"][key] == after["resources"][key], "resource cap changed")
    record = json.loads((job / "result.json").read_text())
    validate_result(record, config["lut_mode"], config["metadata_sequence"], warmups, samples, frequency)
    dump = job / "output.u16le"
    require(dump.is_file() and not dump.is_symlink() and dump.stat().st_size == 24883200, "original-A output dump extent differs")
    (job / "qualified-private.json").write_text(json.dumps(dict(complete=True, mode=config["lut_mode"],
        metadata_sequence=config["metadata_sequence"], kodi_state=kodi_state, output_sha256=digest(dump), output_scope="original A only",
        output_bytes=dump.stat().st_size, timing_scope="host submit/finish wall and CPU, not GPU kernel time"), indent=2))
    print("Private guarded NLQ test PASS; all frame/route/cache/resource/identity gates passed. No GPU-exclusive timing claim.")


if __name__ == "__main__":
    main()
