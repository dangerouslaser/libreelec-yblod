"""Independent source-layout guards; not substitutes for runtime GPU tests."""
from pathlib import Path
import unittest

ROOT = Path("/private/tmp/yblod-libplacebo-prototype")
repository_sources = Path(__file__).resolve().parents[3] / "engine/experimental"
if (repository_sources / "native_gpu_composer_backend_libplacebo.c").exists():
    ROOT = repository_sources
BACKEND = (ROOT / "native_gpu_composer_backend_libplacebo.c").read_text()
GENERATOR = (ROOT / "native_libplacebo_reshape_generate.c").read_text()

class UniformContracts(unittest.TestCase):
    def test_topology_guard_before_submit_gl(self):
        submit = BACKEND.split("int yb_gpu_backend_submit(", 1)[1]
        self.assertLess(submit.index("if(!fp_same_topology(b,p))"), submit.index("g->GetError()"))

    def test_capacity_matches_maximum_layout(self):
        self.assertIn("mmr[48][4]", BACKEND)
        self.assertEqual(8 * 3 * 2, 48)
        self.assertIn("offset+3+r*7+(group?3+k:k)", BACKEND)
        self.assertIn("if(group||k!=3)", BACKEND)

    def test_upload_before_dispatch(self):
        submit = BACKEND.split("int yb_gpu_backend_submit(", 1)[1]
        self.assertLess(submit.index("fp_upload(b,c,words)"), submit.index("g->DispatchCompute"))
        self.assertIn("g->Uniform4fv(loc[2],packed,&mmr[0][0])", BACKEND)

    def test_explicit_clamp_control(self):
        self.assertIn("--uniforms-native-output-range", GENERATOR)
        self.assertIn("b->fp_native_output?1.0f", BACKEND)
        self.assertIn("b->fp_native_output?0.0f", BACKEND)

    def test_sync_and_abort_contract(self):
        self.assertIn("b->pending=1", BACKEND)
        self.assertIn("if(!b->fence||g->GetError()!=GL_NO_ERROR){b->failed=1", BACKEND)
        self.assertIn("yb_gpu_backend_abandon_destroyed_context", BACKEND)

if __name__ == "__main__":
    unittest.main()
