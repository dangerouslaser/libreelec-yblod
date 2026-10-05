#!/usr/bin/env python3
"""Capture the CURRENT already-paused SK4 picture; never play, pause or seek.

Device-side Python standard library only. VDIN1 is started/stopped for each
cycle. By default a driver dump is required before two O_RDONLY|O_SYNC
physical-memory reads. --allow-unverified-dma-sync permits a missing driver
dump for empirical readback diagnostics only: stable reads cannot rule out
stale cache data. All available files are retained. Fresh
kernel-log snapshots, paused state, layout, metadata and cleanup fail closed.
This diagnostic does not alter precision, bypass, video output or picture flags.
"""
import argparse
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time

WIDTH, HEIGHT = 3840, 2160
FRAME_BYTES = WIDTH*HEIGHT*3
CHUNK_BYTES = 1024*1024
DEC_STARTED = 0x2
# dmesg timestamps begin a line and have a fractional part. Bracketed numeric
# register/payload values elsewhere (including [90000]) are not timestamps.
STAMP = r"(?m)^[ \t]*\[[ \t]*([0-9]+\.[0-9]+)\]"


def fresh_log(before, after):
    """Exclude old records using an exact snapshot anchor, never a time fudge."""
    old = before.splitlines()
    if not old:
        raise ValueError("empty kernel-log watermark")
    anchor = "\n".join(old[-16:])
    position = after.find(anchor)
    if position < 0 or after.find(anchor, position+1) >= 0:
        raise ValueError("kernel-log watermark lost or ambiguous; refusing stale records")
    fresh = after[position+len(anchor):].lstrip("\n")
    old_times = re.findall(STAMP, before)
    if not old_times:
        raise ValueError("kernel-log watermark lacks timestamps")
    watermark = max(float(value) for value in old_times)
    if any(float(value) < watermark for value in re.findall(STAMP, fresh)):
        raise ValueError("kernel-log timestamps moved backwards")
    return fresh


def parse_state(text):
    flags = re.findall(STAMP + r"[^\n]*\bflags=0x([0-9a-fA-F]+),\s*flags_isr=0x[0-9a-fA-F]+", text)
    cma = re.findall(STAMP + r"[^\n]*\bcma_flag:0x([0-9a-fA-F]+)", text)
    if len(flags) != 1 or len(cma) != 1:
        raise ValueError("exactly one fresh VDIN flags/CMA state required")
    return {"flags": int(flags[0][1], 16), "cma_flag": int(cma[0][1], 16),
            "flags_timestamp": flags[0][0], "cma_timestamp": cma[0][0]}


def parse_buffers(text, expected_size=FRAME_BYTES, page_size=4096):
    pattern = STAMP + r"[^\n]*buf\[(\d+)\]mem_start\s*=\s*(0x[0-9a-fA-F]+),\s*mem_size\s*=\s*(0x[0-9a-fA-F]+)"
    records = re.findall(pattern, text)
    buffers = {}
    for timestamp, index, address, size in records:
        index, address, size = int(index), int(address, 16), int(size, 16)
        if not 0 <= index <= 3 or index in buffers:
            raise ValueError("invalid or duplicate fresh buffer index")
        if not address or address % page_size or size != expected_size or address+size > 1 << 63:
            raise ValueError("unexpected physical buffer bounds/layout")
        buffers[index] = {"index": index, "address_hex": hex(address), "size": size, "timestamp": timestamp}
    if not buffers:
        raise ValueError("no fresh VDIN buffers")
    ordered = sorted(buffers.values(), key=lambda item: int(item["address_hex"], 16))
    for first, second in zip(ordered, ordered[1:]):
        if int(first["address_hex"], 16)+first["size"] > int(second["address_hex"], 16):
            raise ValueError("fresh physical buffers overlap")
    return buffers


