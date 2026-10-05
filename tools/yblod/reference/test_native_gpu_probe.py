"""Encoder/resource/interface tests; never create or dispatch a GPU context."""
from dataclasses import replace
from fractions import Fraction
import itertools
import os
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


if __name__=="__main__":unittest.main()
