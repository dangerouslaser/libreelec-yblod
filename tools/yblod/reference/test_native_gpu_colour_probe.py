"""Contract checks only; no shader execution, driver or accuracy claims."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class ColourShaderContract(unittest.TestCase):
    def test_declares_no_target_defaults_and_every_stage(self):
        shader = (ROOT / "native_gpu_colour_probe.comp").read_text()
        for name in ("source_ycc", "source_offset", "source_lms", "target_lms_inverse", "target_ycc_inverse", "target_offset", "pq_policy", "code_scale"):
            self.assertRegex(shader, rf"uniform\s+\w+\s+{name}\s*;")
        for name in ("source_nonlinear", "common_linear_lms", "target_linear", "transport_before_quantization", "status_codes"):
            self.assertIn(name, shader)
        self.assertIn("matrix[col][row]", shader)

    def test_rejects_domain_failures_without_float_epsilon(self):
        shader = (ROOT / "native_gpu_colour_probe.comp").read_text()
        self.assertIn("denominator<=0", shader)
        self.assertIn("pq_policy==0&&(v<0||v>1)", shader)
        self.assertIn("result.status_codes.x=3", shader)
        self.assertIn("code_scale!=4096", shader)
        self.assertNotIn("epsilon", shader)
        self.assertNotIn("SK4", shader)

    def test_bounded_output_and_no_integer64_requirement(self):
        shader = (ROOT / "native_gpu_colour_probe.comp").read_text()
        self.assertIn("index>=sample_count", shader)
        self.assertIn("rounded>4095?4095", shader)
        self.assertIn("floor(unrounded)", shader)
        self.assertIn("finite_value(unrounded)", shader)
        self.assertNotIn("int64", shader)
        self.assertNotIn("texture(", shader)
        self.assertNotIn("texelFetch", shader)