def parse_freeze(text):
    if re.search(r"vdin_vf_freeze:[^\n]*from\s+wr\s+list", text, re.I):
        raise ValueError("completed RD-list freeze required; WR fallback rejected")
    events = re.findall(STAMP + r"[^\n]*vdin_vf_freeze:\s*add\s+(\d+)\s+frame from\s+(rd|wr)\s+list", text, re.I)
    if len(events) != 1 or events[0][2].lower() != "rd":
        raise ValueError("exactly one fresh completed RD-list freeze required; WR fallback rejected")
    timestamp, index, _ = events[0]
    return {"index": int(index), "timestamp": timestamp, "list": "rd"}


def rpc(method, params):
    with socket.create_connection(("127.0.0.1", 9090), timeout=10) as connection:
        connection.settimeout(10)
        connection.sendall(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()+b"\n")
        pending = b""
        decoder = json.JSONDecoder()
        while len(pending) < CHUNK_BYTES:
            data = connection.recv(65536)
            if not data:
                raise RuntimeError("Kodi closed the RPC connection")
            pending += data
            text = pending.decode("utf-8")
            while text.strip():
                text = text.lstrip()
                try:
                    response, consumed = decoder.raw_decode(text)
                except json.JSONDecodeError:
                    break
                text = text[consumed:]
                if response.get("id") == 1:
                    if "error" in response:
                        raise RuntimeError("Kodi RPC error: " + json.dumps(response["error"]))
                    return response["result"]
            pending = text.encode("utf-8")
        raise RuntimeError("Kodi RPC response exceeds size limit")


class Hardware:
    control = Path("/sys/class/vdin/vdin1/attr")

    def command(self, value):
        self.control.write_text(value+"\n")

    def log(self):
        return subprocess.check_output(["dmesg"], text=True, timeout=10)

    def event(self, command):
        before = self.log()
        self.command(command)
        return fresh_log(before, self.log())

    def state(self):
        text = self.event("state")
        return parse_state(text), text

    def snapshot(self):
        config = Path("/sys/class/amhdmitx/amhdmitx0/config").read_text()
        if "3840x2160p24hz" not in config or "EOTF: DV-Std" not in config:
            raise ValueError("requires unchanged 3840x2160p24 standard Dolby Vision output")
        active = rpc("Player.GetActivePlayers", {})
        if not isinstance(active, list) or not any(isinstance(player, dict) and
                type(player.get("playerid")) is int and player["playerid"] == 1 and
                player.get("type") == "video" for player in active):
            raise ValueError("Kodi video player 1 must already be active")
        properties = rpc("Player.GetProperties", {"playerid": 1, "properties": ["speed", "time"]})
        if properties.get("speed") != 0:
            raise ValueError("Kodi must already be paused; this script never changes playback")
        timestamp = properties["time"]
        if set(timestamp) != {"hours", "minutes", "seconds", "milliseconds"} or any(type(v) is not int or v < 0 for v in timestamp.values()):
            raise ValueError("invalid Kodi paused timestamp")
        return {"pts_90k": int(Path("/sys/class/tsync/pts_video").read_text().strip(), 16),
                "kodi": properties, "hdmi_config": config, "monotonic_ns": time.monotonic_ns()}


def same_picture(initial, current):
    for key in ("pts_90k", "kodi", "hdmi_config"):
        if current[key] != initial[key]:
            raise ValueError("paused picture/output state changed: " + key)


def file_record(path, chunk_bytes=CHUNK_BYTES):
    size, checksum = 0, hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(chunk_bytes):
            size += len(chunk)
            checksum.update(chunk)
    return {"file": Path(path).name, "bytes": size, "sha256": checksum.hexdigest()}


def copy_chunks(source, size, destination, chunk_bytes=CHUNK_BYTES):
    checksum = hashlib.sha256()
    with Path(destination).open("xb") as target:
        for offset in range(0, size, chunk_bytes):
            expected = min(chunk_bytes, size-offset)
            chunk = source[offset:offset+expected]
            if len(chunk) != expected:
                raise ValueError("short physical-memory read")
            target.write(chunk)
            checksum.update(chunk)
    return {"file": Path(destination).name, "bytes": size, "sha256": checksum.hexdigest()}


