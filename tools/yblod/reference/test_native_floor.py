"""Probe the private signed-wide floor helper, including its full type limits."""
import ctypes as C
import json
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest


class NativeFloorTests(unittest.TestCase):
    def test_exact_floor_without_negative_shifts_or_wide_division(self):
        compiler = shutil.which("cc")
        if not compiler:
            raise RuntimeError("native floor verification requires a C compiler")
        source = Path(__file__).resolve().parent / "native_composer.c"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe.c"
            probe.write_text('#include ' + json.dumps(str(source)) + '''
void floor_probe(int64_t high, uint64_t low, uint32_t shift,
                 uint64_t *output_high, uint64_t *output_low)
{
    const yb_wide value = (yb_wide)high * ((yb_wide)1 << 64) + low;
    const unsigned __int128 result = (unsigned __int128)floor_div_power2(value, shift);
    *output_high = (uint64_t)(result >> 64);
    *output_low = (uint64_t)result;
}
''')
            library = root / "probe.so"
            built = subprocess.run([compiler, "-std=c11", "-O2", "-fPIC", "-shared",
                            "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
                            "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
                            str(probe), "-o", str(library)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            loaded = C.CDLL(str(library))
            function = loaded.floor_probe
            function.argtypes = [C.c_int64, C.c_uint64, C.c_uint32,
                                 C.POINTER(C.c_uint64), C.POINTER(C.c_uint64)]
            function.restype = None
            rng = random.Random(2296)
            values = [-(1 << 127), (1 << 127)-1, -1, 0, 1]
            values += [sign*((1 << exponent)+offset)
                       for exponent in (4, 32, 63, 64, 100, 126)
                       for offset in (-1, 0, 1) for sign in (-1, 1)]
            values += [rng.randrange(-(1 << 127), 1 << 127) for _ in range(256)]
            for value in values:
                high, low = divmod(value, 1 << 64)
                for shift in range(37):
                    upper, lower = C.c_uint64(), C.c_uint64()
                    function(high, low, shift, C.byref(upper), C.byref(lower))
                    result = (upper.value << 64) | lower.value
                    if result >= 1 << 127:
                        result -= 1 << 128
                    self.assertEqual(result, value // (1 << shift), (value, shift))
