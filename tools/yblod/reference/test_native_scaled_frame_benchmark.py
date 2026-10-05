"""Synthetic C-only benchmark guards; timings are not playback performance."""
import ctypes as C
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import test_native_scaled_surface_chain as surface_chain

ROOT = Path(__file__).resolve().parent


class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = Path(cls.directory.name) / "benchmark"
        subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-Wconversion", "-Wshadow", *(str(ROOT / name) for name in
            ("native_scaled_frame_benchmark.c", "native_scaled_surface.c",
             "native_decoder_frame_bridge.c", "native_integration_probe.c",
             "native_composer.c", "native_sampling_probe.c")), "-o", str(cls.binary)],
             check=True, capture_output=True)

    def fixture(self, directory):
        _, _, _, _, _, instructions, _ = surface_chain.SurfaceChainTests().fixture()
        paths = [directory / name for name in ("blob", "Y", "Cb", "Cr", "guide", "p010")]
        payloads = [bytes(instructions), struct.pack("<4H", 512, 513, 511, 514),
                    struct.pack("<H", 512), struct.pack("<H", 512),
                    struct.pack("<H", 512), struct.pack("<6H", *(v * 64 for v in (512, 513, 511, 514, 513, 510)))]
        for path, payload in zip(paths, payloads):
            with path.open("xb") as stream: stream.write(payload)
        return paths, instructions

    def invoke(self, paths, dimensions=("2", "2")):
        return subprocess.run([str(self.binary), *dimensions, *(str(p) for p in paths)],
                              capture_output=True, text=True, timeout=3)

    def rejected(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_successful_warmup_three_complete_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, _ = self.fixture(Path(temporary))
            result = self.invoke(paths)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["counts"], [4, 1, 1])
            self.assertEqual((report["warmup"], report["repeats"]), (1, 3))
            self.assertEqual(len(report["nanoseconds"]), 3)
            self.assertTrue(all(type(n) is int and n >= 0 for n in report["nanoseconds"]))

    def test_fractional_late_surface_and_late_bad_bl(self):
        for fault in ("fractional", "bad_bl", "size"):
            with tempfile.TemporaryDirectory() as temporary:
                paths, _ = self.fixture(Path(temporary))
                index = 5 if fault == "fractional" else 1
                raw = bytearray(paths[index].read_bytes())
                if fault == "fractional": raw[-2] |= 1
                elif fault == "bad_bl": raw[-2:] = struct.pack("<H", 1024)
                else: raw.append(0)
                with paths[index].open("wb") as stream: stream.write(raw)
                self.rejected(self.invoke(paths))

    def test_invalid_instructions_and_luma_mmr_rejected(self):
        for fault in ("version", "depth", "mmr"):
            with tempfile.TemporaryDirectory() as temporary:
                paths, instructions = self.fixture(Path(temporary))
                if fault == "version": instructions.version = 2
                elif fault == "depth": instructions.depth = 8
                else: instructions.mapping.components[0].segments[0].method = 1
                with paths[0].open("wb") as stream: stream.write(bytes(instructions))
                self.rejected(self.invoke(paths))

    def test_symlink_fifo_and_wrong_source_size_fail_without_hang(self):
        for fault in ("symlink", "fifo", "alias", "hardlink"):
            with tempfile.TemporaryDirectory() as temporary:
                paths, _ = self.fixture(Path(temporary))
                if fault == "alias": paths[2] = paths[3]
                elif fault == "hardlink":
                    paths[2].unlink()
                    os.link(paths[3], paths[2])
                else:
                    paths[0].unlink()
                    if fault == "symlink": paths[0].symlink_to(paths[1])
                    else: os.mkfifo(paths[0])
                self.rejected(self.invoke(paths))

    def test_invalid_dimensions_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, _ = self.fixture(Path(temporary))
            for dims in (("0", "2"), ("3", "2"), ("3842", "2"),
                         ("2", "2162"), ("-2", "2"), ("2x", "2")):
                self.rejected(self.invoke(paths, dims))


if __name__ == "__main__": unittest.main()