def physical_read(buffer, destination):
    address, size = int(buffer["address_hex"], 16), buffer["size"]
    descriptor = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    try:
        with mmap.mmap(descriptor, size, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ, offset=address) as source:
            return copy_chunks(source, size, destination)
    finally:
        os.close(descriptor)


def compare_files(first, second, chunk_bytes=CHUNK_BYTES):
    offset, first_difference = 0, None
    with Path(first).open("rb") as a, Path(second).open("rb") as b:
        while True:
            left, right = a.read(chunk_bytes), b.read(chunk_bytes)
            if not left and not right:
                break
            if first_difference is None and left != right:
                common = min(len(left), len(right))
                first_difference = offset + next((i for i in range(common) if left[i] != right[i]), common)
            offset += max(len(left), len(right))
    return {"byte_identical": first_difference is None, "first_difference_offset": first_difference,
            "compared_bytes": offset}


def crc32_mpeg2(data):
    value = 0xffffffff
    for byte in data:
        value ^= byte << 24
        for _ in range(8):
            value = ((value << 1) ^ (0x04c11db7 if value & 0x80000000 else 0)) & 0xffffffff
    return value


def metadata_check(path):
    with Path(path).open("rb") as source:
        raw = source.read(6144*3)
    if len(raw) != 6144*3:
        raise ValueError("capture too short for two complete metadata slots")
    logical = b"".join(raw[index:index+8][::-1] for index in range(0, len(raw), 8))
    packets = []
    for number in range(2):
        copies = []
        for copy in range(3):
            value = 0
            for pixel in range(number*3072 + copy*1024, number*3072 + (copy+1)*1024):
                g, b, r = logical[pixel*3:pixel*3+3]
                intensity, chroma = (g << 4) | (b & 15), (r << 4) | (b >> 4)
                parity = ((chroma >> 1).bit_count()+intensity.bit_count()) & 1
                value = (value << 1) | ((chroma & 1) ^ parity)
            payload = value.to_bytes(128, "big")
            if crc32_mpeg2(payload):
                raise ValueError(f"metadata CRC failed: packet {number}, copy {copy}")
            copies.append(payload)
        if len(set(copies)) != 1:
            raise ValueError("valid metadata copies disagree")
        packets.append(copies[0])
    if [packet[0] >> 6 for packet in packets] != [1, 3]:
        raise ValueError("unsupported metadata packet framing")
    return {"packets": 2, "copies_per_packet": 3, "all_crc_valid": True, "copies_identical": True}


def attempt_driver_dump(hardware, driver, index, cycle, allow_unverified_dma_sync=False):
    if driver.exists():
        raise ValueError("driver dump path already exists")
    hardware.command(f"capture {driver} {index}")
    if not driver.exists():
        cycle["dma_sync"] = {"status": "unverified", "driver_dump_available": False,
            "reason": "capture command returned but no driver dump file was created",
            "limitation": "identical physical reads cannot rule out stale cache data"}
        if not allow_unverified_dma_sync:
            raise ValueError("driver dump unavailable; DMA synchronization unverified (strict default)")
        return False
    cycle["driver_dump"] = file_record(driver)
    if cycle["driver_dump"]["bytes"] != FRAME_BYTES:
        raise ValueError("driver dump size differs from confirmed frame bounds")
    cycle["dma_sync"] = {"status": "driver_dump_observed", "driver_dump_available": True,
        "basis": "reviewed driver dump implementation performs DMA_FROM_DEVICE synchronization; not independently instrumented"}
    return True


