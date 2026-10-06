"""Compile and execute the actual bounded C manifest parser on the host.

The parser is extracted verbatim from the experimental backend. Compiler input
is supplied on stdin; no backend or generated C source file is edited.
"""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).parent

CASES = r'''
int main(void) {
    int v[17]={0};
#define EXPECT(input,count,want) do { \
    if (fp_manifest_values(input,v,count)!=(want)) { \
        fprintf(stderr,"unexpected parser result at test line %d\n",__LINE__); return 1; \
    } \
} while(0)
    EXPECT("9 1 3 0 2 1 1 0 1 0 2 1 3 0 1 0 0\n",17,1);
    if(v[0]!=9 || v[1]!=1 || v[2]!=3 || v[16]!=0)return 2;
    EXPECT(" \t0009\t01 3\n",3,1);
    EXPECT("0",1,1);
    EXPECT("1\n",1,1);
    EXPECT("1 2\n",1,0);
    EXPECT("1\n2",2,0);
    EXPECT("1",2,0);
    EXPECT("",1,0);
    EXPECT("\n",1,0);
    EXPECT("-1\n",1,0);
    EXPECT("+1\n",1,0);
    EXPECT("10\n",1,0);
    EXPECT("99999999999999999999999999999999999999999999999999999\n",1,0);
    EXPECT("1.0\n",1,0);
    EXPECT("1x\n",1,0);
    EXPECT("1\r\n",1,0);
    EXPECT("1\t \n",1,1);
    return 0;
}
'''


class ActualManifestParserTests(unittest.TestCase):
    def test_actual_c_parser_accepts_valid_and_rejects_malformed(self):
        compiler = shutil.which("cc")
        if not compiler:
            self.skipTest("host C compiler unavailable")
        source_path = HERE / "native_gpu_composer_backend_libplacebo.c"
        if not source_path.exists():
            source_path = HERE.resolve().parents[2] / "engine/experimental/native_gpu_composer_backend_libplacebo.c"
        backend = source_path.read_text()
        start = backend.index("static int fp_manifest_values(")
        stop = backend.index("static int fp_parse_shader(", start)
        parser = backend[start:stop]
        self.assertNotIn("sscanf", parser)
        source = "#include <stdio.h>\n" + parser + CASES
        with tempfile.TemporaryDirectory(prefix="yblod-parser-") as directory:
            executable = str(pathlib.Path(directory) / "parser-test")
            compiled = subprocess.run(
                [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                 "-x", "c", "-", "-o", executable],
                input=source, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            tested = subprocess.run([executable], capture_output=True, text=True, timeout=10)
            self.assertEqual(tested.returncode, 0, tested.stderr)


if __name__ == "__main__":
    unittest.main()
