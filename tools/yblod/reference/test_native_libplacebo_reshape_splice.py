import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "splice", HERE / "native_libplacebo_reshape_splice.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

FIXTURE = """#version 430 core
void main()
{
    int64_t total=int64_t(0);
    // Existing reshape operations.
    int64_t mapped=bound(floor_power_two(total,int(m[5])+4),int64_t(0),int64_t(65535));
    int64_t residual=int64_t(0);
    // Unchanged integer NLQ and final quantization.
}
"""
FRAGMENT = "float yb_libplacebo_reshape(uvec3 native_codes, int component) { return 0.5; }\n"


class SpliceTests(unittest.TestCase):
    def test_preserves_version_and_integer_tail(self):
        candidate = MODULE.splice(FIXTURE, FRAGMENT)
        self.assertTrue(candidate.startswith("#version 430 core\n"))
        original_tail = FIXTURE[FIXTURE.index("    int64_t residual="):]
        self.assertTrue(candidate.endswith(original_tail))
        self.assertIn("yb_libplacebo_reshape(sample_value.xyz,component)*65536.0", candidate)
        self.assertLess(candidate.index(FRAGMENT), candidate.index("void main()"))

    def test_refuses_changed_or_duplicate_markers(self):
        for text in (FIXTURE.replace("total=int64_t(0)", "total=0"), FIXTURE + FIXTURE):
            with self.assertRaises(ValueError):
                MODULE.splice(text, FRAGMENT)

    def test_refuses_unrecognized_fragment(self):
        with self.assertRaises(ValueError):
            MODULE.splice(FIXTURE, "void fake() {}")

    def test_runtime_generator_contract(self):
        source_path = HERE / "native_libplacebo_reshape_generate.c"
        if not source_path.exists():
            source_path = HERE.resolve().parents[2] / "engine/experimental/native_libplacebo_reshape_generate.c"
        source = source_path.read_text()
        self.assertIn('strcmp(argv[1],"--runtime")==0', source)
        self.assertIn('m[5]<int64_t(1) || m[5]>int64_t(32)', source)
        self.assertIn('float coefficient_scale=exp2(-float(m[5]))', source)
        self.assertIn('atomicOr(frame_error,4u); return 0.0;', source)
        self.assertIn('int expected=3+(pc>2?1:0)+(has_mmr?1:0);', source)
        self.assertIn('mm->var.dim_a!=packed', source)
        self.assertIn('p->var.dim_a!=7', source)
        self.assertIn('r->glsl,c', source)
        self.assertNotIn('strstr(r->glsl', source)

    def test_uniform_generator_and_backend_contract(self):
        source_directory = HERE
        if not (source_directory / "native_libplacebo_reshape_generate.c").exists():
            source_directory = HERE.resolve().parents[2] / "engine/experimental"
        source = (source_directory / "native_libplacebo_reshape_generate.c").read_text()
        backend = (source_directory / "native_gpu_composer_backend_libplacebo.c").read_text()
        self.assertIn('strcmp(argv[1],"--uniforms-native-output-range")==0', source)
        self.assertIn('YB_FP_OUTPUT_RANGE_NATIVE', source)
        self.assertIn('#define %s yb_fp_c%d_%s', source)
        self.assertIn('fp_cache_locations(b)', backend)
        upload = backend[backend.index('static void fp_upload'):backend.index('static int same_context')]
        self.assertNotIn('GetUniformLocation', upload)
        self.assertIn('ldexp((double)words', upload)
        self.assertIn('Uniform4fv(loc[2],packed', upload)
        submit = backend[backend.index('int yb_gpu_backend_submit'):backend.index('int yb_gpu_backend_finish')]
        self.assertLess(submit.index('fp_same_topology'), submit.index('b->valid=0'))
        self.assertLess(submit.index('fp_upload(b,c,words)'), submit.index('g->DispatchCompute'))


if __name__ == "__main__":
    unittest.main()