def capture_cycle(hardware, output, index, initial, record=None, allow_unverified_dma_sync=False):
    cycle = record if record is not None else {}
    cycle.update(cycle_index=index, state_before_start=hardware.snapshot())
    same_picture(initial, cycle["state_before_start"])
    hardware.command("v4l2start venc0 3840 2160 24 0 0")
    time.sleep(0.7)
    state, state_log = hardware.state()
    if not state["flags"] & DEC_STARTED:
        raise ValueError("VDIN start was not confirmed")
    buffers = parse_buffers(state_log, page_size=os.sysconf("SC_PAGE_SIZE"))
    freeze_log = hardware.event("freeze")
    frozen = parse_freeze(freeze_log)
    if frozen["index"] not in buffers:
        raise ValueError("frozen index has no matching fresh buffer")
    cycle["buffer"], cycle["freeze_event"] = buffers[frozen["index"]], frozen
    cycle["state_after_freeze"] = hardware.snapshot()
    same_picture(initial, cycle["state_after_freeze"])
    # Confirm the frozen address has not changed before any memory access.
    frozen_state, frozen_log = hardware.state()
    frozen_buffers = parse_buffers(frozen_log, page_size=os.sysconf("SC_PAGE_SIZE"))
    if (not frozen_state["flags"] & DEC_STARTED or frozen["index"] not in frozen_buffers or
            any(frozen_buffers[frozen["index"]][key] != cycle["buffer"][key] for key in ("index", "address_hex", "size"))):
        raise ValueError("frozen buffer bounds changed")
    (output / f"cycle-{index:02d}-driver-state.txt").write_text(state_log+"\n"+freeze_log+"\n"+frozen_log)
    driver = output / f"cycle-{index:02d}-driver.rgb"
    driver_available = attempt_driver_dump(hardware, driver, frozen["index"], cycle,
                                           allow_unverified_dma_sync)
    first, second = output / f"cycle-{index:02d}-first.rgb", output / f"cycle-{index:02d}-second.rgb"
    cycle["first_read"] = physical_read(cycle["buffer"], first)
    same_picture(initial, hardware.snapshot())
    cycle["second_read"] = physical_read(cycle["buffer"], second)
    cycle["same_buffer_comparison"] = compare_files(first, second)
    if driver_available:
        cycle["driver_vs_first_comparison"] = compare_files(driver, first)
    cycle["state_after_reads"] = hardware.snapshot()
    same_picture(initial, cycle["state_after_reads"])
    names = ("driver_dump", "first_read", "second_read") if driver_available else ("first_read", "second_read")
    cycle["metadata"] = {name: metadata_check(output / cycle[name]["file"]) for name in names}
    stable = cycle["same_buffer_comparison"]["byte_identical"]
    if driver_available:
        stable = stable and cycle["driver_vs_first_comparison"]["byte_identical"]
    cycle["status"] = "complete" if stable else "unstable"
    cycle["completion_scope"] = "empirical readback stability only; not proof of DMA cache coherency"
    return cycle


def stop_verified(hardware):
    hardware.command("v4l2stop")
    state, _ = hardware.state()
    if state["flags"] & DEC_STARTED:
        raise ValueError("VDIN stop was not confirmed")
    return state


