"""Independent wire assertions for the real-header synthetic C serializer.

Set YB_NATIVE_METADATA_PROBE to the reviewed executable compiled with the exact
patched FFmpeg headers/library, or YB_NATIVE_METADATA_ARCHIVE to its saved nine
case outputs. No locally invented ABI or shader/device use.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

CHECKPOINT = Path(__file__).parent / "results" / "native-metadata-probe-libreelec-20261005a.json"
CASES = ("baseline", "l1-changed", "l2-added", "l2-changed", "l8-added", "l8-changed",
         "repeat", "seek", "invalid-duplicate-l1")


def checkpoint_cases():
    """Verify and replay recorded synthetic C output; this performs NO C run."""
    descriptor = os.open(CHECKPOINT, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        initial = os.fstat(stream.fileno())
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError("regular synthetic checkpoint required")
        raw = stream.read(1024*1024+1)
        def snapshot(info):
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
        if (snapshot(os.fstat(stream.fileno())) != snapshot(initial)
                or snapshot(CHECKPOINT.stat()) != snapshot(initial)
                or len(raw) != initial.st_size):
            raise ValueError("checkpoint changed or exceeded read bound")
    if len(raw) > 1024*1024:
        raise ValueError("bounded synthetic checkpoint required")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate checkpoint key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite checkpoint constant")
    report = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)
    required = {"schema": "yblod.native-metadata-checkpoint.v1", "status": "complete",
        "synthetic_only": True, "gpu_attempted": False,
        "binary_sha256": "3957e0c4c55c8f9206841ab74e074902f3af73f531793f95d6a42279665d0d1b",
        "sdk_and_installed_libavutil_sha256": "16e16a2ab0f89a48c7e487d365e84f1c005f119fa8754c146daaeff40883c108"}
    if type(report) is not dict or any(type(report.get(k)) is not type(v) or report[k] != v for k, v in required.items()):
        raise ValueError("fixed synthetic checkpoint identity mismatch")
    if (type(report.get("source_sha256")) is not dict
            or report["source_sha256"].get("native_metadata_probe.c") != "80c002c2c67fba9886011fade103e7aa839937788866fa7aae20b9ae73c84841"):
        raise ValueError("executed C source checkpoint mismatch")
    dependencies = {"dvbridge_metadata.h": "da799ab08381318601bb0a3f8a1a74ed3293ca09b2cdde52228ea6f7e4c06d36",
        "mpv_dvbridge_cm4.h": "f6762808f5d7a5824983d72b0188098f19e86bd2a6db7b997ef63e2d35612661",
        "dovi_meta.h": "f860511cb8be3c992b4ef7da6747d8dc9670d64d276aeab3a7e6867112857a02"}
    if report.get("dependency_sha256") != dependencies:
        raise ValueError("executed header dependency mismatch")
    cases = report.get("cases")
    if type(cases) is not list or len(cases) != 9 or any(type(item) is not dict or item.get("case") != name for item, name in zip(cases, CASES)):
        raise ValueError("exact ordered nine-case synthetic checkpoint required")
    for case in cases:
        name = case["case"]
        expected_exit = 3 if name == "invalid-duplicate-l1" else 0
        if type(case.get("exit_status")) is not int or case["exit_status"] != expected_exit:
            raise ValueError("checkpoint native exit status mismatch")
        for field in ("stdout_sha256", "stderr_sha256"):
            if type(case.get(field)) is not str or not re.fullmatch("[0-9a-f]{64}", case[field]):
                raise ValueError("declared original log digest required")
        value = case.get("result")
        if (type(value) is not dict or value.get("schema") != "yblod.native-metadata-probe.v1"
                or value.get("synthetic_only") is not True or value.get("case") != name
                or type(value.get("records")) is not list
                or len(value["records"]) != (3 if name in ("repeat", "seek") else 1)):
            raise ValueError("checkpoint fixed native result mismatch")
        if case["stderr_sha256"] != hashlib.sha256(b"").hexdigest():
            raise ValueError("synthetic cohort expected empty stderr")
        for record in value["records"]:
            if type(record) is not dict:
                raise ValueError("native record required")
            for field in ("accepted", "committed", "failure_preserved_outer_state", "inner_mutated_on_failure"):
                if type(record.get(field)) is not bool:
                    raise ValueError("strict native status boolean required")
            for field in ("frames", "changes", "packet_count"):
                if type(record.get(field)) is not int or record[field] < 0:
                    raise ValueError("strict nonnegative native counter required")
            if record["packet_count"] > 4:
                raise ValueError("maximum four packets required")
            for field in ("payload_hex", "packet_hex"):
                maximum = 482*2 if field == "payload_hex" else 512*2
                if (type(record.get(field)) is not str or len(record[field]) > maximum
                        or not re.fullmatch("(?:[0-9a-f]{2})*", record[field])):
                    raise ValueError("strict synthetic byte hex required")
    return {case["case"]: case for case in cases}


def crc(data):
    value = 0xffffffff
    for byte in data:
        value ^= byte << 24
        for _ in range(8):
            value = ((value << 1) ^ (0x04c11db7 if value & 0x80000000 else 0)) & 0xffffffff
    return value


def decode(record):
    if type(record) is not dict or type(record.get("packet_count")) is not int or not 1 <= record["packet_count"] <= 4:
        raise ValueError("one to four transport packets required")
    for field, maximum in (("payload_hex", 482*2), ("packet_hex", 512*2)):
        if (type(record.get(field)) is not str or len(record[field]) > maximum
                or not re.fullmatch("(?:[0-9a-f]{2})*", record[field])):
            raise ValueError("bounded byte hex required before decoding")
    payload = bytes.fromhex(record["payload_hex"])
    packets = bytes.fromhex(record["packet_hex"])
    if len(payload) < 71 or len(payload) > 482 or len(packets) != 128*record["packet_count"]:
        raise ValueError("bounded complete synthetic payload and packet set required")
    count = record["packet_count"]
    assembled = bytearray()
    for index in range(count):
        packet = packets[128*index:128*(index+1)]
        if crc(packet) != 0:
            raise ValueError("packet CRC mismatch")
        if packet[0] >> 6 != (0 if count == 1 else 1 if index == 0 else 3 if index+1 == count else 2):
            raise ValueError("packet sequence tag mismatch")
        if packet[1] >> 4 != packet[1] & 15 or packet[1] != packets[1]:
            raise ValueError("packet identity mismatch")
        start = 5 if index == 0 else 3
        if index == 0 and int.from_bytes(packet[3:5], "big") != len(payload):
            raise ValueError("packet payload length mismatch")
        take = min(124-start, len(payload)-len(assembled))
        assembled.extend(packet[start:start+take])
        if any(packet[start+take:124]):
            raise ValueError("nonzero packet padding")
    if bytes(assembled) != payload:
        raise ValueError("assembled packet payload mismatch")
    position = 71
    extensions = []
    for _ in range(payload[70]):
        if position+5 > len(payload):
            raise ValueError("truncated extension header")
        length = int.from_bytes(payload[position:position+4], "big")
        level = payload[position+4]
        position += 5
        if position+length > len(payload):
            raise ValueError("truncated extension data")
        extensions.append((level, payload[position:position+length]))
        position += length
    if position != len(payload):
        raise ValueError("trailing extension bytes")
    return payload, extensions


class MetadataParserTests(unittest.TestCase):
    def test_crc_known_literal_and_malformed_bounds(self):
        # CRC-32/MPEG-2 known answer, not computed using the serializer helper.
        self.assertEqual(crc(b"123456789"), 0x0376e6e7)
        with self.assertRaises(ValueError):
            decode(dict(payload_hex="00", packet_hex="", packet_count=0))

    def test_public_checkpoint_location_and_schema_corruption_regressions(self):
        self.assertEqual(CHECKPOINT.parent, Path(__file__).parent / "results")
        original = json.loads(CHECKPOINT.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            for field, value in (("schema", "wrong"), ("gpu_attempted", 0), ("source_sha256", None),
                                 ("binary_sha256", "0"*64)):
                changed = dict(original, **{field: value})
                path.write_text(json.dumps(changed))
                with mock.patch(__name__+".CHECKPOINT", path), self.assertRaises(ValueError):
                    checkpoint_cases()
            for field, value in (("packet_count", 5), ("packet_count", True),
                                 ("payload_hex", "00"*483), ("packet_hex", "00"*513)):
                with self.assertRaises(ValueError):
                    decode(dict(original["cases"][0]["result"]["records"][0], **{field: value}))
            path.write_bytes(b'{"schema":1,"schema":2}')
            with mock.patch(__name__+".CHECKPOINT", path), self.assertRaises(ValueError):
                checkpoint_cases()
            # Preserve valid hex but damage the original C packet CRC.
            original["cases"][0]["result"]["records"][0]["packet_hex"] = (
                "01"+original["cases"][0]["result"]["records"][0]["packet_hex"][2:])
            path.write_text(json.dumps(original))
            with mock.patch(__name__+".CHECKPOINT", path):
                with self.assertRaisesRegex(ValueError, "CRC"):
                    decode(checkpoint_cases()["baseline"]["result"]["records"][0])

    def test_checkpoint_missing_nonregular_symlink_and_read_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "checkpoint.json"
            with mock.patch(__name__+".CHECKPOINT", path), self.assertRaises(FileNotFoundError):
                checkpoint_cases()
            with mock.patch(__name__+".CHECKPOINT", root), self.assertRaises((OSError, ValueError)):
                checkpoint_cases()
            path.write_bytes(b" "*(1024*1024+2))
            with mock.patch(__name__+".CHECKPOINT", path), self.assertRaises(ValueError):
                checkpoint_cases()
            link = root / "link.json"
            link.symlink_to(path)
            if hasattr(os, "O_NOFOLLOW"):
                with mock.patch(__name__+".CHECKPOINT", link), self.assertRaises(OSError):
                    checkpoint_cases()


@unittest.skipUnless(os.environ.get("YB_NATIVE_METADATA_PROBE") or os.environ.get("YB_NATIVE_METADATA_ARCHIVE") or CHECKPOINT.is_file(),
                     "matching-header synthetic serializer executable or actual-output archive required")
class NativeMetadataProbeTests(unittest.TestCase):
    def invoke(self, name, rejected=False):
        archive = os.environ.get("YB_NATIVE_METADATA_ARCHIVE")
        executable = os.environ.get("YB_NATIVE_METADATA_PROBE")
        if executable:
            executable = Path(executable).resolve(strict=True)
            result = subprocess.run([str(executable), name], capture_output=True, timeout=5, check=False)
        elif archive:
            root = Path(archive).resolve(strict=True) / "cases"
            result = subprocess.CompletedProcess(["archived", name],
                int((root / (name+".exit-status")).read_text()),
                (root / (name+".json")).read_bytes(), (root / (name+".stderr")).read_bytes())
        else:
            case = checkpoint_cases()[name]
            # These are saved, source-pinned C outputs: no current executable
            # or FFmpeg allocation occurs on this replay path.
            result = subprocess.CompletedProcess(["recorded-synthetic-replay", name],
                case["exit_status"], json.dumps(case["result"]).encode(), b"")
        self.assertEqual(result.returncode, 3 if rejected else 0, result.stderr.decode(errors="replace"))
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "yblod.native-metadata-probe.v1")
        self.assertIs(report["synthetic_only"], True)
        self.assertEqual(report["case"], name)
        for record in report["records"]:
            self.assertIs(record["accepted"], not rejected)
            self.assertIs(record["committed"], not rejected)
        return report["records"]

    def test_l1_and_l2_exact_preservation_without_source_colour_claim(self):
        baseline, ext = decode(self.invoke("baseline")[0])
        self.assertEqual(ext, [(1, bytes.fromhex("00000bb80200")), (5, b"\0"*8)])
        changed, changed_ext = decode(self.invoke("l1-changed")[0])
        self.assertEqual(changed_ext[0], (1, bytes.fromhex("00000bb80201")))
        self.assertEqual(baseline[:71], changed[:71])
        for name, slope in (("l2-added", "0800"), ("l2-changed", "0801")):
            _, values = decode(self.invoke(name)[0])
            self.assertEqual([level for level, _ in values], [1, 2, 5])
            self.assertEqual(values[1], (2, bytes.fromhex("09c4"+slope+"0800080008000800ffff")))

    def test_valid_raw_l8_grammar_converts_six_12bit_controls_to_words(self):
        for name, slope in (("l8-added", "0800"), ("l8-changed", "0801")):
            _, extensions = decode(self.invoke(name)[0])
            self.assertEqual([level for level, _ in extensions], [1, 5, 8])
            self.assertEqual(extensions[2], (8, bytes.fromhex("01"+slope+"0800"*5)))

    def test_repeat_and_discontinuity_scene_refresh(self):
        normal = self.invoke("repeat")
        seek = self.invoke("seek")
        normal_payloads = [decode(record)[0] for record in normal]
        seek_payloads = [decode(record)[0] for record in seek]
        self.assertEqual([payload[1] for payload in normal_payloads], [1, 1, 0])
        self.assertEqual([payload[1] for payload in seek_payloads], [1, 1, 1])
        self.assertEqual(normal_payloads[0], normal_payloads[1])
        self.assertEqual([record["frames"] for record in normal], [1, 2, 3])
        self.assertEqual([record["changes"] for record in normal], [0, 0, 1])
        self.assertEqual([record["changes"] for record in seek], [0, 0, 0])

    def test_rejection_preserves_outer_copy_not_inner_serializer_state(self):
        record = self.invoke("invalid-duplicate-l1", rejected=True)[0]
        self.assertIs(record["failure_preserved_outer_state"], True)
        self.assertIs(record["inner_mutated_on_failure"], True)
        self.assertEqual(record["frames"], 0)
        self.assertEqual(record["payload_hex"], "")
        self.assertEqual(record["packet_hex"], "")
        self.assertEqual(record["packet_count"], 0)


if __name__ == "__main__":
    unittest.main()
