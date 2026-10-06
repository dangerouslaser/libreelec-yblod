"""Source guards for the isolated same-context numerical-update diagnostic."""
from pathlib import Path
import unittest

source_path = Path(__file__).with_name("native_gpu_composer_sequence_probe.c")
if not source_path.exists():
    source_path = Path(__file__).resolve().parents[3] / "engine/experimental/native_gpu_composer_sequence_probe.c"
SOURCE = source_path.read_text()

class SequenceContracts(unittest.TestCase):
    def test_same_objects_and_metadata_switch(self):
        self.assertIn("pass==1?alternate:base_blob", SOURCE)
        self.assertIn("sequence_work.blob=selected_instructions;plan.mapping=selected_instructions->mapping", SOURCE)
        self.assertIn("plan.nlq[c]=selected_instructions->nlq[c]", SOURCE)
        self.assertEqual(SOURCE.count("yb_gpu_backend_create(&create,&backend)"), 1)

    def test_both_cpu_oracles(self):
        self.assertIn("verify_frame(&alternate_work", SOURCE)
        self.assertIn("yb_decoder_frame_bridge_init(&reference,&w->descriptor,w->blob,9216)", SOURCE)

    def test_change_and_restoration_required(self):
        self.assertIn("!(changed_from_a[0]+changed_from_a[1]+changed_from_a[2])", SOURCE)
        self.assertIn("restoration_mismatches[0]||restoration_mismatches[1]||restoration_mismatches[2]", SOURCE)
        self.assertIn("image_codes[j]!=initial_codes[plane_start+j]", SOURCE)

    def test_readbacks_not_in_timed_passes(self):
        self.assertIn("if(pass<3){", SOURCE)
        self.assertIn("if(pass>=4){", SOURCE)
        self.assertIn("times[pass-4].wall", SOURCE)
        self.assertIn("sequence_reference_metrics", SOURCE)

if __name__ == "__main__":
    unittest.main()