def run(output, cycles=3, hardware=None, allow_unverified_dma_sync=False):
    output = Path(output).resolve()
    if not 1 <= cycles <= 3 or type(cycles) is not int:
        raise ValueError("one to three capture cycles required")
    if not output.is_relative_to(Path("/storage")) or not re.fullmatch(r"[A-Za-z0-9_./-]+", str(output)):
        raise ValueError("fresh output must be a whitespace-free path under /storage")
    output.mkdir(parents=True, exist_ok=False)
    hardware = hardware or Hardware()
    report = {"schema": "yblod.capture-repeat.v1", "status": "incomplete", "width": WIDTH, "height": HEIGHT,
              "storage": "CoreELEC RGB8; reverse each 64-bit word; logical channels G,B,R", "capture_port": "venc0",
              "cycles": [], "allow_unverified_dma_sync": allow_unverified_dma_sync,
              "completion_scope": "capture procedure and empirical readback stability; not proof of DMA cache coherency",
              "readback": "O_RDONLY|O_SYNC /dev/mem, MAP_SHARED/PROT_READ; separate mapping per read",
              "chunk_bytes": CHUNK_BYTES, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "python_version": os.sys.version, "cleanup": {}, "source_association": "external visible-counter verification required"}
    initial_cma, modified, started = None, False, False
    error = None
    try:
        initial_driver, initial_log = hardware.state()
        if initial_driver["flags"] & DEC_STARTED:
            raise ValueError("VDIN1 already running; refusing to take over another capture")
        initial_cma = initial_driver["cma_flag"]
        report["initial_driver_state"] = initial_driver
        (output / "initial-driver-state.txt").write_text(initial_log)
        initial = hardware.snapshot()
        report["initial_state"] = initial
        report["software_state"] = {name: Path(path).read_text() for name, path in
            (("os_release", "/etc/os-release"), ("kernel_version", "/proc/version"), ("source_format", "/sys/class/amdolby_vision/src_format"))}
        modified = True
        hardware.command("cma_config_flag 101")
        cma_state, _ = hardware.state()
        if cma_state["cma_flag"] != 0x101 or cma_state["flags"] & DEC_STARTED:
            raise ValueError("capture CMA configuration not confirmed while idle")
        for index in range(cycles):
            started = True
            cycle = {"cycle_index": index, "status": "incomplete"}
            report["cycles"].append(cycle)
            capture_cycle(hardware, output, index, initial, record=cycle,
                          allow_unverified_dma_sync=allow_unverified_dma_sync)
            stop_verified(hardware)
            started = False
            if cycle["status"] != "complete":
                raise ValueError("readback differs within one frozen buffer; retained all evidence")
        same_picture(initial, hardware.snapshot())
    except BaseException as failure:
        error = f"{type(failure).__name__}: {failure}"
    finally:
        if modified:
            try:
                # Confirm stopped even if the last cycle completed its stop.
                if started:
                    stop_verified(hardware)
                else:
                    final_state, _ = hardware.state()
                    if final_state["flags"] & DEC_STARTED:
                        stop_verified(hardware)
                report["cleanup"]["vdin_stopped_confirmed"] = True
                hardware.command(f"cma_config_flag {initial_cma:x}")
                restored, restore_log = hardware.state()
                if restored["flags"] & DEC_STARTED or restored["cma_flag"] != initial_cma:
                    raise ValueError("original CMA state was not restored")
                report["cleanup"].update(cma_restored=True, original_cma_flag=initial_cma, final_state=restored)
                (output / "cleanup-driver-state.txt").write_text(restore_log)
            except BaseException as failure:
                report["cleanup"]["error"] = f"{type(failure).__name__}: {failure}"
                error = error or report["cleanup"]["error"]
        else:
            report["cleanup"]["no_capture_configuration_changed"] = True
    report["status"] = "failed" if error else "complete"
    if error:
        report["error"] = error
    with (output / "capture-repeat.json").open("x") as target:
        json.dump(report, target, indent=2)
        target.write("\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--allow-unverified-dma-sync", action="store_true",
                        help="allow missing driver dump; identical reads cannot rule out stale cache data")
    args = parser.parse_args(argv)
    def interrupted(number, _frame):
        raise RuntimeError(f"capture interrupted by signal {number}")
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), interrupted)
    try:
        report = run(args.output, args.cycles, allow_unverified_dma_sync=args.allow_unverified_dma_sync)
    except (OSError, ValueError) as error:
        parser.exit(1, f"repeat capture: {error}\n")
    print(json.dumps({"directory": str(args.output), "status": report["status"], "cycles": len(report["cycles"])}), flush=True)
    if report["status"] != "complete":
        parser.exit(1, report["error"]+"\n")


if __name__ == "__main__":
    main()
