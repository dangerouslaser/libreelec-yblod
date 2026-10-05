"""Encoder/resource/interface tests; never create or dispatch a GPU context."""
from dataclasses import replace
from fractions import Fraction
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import native_gpu_probe as probe
from native_gpu_vectors import vector_fixtures

ROOT=Path(__file__).resolve().parent


class NativeGpuProbeTests(unittest.TestCase):
    def fixture(self):
        return next(f for f in vector_fixtures() if f.nlq is not None and f.nlq.denominator==23)

    def encode(self,fixture,**changes):
        values=dict(mapping_config=fixture.mapping,nlq_config=fixture.nlq,component=fixture.component,
                    triplets=fixture.triplets,el_samples=fixture.el_samples,output_depth=fixture.output_depth)
        values.update(changes)
        return probe.encode(**values)

    def test_fixed_format_and_little_endian_header(self):
        f=self.fixture();data=self.encode(f)
        self.assertEqual(data[:8],b"YBGPU01\0")
        self.assertEqual(data[8:12],len(f.triplets).to_bytes(4,"little"))
        self.assertEqual(len(data),64+3*(72+16*184)+16*len(f.triplets))

    def test_fractional_and_boolean_inputs_never_quantized(self):
        f=self.fixture()
        for value in (True,1.25,Fraction(3,2),-1,1024):
            with self.assertRaises(ValueError): self.encode(f,triplets=[(value,0,0)],el_samples=[0])
            with self.assertRaises(ValueError): self.encode(f,triplets=[(0,0,0)],el_samples=[value])
        for settings in ({"component":True},{"component":3},{"output_depth":True},{"output_depth":8}):
            with self.assertRaises(ValueError):self.encode(f,**settings)

    def test_bounded_iterators_and_exact_el_association(self):
        f=self.fixture()
        with self.assertRaises(ValueError):self.encode(f,triplets=itertools.repeat((1,2,3)))
        for values in ([],itertools.repeat(1),None):
            with self.assertRaises(ValueError):self.encode(f,triplets=[(1,2,3)],el_samples=values)
        with self.assertRaises(ValueError):self.encode(f,triplets=[])
        with self.assertRaises(ValueError):self.encode(f,triplets=[(1,2)])

    def test_global_denominator_subset_and_disabled_contract(self):
        f=self.fixture()
        with self.assertRaisesRegex(ValueError,"denominator mismatch"):
            self.encode(f,nlq_config=replace(f.nlq,denominator=32 if f.nlq.denominator!=32 else 23))
        with self.assertRaisesRegex(ValueError,"disabled EL"):
            self.encode(f,nlq_config=None)
        data=self.encode(f,nlq_config=None,el_samples=None)
        self.assertEqual(data[16:20],bytes(4))

    def test_exclusive_fixture_write(self):
        f=self.fixture()
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"fixture.bin"
            args=(f.mapping,f.nlq,f.component,f.triplets,f.el_samples,f.output_depth)
            self.assertEqual(probe.write_fixture(path,*args),len(path.read_bytes()))
            original=path.read_bytes()
            with self.assertRaises(FileExistsError):probe.write_fixture(path,*args)
            self.assertEqual(path.read_bytes(),original)

    def test_wire_sentinel_group_and_fence_guards_present(self):
        source=(ROOT/"native_gpu_probe.c").read_text()
        shader=(ROOT/"native_gpu_probe.comp").read_text()
        self.assertIn("actual[i]=INT32_MIN",source)
        self.assertIn("linked_group_size[0]!=64",source)
        self.assertIn("GL_COMPUTE_WORK_GROUP_SIZE",source)
        self.assertIn("UINT64_C(5000000000)",source)
        self.assertNotIn("glFinish(",source)
        self.assertIn("GL_BUFFER_UPDATE_BARRIER_BIT",source)
        self.assertIn("input_words[4*i]",source)
        self.assertIn("actual[4*i]",source)
        self.assertIn("layout(local_size_x=64)",shader)
        self.assertIn("if (index>=uint(m[0])) return",shader)
        self.assertIn("20-int(m[4])*degree",shader)
        self.assertIn("int(m[5])-5-int(m[6])",shader)
        self.assertIn("terms[6]=floor_power_two(terms[3]*terms[2],20)",shader)
        self.assertIn("terms[14+term]=floor_power_two(terms[term]*terms[7+term],20)",shader)


class NativeGPUWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc"):raise unittest.SkipTest("host C compiler unavailable")
        cls.temporary=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        root=Path(cls.temporary.name)
        source=root/"wire.c"
        source.write_text('''#include "native_gpu_probe_fixture.h"
#include <stdio.h>
#include <stdlib.h>
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    struct yb_probe_fixture *f=calloc(1,sizeof(*f));
    if(!f || !yb_probe_load(argv[1],f)){free(f);return 2;}
    int64_t words[YB_PROBE_METADATA_WORDS];yb_probe_metadata(f,words);
    putchar('[');
    for(unsigned i=0;i<YB_PROBE_METADATA_WORDS;++i){if(i)putchar(',');printf("%lld",(long long)words[i]);}
    puts("]");free(f);return 0;
}
''')
        cls.executable=root/"wire"
        result=subprocess.run(["cc","-std=c11","-O2","-Wall","-Wextra","-Werror","-Wconversion","-Wshadow",
            "-I",str(ROOT),str(source),str(ROOT/"native_gpu_probe_fixture.c"),str(ROOT/"native_composer.c"),
            str(ROOT/"native_gpu_guard.c"),"-o",str(cls.executable)],capture_output=True,text=True)
        if result.returncode:raise AssertionError(result.stderr)

    def test_all_scalar_word_offsets_against_independent_mapping_fields(self):
        for fixture in vector_fixtures():
            with self.subTest(name=fixture.name),tempfile.TemporaryDirectory() as temporary:
                path=Path(temporary)/"fixture.bin"
                probe.write_fixture(path,fixture.mapping,fixture.nlq,fixture.component,
                                    fixture.triplets,fixture.el_samples,fixture.output_depth)
                process=subprocess.run([str(self.executable),str(path)],capture_output=True,text=True,check=True)
                words=json.loads(process.stdout)
                self.assertEqual(len(words),419)
                cfg=fixture.mapping;curve=cfg.mappings[fixture.component];n=fixture.nlq
                header=[len(fixture.triplets),fixture.component,int(n is not None),fixture.output_depth,
                        cfg.bit_depth,cfg.denominator,n.bit_depth if n else 0,n.offset if n else 0,
                        n.slope if n else 0,n.threshold if n else 0,n.maximum if n else 0]
                self.assertEqual(words[:11],header)
                self.assertEqual(words[11:17],[v for curve in cfg.mappings for v in (curve.pivots[0],curve.pivots[-1])])
                self.assertEqual(words[17],len(curve.pivots))
                self.assertEqual(words[18:35],list(curve.pivots)+[0]*(17-len(curve.pivots)))
                for index in range(16):
                    expected=[0]*24
                    if index<len(curve.segments):
                        segment=curve.segments[index]
                        polynomial=segment.method=="polynomial"
                        expected[0]=0 if polynomial else 1
                        expected[1]=len(segment.coefficients)-1 if polynomial else len(segment.coefficients)
                        expected[2]=segment.constant
                        if polynomial:expected[3:3+len(segment.coefficients)]=segment.coefficients
                        else:
                            values=[v for row in segment.coefficients for v in row]
                            expected[3:3+len(values)]=values
                    self.assertEqual(words[35+index*24:35+(index+1)*24],expected)


if __name__=="__main__":unittest.main()
