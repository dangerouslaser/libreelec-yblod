"""Independent wire oracle. Native cases require real-header executable/archive.

Local parser fixtures are invented transport bytes, not serializer execution.
No FFmpeg ABI substitute, GPU, device or film content is involved.
"""
import json
import hashlib
import os
from pathlib import Path
import re
import struct
import stat
import subprocess
import unittest
import tempfile
from unittest import mock

CASES = ("baseline", "l2-2", "l2-8", "l2-15", "l2-20", "l2-21-reject",
         "boundary-119", "boundary-120")
L2_COUNTS = dict(zip(CASES[:6], (0, 2, 8, 15, 20, 21)))
LENGTHS = dict(zip(CASES, (95, 133, 247, 380, 475, 494, 119, 120)))
CHECKPOINT = Path(__file__).parent / "results" / "native-metadata-fragments-libreelec-20261005a.json"
RECORD_FIELDS = ("accepted", "committed", "failure_preserved_outer_state",
                 "inner_mutated_on_failure", "frames", "changes", "packet_count",
                 "payload_hex", "packet_hex")
EXECUTED_C = "fd9a57bf554e3b24c7ac80e3db655fba0a580e2d117b4e606591090879e19e9c"
EXECUTED_BINARY = "9f086053df1ac496db1016183ae9c856a75c418cccc18ec0ac47c18992bb651d"
LIBRARY = "16e16a2ab0f89a48c7e487d365e84f1c005f119fa8754c146daaeff40883c108"
DEPENDENCIES = {
    "dvbridge_metadata.h": "da799ab08381318601bb0a3f8a1a74ed3293ca09b2cdde52228ea6f7e4c06d36",
    "mpv_dvbridge_cm4.h": "f6762808f5d7a5824983d72b0188098f19e86bd2a6db7b997ef63e2d35612661",
    "dovi_meta.h": "f860511cb8be3c992b4ef7da6747d8dc9670d64d276aeab3a7e6867112857a02"}


def sha(value):
    if type(value) is not str or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("strict SHA256 required")
    return value


def crc(data):
    accumulator = 0xffffffff
    for byte in data:
        accumulator ^= byte << 24
        for _ in range(8):
            top = accumulator & 0x80000000
            accumulator = (accumulator << 1) & 0xffffffff
            if top:
                accumulator ^= 0x04c11db7
    return accumulator


def parse_json(raw, maximum=16384):
    if len(raw) > maximum:
        raise ValueError("bounded synthetic log required")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite JSON value")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject, parse_float=reject)


