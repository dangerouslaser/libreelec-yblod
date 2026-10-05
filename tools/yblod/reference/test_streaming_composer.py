import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from make_demo import make_demo
import streaming_composer as stream


class StreamingComposerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / "input"
        self.manifest = make_demo(self.bundle)
        self.manifest_path = self.bundle / "frame.json"
        self.output = self.root / "output"

    def save(self):
        self.manifest_path.write_text(json.dumps(self.manifest))

    def no_completion(self):
        self.assertFalse((self.output / "report.json").exists())

    def test_success_stage_counts_hashes_and_little_endian(self):
        result = stream.run(self.manifest_path, self.output, chunk_samples=3)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["stages"]), 12)
        self.assertEqual(len(result["input_sha256"]), 6)
        self.assertEqual(set(result["helper_sha256"]),
                         {"reference.py", "base_mapping_stage.py", "nlq_stage.py", "composition_stage.py"})
        for name, stage in result["stages"].items():
            data = (self.output / stage["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), stage["sha256"])
            self.assertEqual(stage["samples"], 8 if name.endswith("_Y") else 2)
            self.assertEqual(len(data), stage["samples"] * (4 if name.startswith(("sum_", "residual_")) else 2))
        # Last Y enhancement value513 with slope1024,D20 produces32 correction.
        self.assertEqual((self.output / "residual_Y.i32le").read_bytes()[-4:], b"\x20\x00\x00\x00")
        self.assertEqual(json.loads((self.output / "report.json").read_text()), result)
        self.assertFalse((self.output / "report.pending.json").exists())

    def test_bad_chunk_configuration(self):
        for size in (True, 0, -1, 65537, 1.0):
            with self.assertRaises(ValueError): stream.run(self.manifest_path, self.output, chunk_samples=size)
            self.no_completion()

    def test_missing_short_extra_and_native_depth_rejected(self):
        plane = self.bundle / "bl_Y.u16le"
        original = plane.read_bytes()
        for payload in (original[:-1], original + b"\0\0", b"\0\x04" + original[2:]):
            plane.write_bytes(payload)
            destination = self.root / f"bad-{len(payload)}-{payload[1]}"
            with self.assertRaises(ValueError): stream.run(self.manifest_path, destination, chunk_samples=1)
            self.assertFalse((destination / "report.json").exists())
        plane.unlink()
        with self.assertRaises(OSError): stream.run(self.manifest_path, self.output)
        self.no_completion()

    def test_escape_and_extra_plane_declarations(self):
        outside = self.root / "outside.u16le"
        outside.write_bytes((self.bundle / "bl_Y.u16le").read_bytes())
        link = self.bundle / "escape.u16le"
        link.symlink_to(outside)
        for name in (str(outside), "../outside.u16le", "escape.u16le"):
            self.manifest["bl"]["planes"]["Y"] = name
            self.save()
            with self.assertRaises(ValueError): stream.run(self.manifest_path, self.output)
            self.no_completion()
        self.manifest["bl"]["planes"]["Y"] = "bl_Y.u16le"
        self.manifest["bl"]["planes"]["alpha"] = "unused"
        self.save()
        with self.assertRaises(ValueError): stream.run(self.manifest_path, self.output)

    def test_global_identity_and_mmr_guide_validation(self):
        self.manifest["el"]["pts"] += 1
        self.save()
        with self.assertRaises(ValueError): stream.run(self.manifest_path, self.output)
        self.manifest["el"]["pts"] -= 1
        self.manifest["metadata"]["mappings"][1]["segments"][0] = {
            "method": "mmr", "constant": 0, "coefficients": [[0] * 7]}
        self.save()
        with self.assertRaisesRegex(ValueError, "guide"): stream.run(self.manifest_path, self.output)
        self.manifest["mmr_luma"] = "guide.u16le"
        (self.bundle / "guide.u16le").write_bytes(b"\0\0")
        self.save()
        with self.assertRaises(ValueError): stream.run(self.manifest_path, self.output)
        self.no_completion()

    def test_explicit_disable_does_not_touch_enhancement(self):
        self.manifest["metadata"]["disable_residual"] = True
        self.manifest["el"] = None
        for channel in stream.CHANNELS:
            (self.bundle / f"el_{channel}.u16le").unlink()
        self.save()
        with mock.patch.object(stream.nlq, "correction", side_effect=AssertionError("disabled NLQ invoked")):
            result = stream.run(self.manifest_path, self.output, chunk_samples=1)
        self.assertEqual(len(result["input_sha256"]), 3)
        self.assertTrue(all(stage["minimum"] == stage["maximum"] == 0
                            for name, stage in result["stages"].items() if name.startswith("residual_")))

    def test_existing_output_is_untouched(self):
        self.output.mkdir()
        sentinel = self.output / "keep"
        sentinel.write_bytes(b"unchanged")
        with self.assertRaises(FileExistsError): stream.run(self.manifest_path, self.output)
        self.assertEqual(sentinel.read_bytes(), b"unchanged")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_reader_detects_early_eof_extra_bytes_and_same_size_change(self):
        filename = "bl_Y.u16le"
        path = self.bundle / filename
        original = path.read_bytes()
        for mode in ("truncate", "append", "rewrite", "replace"):
            path.write_bytes(original)
            reader = stream.PlaneReader(self.bundle, filename, 8, 10)
            try:
                reader.read(1)
                if mode == "truncate":
                    path.write_bytes(b"\0\0")
                elif mode == "append":
                    with path.open("ab") as handle: handle.write(b"\0\0")
                elif mode == "rewrite":
                    path.write_bytes(b"\x01\x00" + original[2:])
                else:
                    replacement = self.bundle / "replacement"
                    replacement.write_bytes(original)
                    replacement.replace(path)
                with self.assertRaises(ValueError):
                    reader.read(7)
                    reader.finish()
            finally:
                reader.close()

    def test_reader_consumption_required_and_no_whole_plane_reads(self):
        reader = stream.PlaneReader(self.bundle, "bl_Y.u16le", 8, 10)
        try:
            with self.assertRaises(ValueError): reader.finish()
            for count in (0, True, 65537, 9):
                with self.assertRaises(ValueError): reader.read(count)
        finally:
            reader.close()
        original_read = stream.PlaneReader.read
        original_write = stream.StageWriter.write
        counts = []
        written = []
        def checked_read(reader, count):
            counts.append(count)
            self.assertLessEqual(count, 3)
            return original_read(reader, count)
        def checked_write(writer, values):
            written.append(len(values))
            self.assertLessEqual(len(values), 3)
            return original_write(writer, values)
        with mock.patch.object(stream.PlaneReader, "read", checked_read), mock.patch.object(stream.StageWriter, "write", checked_write):
            stream.run(self.manifest_path, self.output, chunk_samples=3)
        self.assertGreater(len(counts), 6)
        self.assertGreater(len(written), 12)

    def test_midstream_io_and_input_change_leave_no_report(self):
        original_read = stream.PlaneReader.read
        calls = 0
        def changed(reader, count):
            nonlocal calls
            result = original_read(reader, count)
            calls += 1
            if calls == 1:
                data = reader.path.read_bytes()
                reader.path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
            return result
        with mock.patch.object(stream.PlaneReader, "read", changed):
            with self.assertRaises(ValueError): stream.run(self.manifest_path, self.output, chunk_samples=1)
        self.no_completion()
        second = self.root / "io-failed"
        with mock.patch.object(stream.StageWriter, "write", side_effect=OSError("test output failure")):
            with self.assertRaises(OSError): stream.run(self.manifest_path, second)
        self.assertFalse((second / "report.json").exists())

    def test_signed_storage_overflow_rejected_not_wrapped(self):
        with mock.patch.object(stream.nlq, "correction", return_value=1 << 31):
            with self.assertRaisesRegex(ValueError, "i32le storage"): stream.run(self.manifest_path, self.output)
        self.no_completion()
        destination = self.root / "sum-overflow"
        with mock.patch.object(stream.nlq, "correction", return_value=(1 << 31) - 1):
            with self.assertRaisesRegex(ValueError, "sum_Y"): stream.run(self.manifest_path, destination)
        self.assertFalse((destination / "report.json").exists())

    def test_manifest_bound_and_publication_failure(self):
        self.manifest_path.write_bytes(b" " * ((8 << 20) + 1))
        with self.assertRaises(ValueError): stream.run(self.manifest_path, self.output)
        self.no_completion()
        self.save()
        with mock.patch.object(stream.os, "link", side_effect=OSError("test publication failure")):
            with self.assertRaises(OSError): stream.run(self.manifest_path, self.output)
        self.no_completion()
        self.assertTrue((self.output / "report.pending.json").exists())

    def test_published_report_survives_temporary_cleanup_failure(self):
        original_unlink = Path.unlink
        def fail_pending(path, *args, **kwargs):
            if path == self.output / "report.pending.json":
                raise OSError("test pending cleanup failure")
            return original_unlink(path, *args, **kwargs)
        with mock.patch.object(Path, "unlink", fail_pending):
            result = stream.run(self.manifest_path, self.output)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(json.loads((self.output / "report.json").read_text()), result)
        self.assertTrue((self.output / "report.pending.json").exists())

    def test_consistent_input_alias_hashed_once(self):
        self.manifest["bl"]["planes"]["Cr"] = "bl_Cb.u16le"
        self.save()
        result = stream.run(self.manifest_path, self.output)
        self.assertEqual(len(result["input_sha256"]), 5)
        self.assertEqual(result["input_sha256"]["bl_Cb.u16le"],
                         hashlib.sha256((self.bundle / "bl_Cb.u16le").read_bytes()).hexdigest())
        self.assertEqual((self.output / "mapped_Cb.u16le").read_bytes(),
                         (self.output / "mapped_Cr.u16le").read_bytes())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX regular-file check")
    def test_nonregular_plane_rejected_without_blocking(self):
        fifo = self.bundle / "named-pipe"
        os.mkfifo(fifo)
        self.manifest["bl"]["planes"]["Y"] = fifo.name
        self.save()
        with self.assertRaisesRegex(ValueError, "regular file"):
            stream.run(self.manifest_path, self.output)
        self.no_completion()


if __name__ == "__main__":
    unittest.main()
