"""Independent CPU/oracle baseline for future GPU differential fixtures."""
import tempfile
import json
import shutil
import struct
import subprocess
from pathlib import Path
import unittest

import native_stage
import native_gpu_probe
from native_gpu_vectors import vector_fixtures, expected_stages, width_oracle, WIDTH_LIMIT, triple_feature


class GPUVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.library = native_stage.build(Path(cls.temporary.name)/"build")
        here = Path(__file__).resolve().parent
        cls.validator = Path(cls.temporary.name)/"probe_validate"
        compiled = subprocess.run([shutil.which("cc"), "-std=c11", "-O2", "-Wall", "-Wextra",
            "-Werror", "-Wconversion", "-Wshadow", "-DYB_GPU_PROBE_HOST_ONLY",
            *(str(here/name) for name in ("native_gpu_probe.c", "native_gpu_probe_fixture.c",
                                          "native_composer.c", "native_gpu_guard.c")),
            "-o", str(cls.validator)], capture_output=True, text=True)
        if compiled.returncode:
            raise RuntimeError("host-only validator compilation failed: " + compiled.stderr)

    def validate_bytes(self, data):
        path = Path(self.temporary.name)/"fixture.bin"
        path.write_bytes(data)
        result = subprocess.run([str(self.validator), "--validate", str(path)],
                                capture_output=True, text=True, timeout=5)
        return result.returncode, json.loads(result.stdout)

    def test_every_four_stage_matches_native_cpu_even_width_rejected(self):
        fixtures = vector_fixtures()
        self.assertEqual(len({v.name for v in fixtures}), len(fixtures))
        for vector in fixtures:
            with self.subTest(vector=vector.name):
                engine = native_stage.NativeStage(self.library, vector.mapping,
                    None if vector.nlq is None else (vector.nlq,)*3, vector.output_depth,
                    disabled=vector.nlq is None)
                actual = engine.process(vector.component, vector.triplets, vector.el_samples)
                self.assertEqual(tuple(tuple(actual[name]) for name in
                    ("mapped", "residual", "sum", "reconstructed")), expected_stages(vector))

    def test_literal_pivot_and_signed_floor_known_answers(self):
        cases = {v.name: v for v in vector_fixtures()}
        self.assertEqual(expected_stages(cases["right-owned-pivots"])[0],
                         (4096, 4096, 4096, 4096, 8192, 8192, 16384, 16384, 16384, 16384))
        self.assertEqual(expected_stages(cases["negative-cap-before-floor"]),
                         ((32,)*5, (-9, -8, 0, 8, 8), (23, 24, 32, 40, 40), (1, 2, 2, 3, 3)))
        self.assertEqual(expected_stages(cases["cross-depth-bl8-el10"])[1],
                         (-8184, -8, 0, 8, 8168))
        self.assertEqual(expected_stages(cases["cross-depth-bl10-el8"])[1],
                         (-2040, -8, 0, 8, 2024))
        self.assertEqual(expected_stages(cases["mmr-mixed-pivot-right-and-guide-clamp"])[0],
                         (4096, 4096, 4096, 4096, 33728, 33728, 8192, 8192, 8192, 8192))
        self.assertEqual(expected_stages(cases["mmr-width-limit-signed-prefix-cancellation"])[0],
                         (32, 31, 31, 65535, 0))

    def test_width_boundary_expected_rejection_is_explicit(self):
        cases = {v.name: v for v in vector_fixtures()}
        for bound in (WIDTH_LIMIT-1, WIDTH_LIMIT, WIDTH_LIMIT+1):
            result = width_oracle(cases[f"mmr-width-{bound}"].mapping)
            self.assertEqual(result, dict(supported=bound <= WIDTH_LIMIT, mmr_segment_count=1,
                worst_l1_bound=bound, first_unsupported=(-1, -1) if bound <= WIDTH_LIMIT else (1, 0)))

    def test_negative_floor_identity_including_int64_min(self):
        # This establishes the exact shader helper contract. Neither negative
        # arithmetic shifts nor division truncation are accepted substitutes.
        values = tuple(range(-128, 129)) + (-2**63, -2**63+1, 2**63-1)
        for shift in range(37):
            for value in values:
                positive_shift_only = value >> shift if value >= 0 else -1-((-(value+1)) >> shift)
                self.assertEqual(positive_shift_only, value // (1 << shift))

    def test_serialized_all_vectors_host_only_cpu_and_rejection(self):
        for vector in vector_fixtures():
            with self.subTest(vector=vector.name):
                data = native_gpu_probe.encode(vector.mapping, vector.nlq, vector.component,
                                               vector.triplets, vector.el_samples, vector.output_depth)
                status, report = self.validate_bytes(data)
                width = width_oracle(vector.mapping)
                poly = all(s.method == "polynomial" for m in vector.mapping.mappings for s in m.segments)
                self.assertEqual(status, 0 if width["supported"] else 3)
                self.assertIs(report["gpu_attempted"], False)
                self.assertIs(report["accepted"], width["supported"])
                self.assertIs(report["algorithm_supported"], True)
                self.assertEqual(report["schema"], "yblod.native-gpu-probe.v2")
                self.assertIs(report["polynomial_only"], poly)
                self.assertEqual(report["width_report"], dict(supported=width["supported"],
                    mmr_segment_count=width["mmr_segment_count"], worst_l1_bound=width["worst_l1_bound"],
                    first_unsupported_component=width["first_unsupported"][0],
                    first_unsupported_segment=width["first_unsupported"][1]))
                self.assertEqual(report["cpu_stages"], [list(row) for row in zip(*expected_stages(vector))])

    def test_feature_floors_cannot_be_collapsed_even_at_unclipped_anchor(self):
        cases = {v.name: v for v in vector_fixtures()}
        for depth, order, basis in ((8, 3, "cube"), (10, 2, "square")):
            vector = cases[f"mmr{order}-cr-b{depth}-triple-{basis}-floor"]
            top = (1 << depth)-1
            anchor = (top, top-2, top-1)
            actual = expected_stages(vector)[0][vector.triplets.index(anchor)]
            self.assertEqual(actual, 32768)
            y, u, v = anchor
            collapsed = ((y*u*v)**order * (1 << 20)) // (1 << (3*depth*order))
            expected_feature = triple_feature(anchor, depth, order)
            self.assertNotEqual(collapsed, expected_feature)
            wrong_mapped = 32768 + 2*(collapsed-expected_feature)
            self.assertTrue(0 < wrong_mapped < 65535)
            self.assertNotEqual(wrong_mapped, actual)

    def test_host_only_malformed_binary_does_not_attempt_gpu(self):
        vector = next(v for v in vector_fixtures() if v.name == "cross-depth-bl8-el10")
        valid = native_gpu_probe.encode(vector.mapping, vector.nlq, vector.component,
                                         vector.triplets, vector.el_samples, vector.output_depth)
        corrupted = [valid[:length] for length in (0, 7, 8, 12, 63, 64, 136, 144, 152,
                                                    9111, 9112, len(valid)-1)]
        corrupted += [valid+b"\0", valid+valid, b"YBGPU02\0"+valid[8:]]
        for offset, value in ((8, 0), (8, 4097), (8, 2**32-1), (12, 3), (12, 2**32-1),
            (16, 2), (16, 0), (20, 16), (24, 9), (28, 33), (32, 9), (36, 1024),
            (64, 1), (72, 0), (76, 1), (136, 2), (140, 3), (324, 1),
            (9112, 256), (9112+12, 1024)):
            data = bytearray(valid)
            struct.pack_into("<I", data, offset, value)
            corrupted.append(bytes(data))
        for offset, value in ((40, 2 << 23), (144, -2**63), (168, 1)):
            data = bytearray(valid)
            struct.pack_into("<Q" if value >= 0 else "<q", data, offset, value)
            corrupted.append(bytes(data))
        swapped = bytearray(valid)
        swapped[8:12] = swapped[8:12][::-1]
        corrupted.append(bytes(swapped))
        # Independent EL8 domain must not be widened to the BL10 domain.
        other = next(v for v in vector_fixtures() if v.name == "cross-depth-bl10-el8")
        data = bytearray(native_gpu_probe.encode(other.mapping, other.nlq, other.component,
                                                 other.triplets, other.el_samples, other.output_depth))
        struct.pack_into("<I", data, 9112+12, 256)
        corrupted.append(bytes(data))
        disabled = next(v for v in vector_fixtures() if v.nlq is None)
        data = bytearray(native_gpu_probe.encode(disabled.mapping, None, disabled.component,
                                                 disabled.triplets, None, disabled.output_depth))
        struct.pack_into("<I", data, 9112+12, 1)
        corrupted.append(bytes(data))
        for data in corrupted:
            status, report = self.validate_bytes(data)
            self.assertEqual(status, 2)
            self.assertEqual(report["status"], "invalid-fixture")
            self.assertIs(report["gpu_attempted"], False)


if __name__ == "__main__":
    unittest.main()
