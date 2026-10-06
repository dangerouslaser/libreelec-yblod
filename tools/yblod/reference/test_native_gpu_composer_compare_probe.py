"""Source contract guards; runtime correctness still needs actual GPU evidence."""
from pathlib import Path
import unittest

source_path = Path(__file__).with_name("native_gpu_composer_compare_probe.c")
if not source_path.exists():
    source_path = Path(__file__).resolve().parents[3] / "engine/experimental/native_gpu_composer_compare_probe.c"
SOURCE = source_path.read_text()

class ComparisonContracts(unittest.TestCase):
    def test_distinct_schema(self):
        self.assertIn("yblod.native-gpu-composer-compare-probe.v1", SOURCE)
        self.assertNotIn("yblod.native-gpu-composer-image-probe.v1", SOURCE)

    def test_mismatches_are_measurements(self):
        self.assertNotIn("image_codes[(size_t)start+i]!=scratch->out[i])goto", SOURCE)
        for key in ("over_one", "signed_sum", "squared_error_sum", "abs_p99"):
            self.assertIn(key, SOURCE)
        self.assertIn("if(actual>maximum||expected>maximum)goto image_gate_cleanup", SOURCE)

    def test_dump_exclusive_outside_timing(self):
        self.assertIn('fopen(dump_path,"wbx")', SOURCE)
        self.assertIn("if(pass==0)", SOURCE)
        self.assertIn("if(dump){if(fclose(dump))ok=0", SOURCE)

    def test_reference_and_completion_unchanged(self):
        self.assertIn("native-integer-CPU-composer-not-licensed-hardware", SOURCE)
        self.assertIn("yb_integration_finish(&reference,&completion)", SOURCE)
        self.assertIn("yb_gpu_backend_finish(backend,UINT64_C(5000000000)", SOURCE)
        self.assertIn("yb_gpu_backend_abandon_destroyed_context", SOURCE)

    def test_percentile_rank_and_error_bounds(self):
        self.assertIn("if(absolute>=4096)goto image_gate_cleanup", SOURCE)
        self.assertIn("d->histogram[absolute]++", SOURCE)
        self.assertIn("(d->count*99U+99U)/100U", SOURCE)

if __name__ == "__main__":
    unittest.main()
