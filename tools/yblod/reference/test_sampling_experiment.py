import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

import chroma_geometry
from extract_frame import digest
from output_frame import convert, expand_left, pack
from sampling_experiment import active_rectangle, experiment, main
import test_inverse_stage


class SamplingExperimentTests(unittest.TestCase):
    def setUp(self):
        self.base = test_inverse_stage.InverseBundleTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.fixture = self.base.fixture
        f = self.fixture
        self.base.dm["cmv29_metadata"] = {"ext_metadata_blocks": [{"Level5": {
            "active_area_left_offset": 0, "active_area_right_offset": 0,
            "active_area_top_offset": 48, "active_area_bottom_offset": 0}}]}
        patcher = patch("sampling_experiment.provenance", return_value=(self.base.report, self.base.dm, self.base.identity))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.update_baseline()

    def update_baseline(self):
        f = self.fixture
        arrays = []
        for name in ("Y", "Cb", "Cr"):
            shape = (f.h, f.w) if name == "Y" else (f.h//2, f.w//2)
            record = self.base.report["stages"]["reconstructed_" + name]
            path = self.base.result / record["file"]
            record["sha256"] = digest(path)
            a = np.frombuffer(path.read_bytes(), dtype="<u2").reshape(shape)
            arrays.append(a if name == "Y" else expand_left(a))
        (self.base.result / "report.json").write_text(json.dumps(self.base.report))
        # Independent legacy baseline uses output_frame.expand_left, never the
        # experimental geometry helper, and includes the inactive border.
        codes = convert(np.stack(arrays, axis=-1), self.base.dm, "direct", lambda *_: None)
        rectangle = active_rectangle(self.base.dm, f.w, f.h)
        left, top, right, bottom = rectangle
        codes[:top] = codes[bottom:] = [0, 2048, 2048]
        codes[:, :left] = codes[:, right:] = [0, 2048, 2048]
        path = f.output / "tunnel.rgb8"
        path.write_bytes(pack(codes).tobytes())
        f.fixture.alter(f.output, "output.json", lambda info: info.update(
            source_dm=self.base.dm, composer_report_sha256=digest(self.base.result / "report.json")))
        f.fixture.alter(f.output, "output.json", lambda info: info["stages"]["unembedded_tunnel"].update(sha256=digest(path)))

    def test_odd_top_nonzero_left_and_independent_chroma_channels(self):
        f = self.fixture
        self.base.dm["cmv29_metadata"]["ext_metadata_blocks"][0]["Level5"].update(
            active_area_left_offset=2, active_area_right_offset=4,
            active_area_top_offset=49, active_area_bottom_offset=0)
        rect = [2, 49, f.w-4, f.h]
        f.fixture.alter(f.output, "output.json", lambda info: info.update(active_rectangle=rect))
        def update_comparison(comparison):
            comparison["active_rectangle"] = rect
            for name, divisor in (("I", 1), ("P", 2), ("T", 2)):
                comparison["channels"][name]["samples"] = (rect[2]-rect[0])*(rect[3]-rect[1])//divisor
        f.fixture.alter(f.output, "sk4.json", update_comparison)
        self.update_baseline()
        before = self.run_experiment()
        f.c[49, 2] += 7  # P at x2.
        f.c[50, 3] -= 9  # T stored at x3, co-sited with x2.
        f.update_capture()
        after = self.run_experiment()
        for channel, divisor in (("I", 1), ("P", 2), ("T", 2)):
            first = before["variants"]["linear-left"]["comparisons"]["versus_capture"][channel]
            last = after["variants"]["linear-left"]["comparisons"]["versus_capture"][channel]
            width = (f.w-6)//divisor
            self.assertEqual(last["even_row"]["samples"], 41*width)
            self.assertEqual(last["odd_row"]["samples"], 42*width)
            delta_sum = (last["all"]["mean_signed_codes"]-first["all"]["mean_signed_codes"])*last["all"]["samples"]
            self.assertAlmostEqual(delta_sum, {"I": 0, "P": -7, "T": 9}[channel], places=7)

    def run_experiment(self):
        return experiment(self.fixture.output, self.base.result, self.base.extraction, self.fixture.capture)

    def args(self, report):
        return [str(self.fixture.output), str(self.base.result), str(self.base.extraction), str(self.fixture.capture), "--report", str(report)]

    def test_constant_planes_all_variants_unchanged_and_masks_partition(self):
        report = self.run_experiment()
        f = self.fixture
        self.assertEqual(report["baseline"]["verified_bytes"], f.h*f.w*3)
        for variant in report["variants"].values():
            for name, divisor in (("I", 1), ("P", 2), ("T", 2)):
                groups = variant["comparisons"]["minus_baseline"][name]
                self.assertEqual(groups["all"]["maximum_absolute_codes"], 0)
                self.assertEqual(groups["all"]["samples"], f.w*(f.h-48)//divisor)
                self.assertEqual(groups["even_row"]["samples"] + groups["odd_row"]["samples"], groups["all"]["samples"])
        self.assertTrue(report["metadata"]["all_crc_valid"])

    def test_vertical_change_is_local_to_variants_and_preserves_baseline(self):
        f = self.fixture
        path = self.base.result / "reconstructed_Cb.raw"
        samples = np.broadcast_to(950 + (np.arange(f.h//2) % 2)[:, None]*150, (f.h//2, f.w//2))
        path.write_bytes(samples.astype("<u2").tobytes())
        self.update_baseline()
        report = self.run_experiment()
        self.assertTrue(report["baseline"]["byte_identical"])
        self.assertEqual(report["variants"]["linear-left"]["comparisons"]["minus_baseline"]["P"]["all"]["maximum_absolute_codes"], 0)
        for variant in ("linear-top-control", "linear-bottom-control"):
            self.assertGreater(report["variants"][variant]["comparisons"]["minus_baseline"]["P"]["all"]["mean_absolute_codes"], 0)

    def test_baseline_mismatch_refuses_success_report(self):
        f = self.fixture
        path = f.output / "tunnel.rgb8"
        data = bytearray(path.read_bytes())
        data[0] ^= 1  # Inactive border must be verified as well.
        path.write_bytes(data)
        f.fixture.alter(f.output, "output.json", lambda info: info["stages"]["unembedded_tunnel"].update(sha256=digest(path)))
        report = f.root / "should-not-exist.json"
        with self.assertRaises(SystemExit):
            main(self.args(report))
        self.assertFalse(report.exists())

    def test_capture_masks_are_identical_across_all_variants_and_have_halo(self):
        f = self.fixture
        f.y[80:] = 200
        f.update_capture()
        report = self.run_experiment()
        for variant in report["variants"].values():
            groups = variant["comparisons"]["versus_capture"]["I"]
            self.assertEqual(groups["edge_gt_16"]["samples"], 2*f.w)
            self.assertEqual(groups["smooth_le_4"]["samples"], f.w*(f.h-48)-2*f.w)
        reference = report["variants"]["linear-left"]["comparisons"]["versus_capture"]
        for variant in report["variants"].values():
            for channel, groups in variant["comparisons"]["versus_capture"].items():
                self.assertEqual({g: v["samples"] for g, v in groups.items()},
                                 {g: v["samples"] for g, v in reference[channel].items()})

    def test_expansion_requests_are_striped(self):
        original = chroma_geometry.expand
        sizes = []
        def spy(plane, start=0, stop=None, variant="linear-left"):
            sizes.append(stop-start)
            return original(plane, start=start, stop=stop, variant=variant)
        with patch("sampling_experiment.chroma_geometry.expand", side_effect=spy):
            self.run_experiment()
        self.assertTrue(sizes)
        self.assertLessEqual(max(sizes), 32)

    def test_source_active_area_mismatch_rejected(self):
        self.base.dm["cmv29_metadata"]["ext_metadata_blocks"][0]["Level5"]["active_area_top_offset"] = 50
        self.fixture.fixture.alter(self.fixture.output, "output.json", lambda info: info.update(source_dm=self.base.dm))
        with self.assertRaisesRegex(ValueError, "active rectangles"):
            self.run_experiment()

    def test_changed_rpu_rejected(self):
        (self.base.extraction / "rpu.json").write_text("changed")
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.run_experiment()

    def test_candidate_domain_failure_names_variant_rows_and_writes_nothing(self):
        import sampling_experiment
        original = sampling_experiment.produce
        def fail_cubic(planes, dm, variant, start, stop, rectangle):
            if variant == "cubic-left":
                raise ValueError("test inverse-transfer domain failure")
            return original(planes, dm, variant, start, stop, rectangle)
        with patch("sampling_experiment.produce", side_effect=fail_cubic):
            with self.assertRaisesRegex(ValueError, r"cubic-left, rows \[32, 64\)"):
                self.run_experiment()
            destination = self.fixture.root / "failed-candidate.json"
            with self.assertRaises(SystemExit):
                main(self.args(destination))
            self.assertFalse(destination.exists())

    def test_capture_corruption_rejected(self):
        self.fixture.capture.write_bytes(bytes(self.fixture.h*self.fixture.w*3))
        with self.assertRaisesRegex(ValueError, "capture integrity"):
            self.run_experiment()

    def test_input_plane_out_of_range_rejected(self):
        path = self.base.result / "reconstructed_Y.raw"
        path.write_bytes(np.full((self.fixture.h, self.fixture.w), 4096, dtype="<u2").tobytes())
        self.base.report["stages"]["reconstructed_Y"]["sha256"] = digest(path)
        with self.assertRaisesRegex(ValueError, "12-bit storage"):
            self.run_experiment()

    def test_report_is_only_new_artifact_and_not_overwritten(self):
        f = self.fixture
        before = set(f.root.rglob("*"))
        report = f.root / "sampling.json"
        main(self.args(report))
        self.assertEqual(set(f.root.rglob("*"))-before, {report})
        original = report.read_bytes()
        with self.assertRaises(SystemExit):
            main(self.args(report))
        self.assertEqual(report.read_bytes(), original)

    def test_active_area_requires_exactly_one_block(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            active_rectangle({"cmv29_metadata": {"ext_metadata_blocks": []}}, 128, 132)


if __name__ == "__main__":
    unittest.main()