def original_stdout(result):
    """Reconstitute this fixed C stdout grammar, not arbitrary JSON whitespace."""
    value = {"schema": result["schema"], "synthetic_only": result["synthetic_only"],
             "case": result["case"], "records": [
                 {name: record[name] for name in RECORD_FIELDS} for record in result["records"]]}
    return (json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n").encode()


def checkpoint_cases():
    fd = os.open(CHECKPOINT, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        initial = os.fstat(stream.fileno())
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError("regular checkpoint required")
        raw = stream.read(1024 * 1024 + 1)
        stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if (stamp(initial) != stamp(os.fstat(stream.fileno())) or
                stamp(initial) != stamp(CHECKPOINT.stat()) or len(raw) != initial.st_size):
            raise ValueError("checkpoint changed or exceeded bound")
    report = parse_json(raw, 1024 * 1024)
    required = {"schema": "yblod.native-metadata-fragment-checkpoint.v1", "status": "complete",
                "synthetic_only": True, "gpu_attempted": False, "binary_sha256": EXECUTED_BINARY,
                "sdk_and_installed_libavutil_sha256": LIBRARY}
    if type(report) is not dict or any(type(report.get(k)) is not type(v) or report[k] != v
                                     for k, v in required.items()):
        raise ValueError("fixed checkpoint identity mismatch")
    source = report.get("source_sha256")
    if (type(source) is not dict or set(source) != {"native_metadata_fragment_probe.c", "run_native_metadata_fragment_probe.sh"}
            or source["native_metadata_fragment_probe.c"] != EXECUTED_C):
        raise ValueError("executed source identity mismatch")
    for value in source.values(): sha(value)
    if source["run_native_metadata_fragment_probe.sh"] != "a552b21c625a899f61a1b9f5e30fb60af8ea6c499e6df4e69dccc9edcf1eb86f":
        raise ValueError("executed cohort identity mismatch")
    if report.get("dependency_sha256") != DEPENDENCIES:
        raise ValueError("actual header identity mismatch")
    analysis = report.get("analysis_sha256")
    if type(analysis) is not dict or set(analysis) != {"test_native_metadata_fragment_probe.py", "NATIVE_METADATA_FRAGMENT_PROBE.md"}:
        raise ValueError("separate publication analysis pins required")
    for value in analysis.values(): sha(value)
    expected_counts = dict(cases=8, records=16, accepted_records=15,
        deliberately_rejected_records=1, multipart_target_records=5,
        original_archive_tests=6, final_public_replay_tests=8)
    if (report.get("counts") != expected_counts or
            any(type(v) is not int for v in report["counts"].values())):
        raise ValueError("fixed cohort counts required")
    memory = report.get("memory")
    if type(memory) is not dict:
        raise ValueError("actual memory snapshots required")
    for key in ("max_bytes", "swap_max_bytes", "swap_current_before_bytes", "swap_current_after_bytes", "peak_observed_before_exit_bytes"):
        if type(memory.get(key)) is not int or memory[key] < 0:
            raise ValueError("strict snapshot integer required")
    if (memory["max_bytes"] != 536870912 or memory["swap_max_bytes"] != 0
            or memory["swap_current_before_bytes"] != 0 or memory["swap_current_after_bytes"] != 0
            or not 0 < memory["peak_observed_before_exit_bytes"] <= memory["max_bytes"]):
        raise ValueError("snapshot limits/peak invalid")
    for key in ("events_before", "events_after"):
        events = memory.get(key)
        if (type(events) is not dict or set(events) != {"low", "high", "max", "oom", "oom_kill", "oom_group_kill", "sock_throttled"}
                or any(type(v) is not int or v != 0 for v in events.values())):
            raise ValueError("fixed zero event snapshots required")
    cases = report.get("cases")
    if type(cases) is not list or len(cases) != len(CASES):
        raise ValueError("exact eight cases required")
    for case, name in zip(cases, CASES):
        if type(case) is not dict or case.get("case") != name:
            raise ValueError("fixed ordered case required")
        if type(case.get("exit_status")) is not int or case["exit_status"] != (3 if name == "l2-21-reject" else 0):
            raise ValueError("native exit status mismatch")
        sha(case.get("stdout_sha256")); sha(case.get("stderr_sha256"))
        if case["stderr_sha256"] != hashlib.sha256(b"").hexdigest():
            raise ValueError("expected empty native stderr")
        result = case.get("result")
        if (type(result) is not dict or set(result) != {"schema", "synthetic_only", "case", "records"}
                or result.get("schema") != "yblod.native-metadata-fragment-probe.v1"
                or result.get("synthetic_only") is not True or result.get("case") != name
                or type(result.get("records")) is not list or len(result["records"]) != 2):
            raise ValueError("exact native result required")
        for i, record in enumerate(result["records"]):
            if type(record) is not dict or set(record) != set(RECORD_FIELDS):
                raise ValueError("fixed record fields required")
            for field in RECORD_FIELDS[:4]:
                if type(record[field]) is not bool: raise ValueError("strict native bool required")
            for field in RECORD_FIELDS[4:7]:
                if type(record[field]) is not int or record[field] < 0: raise ValueError("strict native counter required")
            rejection = i == 1 and name == "l2-21-reject"
            if record["accepted"] != (not rejection) or record["committed"] != (not rejection):
                raise ValueError("native acceptance mismatch")
            if rejection:
                if (not record["failure_preserved_outer_state"] or not record["inner_mutated_on_failure"]
                        or record["frames"] != 1 or record["changes"] != 0 or record["packet_count"] != 0
                        or record["payload_hex"] != "" or record["packet_hex"] != ""):
                    raise ValueError("failed candidate exposed/committed")
            else:
                if record["failure_preserved_outer_state"] or record["inner_mutated_on_failure"]:
                    raise ValueError("successful record falsely labelled failure")
                payload, _ = decode(record, i)
                if len(payload) != (95 if i == 0 else LENGTHS[name]):
                    raise ValueError("fixed fixture size mismatch")
        if hashlib.sha256(original_stdout(result)).hexdigest() != case["stdout_sha256"]:
            raise ValueError("original native stdout digest mismatch")
    return {item["case"]: item for item in cases}


def decode(record, expected_id):
    if type(record) is not dict or type(record.get("packet_count")) is not int:
        raise ValueError("strict packet count required")
    count = record["packet_count"]
    if not 1 <= count <= 4:
        raise ValueError("one to four packets required")
    for key, bound in (("payload_hex", 964), ("packet_hex", 1024)):
        value = record.get(key)
        if type(value) is not str or len(value) > bound or not re.fullmatch(r"(?:[0-9a-f]{2})*", value):
            raise ValueError("bounded byte hex required")
    payload, wire = (bytes.fromhex(record[k]) for k in ("payload_hex", "packet_hex"))
    if not 71 <= len(payload) <= 482 or len(wire) != count * 128:
        raise ValueError("payload/frame size invalid")
    # Independent first119 + subsequent121 capacity equation.
    required = 1
    capacity = 119
    while capacity < len(payload):
        capacity += 121
        required += 1
    if count != required:
        raise ValueError("nonminimal packet count")
    recovered = bytearray()
    for i in range(count):
        packet = wire[i * 128:(i + 1) * 128]
        if crc(packet) != 0:
            raise ValueError("CRC mismatch")
        tag = 0 if count == 1 else 1 if i == 0 else 3 if i == count - 1 else 2
        if packet[0] != tag << 6 or packet[1] != expected_id * 17 or packet[2] != 0:
            raise ValueError("packet sequence/identity/reserved mismatch")
        start = 5 if i == 0 else 3
        if i == 0 and int.from_bytes(packet[3:5], "big") != len(payload):
            raise ValueError("declared length mismatch")
        take = min(124 - start, len(payload) - len(recovered))
        recovered += packet[start:start + take]
        if any(packet[start + take:124]):
            raise ValueError("nonzero unused padding")
    if recovered != payload:
        raise ValueError("assembly mismatch")
    offset = 71
    extensions = []
    for _ in range(payload[70]):
        if offset + 5 > len(payload):
            raise ValueError("extension header truncation")
        length = int.from_bytes(payload[offset:offset + 4], "big")
        level = payload[offset + 4]
        offset += 5
        if offset + length > len(payload):
            raise ValueError("extension body truncation")
        extensions.append((level, payload[offset:offset + length]))
        offset += length
    if offset != len(payload):
        raise ValueError("extension trailing bytes")
    return payload, extensions


def transport_fixture(payload, identity=1):
    """Invented parser-only wire fixture, NOT output from the tested serializer."""
    count = 1 + max(0, len(payload) - 119 + 120) // 121
    packets = bytearray()
    offset = 0
    for i in range(count):
        packet = bytearray(128)
        packet[0] = (0 if count == 1 else 1 if i == 0 else 3 if i == count - 1 else 2) << 6
        packet[1] = identity * 17
        start = 5 if i == 0 else 3
        if i == 0: packet[3:5] = len(payload).to_bytes(2, "big")
        take = min(124 - start, len(payload) - offset)
        packet[start:start + take] = payload[offset:offset + take]
        offset += take
        packet[124:] = crc(packet[:124]).to_bytes(4, "big")
        packets += packet
    return dict(packet_count=count, payload_hex=payload.hex(), packet_hex=packets.hex())


class FragmentParserTests(unittest.TestCase):
    def test_crc_known_answer_and_all_packet_capacity_edges(self):
        self.assertEqual(crc(b"123456789"), 0x0376e6e7)
        for length in (119, 120, 240, 241, 361, 362, 475, 482):
            payload = bytearray(71)
            payload[70] = 1
            payload += (length - 76).to_bytes(4, "big") + b"\xfe" + bytes(length - 76)
            record = transport_fixture(payload)
            actual, _ = decode(record, 1)
            self.assertEqual(actual, payload)

    def test_corruption_crc_and_repaired_semantic_errors(self):
        payload = bytearray(71)
        payload[70] = 1
        payload += (57).to_bytes(4, "big") + b"\xfe" + bytes(57)
        good = transport_fixture(payload)
        for position, change, repaired in ((129, 0x11, True), (128, 0x80, True),
                                           (200, 1, True), (3, 1, True), (126, 1, False)):
            wire = bytearray.fromhex(good["packet_hex"])
            wire[position] ^= change
            if repaired:
                packet = position // 128
                first = packet * 128
                wire[first + 124:first + 128] = crc(wire[first:first + 124]).to_bytes(4, "big")
            with self.assertRaises(ValueError):
                decode(dict(good, packet_hex=wire.hex()), 1)
        for key, value in (("packet_count", True), ("packet_count", 5),
                           ("packet_hex", "00" * 513), ("payload_hex", "00" * 483)):
            with self.assertRaises(ValueError): decode(dict(good, **{key: value}), 1)

    def test_strict_json_bounds_and_extension_trailing_rejection(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b" " * 16385):
            with self.assertRaises(ValueError): parse_json(raw)
        for payload in (bytes(72), bytes(70) + b"\x01"):
            with self.assertRaises(ValueError): decode(transport_fixture(payload), 1)

    def test_checkpoint_pins_types_case_order_and_log_corruption(self):
        original = json.loads(CHECKPOINT.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            for fault in ("binary", "case", "type", "digest", "payload", "source", "dependency", "memory", "count"):
                changed = json.loads(json.dumps(original))
                if fault == "binary": changed["binary_sha256"] = "0" * 64
                if fault == "case": changed["cases"].reverse()
                if fault == "type": changed["cases"][0]["result"]["records"][0]["packet_count"] = True
                if fault == "digest": changed["cases"][0]["stdout_sha256"] = "0" * 64
                if fault == "payload": changed["cases"][0]["result"]["records"][0]["packet_hex"] = "00" * 513
                if fault == "source": changed["source_sha256"]["native_metadata_fragment_probe.c"] = "0" * 64
                if fault == "dependency": changed["dependency_sha256"]["dovi_meta.h"] = "0" * 64
                if fault == "memory": changed["memory"]["swap_current_after_bytes"] = 1
                if fault == "count": changed["counts"]["cases"] = True
                path.write_text(json.dumps(changed))
                with mock.patch(__name__ + ".CHECKPOINT", path), self.assertRaises(ValueError): checkpoint_cases()

    def test_checkpoint_missing_nonregular_symlink_duplicate_and_read_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "checkpoint.json"
            with mock.patch(__name__ + ".CHECKPOINT", path), self.assertRaises(FileNotFoundError): checkpoint_cases()
            with mock.patch(__name__ + ".CHECKPOINT", root), self.assertRaises((OSError, ValueError)): checkpoint_cases()
            for raw in (b" " * (1024 * 1024 + 1), b'{"schema":1,"schema":2}', b'{"schema":NaN}', b'{"schema":1e999}'):
                path.write_bytes(raw)
                with mock.patch(__name__ + ".CHECKPOINT", path), self.assertRaises(ValueError): checkpoint_cases()
            link = root / "alias"
            link.symlink_to(path)
            if hasattr(os, "O_NOFOLLOW"):
                with mock.patch(__name__ + ".CHECKPOINT", link), self.assertRaises(OSError): checkpoint_cases()


@unittest.skipUnless(os.environ.get("YB_NATIVE_METADATA_FRAGMENT_PROBE") or
                     os.environ.get("YB_NATIVE_METADATA_FRAGMENT_ARCHIVE") or CHECKPOINT.is_file(),
                     "actual-header fragment executable or saved native logs required")
class NativeFragmentTests(unittest.TestCase):
    def invoke(self, name):
        executable = os.environ.get("YB_NATIVE_METADATA_FRAGMENT_PROBE")
        if executable:
            result = subprocess.run([str(Path(executable).resolve(strict=True)), name],
                                    capture_output=True, timeout=5, check=False)
            exit_status, raw, stderr = result.returncode, result.stdout, result.stderr
        elif os.environ.get("YB_NATIVE_METADATA_FRAGMENT_ARCHIVE"):
            root = Path(os.environ["YB_NATIVE_METADATA_FRAGMENT_ARCHIVE"]) / "cases"
            with (root / (name + ".json")).open("rb") as stream: raw = stream.read(16385)
            with (root / (name + ".stderr")).open("rb") as stream: stderr = stream.read(16385)
            exit_status = int((root / (name + ".exit-status")).read_text())
        else:
            saved = checkpoint_cases()[name]
            exit_status, raw, stderr = saved["exit_status"], original_stdout(saved["result"]), b""
        self.assertEqual(exit_status, 3 if name == "l2-21-reject" else 0)
        self.assertEqual(stderr, b"")
        report = parse_json(raw)
        self.assertEqual(report["schema"], "yblod.native-metadata-fragment-probe.v1")
        self.assertIs(report["synthetic_only"], True)
        self.assertEqual(report["case"], name)
        self.assertEqual(len(report["records"]), 2)
        for record in report["records"]:
            for field in ("accepted", "committed", "failure_preserved_outer_state", "inner_mutated_on_failure"):
                self.assertIs(type(record[field]), bool)
            for field in ("frames", "changes", "packet_count"):
                self.assertIs(type(record[field]), int)
        self.assertIs(report["records"][0]["accepted"], True)
        self.assertEqual(len(decode(report["records"][0], 0)[0]), 95)
        return report["records"]

    def test_distinct_l2_multiple_packets_literal_order_and_bytes(self):
        for name in CASES[:5]:
            records = self.invoke(name)
            target = records[1]
            self.assertIs(target["accepted"], True)
            self.assertIs(target["committed"], True)
            payload, extensions = decode(target, 1)
            count = L2_COUNTS[name]
            self.assertEqual(len(payload), LENGTHS[name])
            self.assertEqual(target["packet_count"], {0: 1, 2: 2, 8: 3, 15: 4, 20: 4}[count])
            expected = [(1, bytes.fromhex("00000bb80200"))]
            expected += [(2, struct.pack(">7H", 1000 + i, 2048 + i, 2048, 2048, 2048, 2048, 65535))
                         for i in reversed(range(count))]
            expected += [(5, bytes(8))]
            self.assertEqual(extensions, expected)
            self.assertEqual((target["frames"], target["changes"]), (2, 1))

    def test_exact119120_boundary_accepted_converter_grammar(self):
        for name, extra in (("boundary-119", (9, bytes(1))),
                            ("boundary-120", (254, bytes(2)))):
            target = self.invoke(name)[1]
            self.assertIs(target["accepted"], True)
            payload, extensions = decode(target, 1)
            self.assertEqual(len(payload), LENGTHS[name])
            self.assertEqual(target["packet_count"], 1 if name.endswith("119") else 2)
            self.assertEqual(extensions, [(1, bytes.fromhex("00000bb80200")), (5, bytes(8)),
                                         (8, b"\x01" + b"\x08\x00" * 6), extra])

    def test_overcap_rejection_preserves_seeded_outer_state(self):
        seed, rejected = self.invoke("l2-21-reject")
        self.assertIs(rejected["accepted"], False)
        self.assertIs(rejected["committed"], False)
        self.assertIs(rejected["failure_preserved_outer_state"], True)
        self.assertIs(rejected["inner_mutated_on_failure"], True)
        self.assertEqual((rejected["frames"], rejected["changes"]), (seed["frames"], seed["changes"]))
        self.assertEqual((rejected["packet_count"], rejected["payload_hex"], rejected["packet_hex"]), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
