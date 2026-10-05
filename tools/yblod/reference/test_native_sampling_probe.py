import ctypes as C
import os
from fractions import Fraction as F
from pathlib import Path
import subprocess
import shlex
import tempfile
import unittest

from sampling_contract import SamplingContract,sample_exact


class Plane(C.Structure):
    _fields_=[("data",C.POINTER(C.c_uint16)),("samples",C.c_uint64),("width",C.c_uint64),("height",C.c_uint64),("stride_samples",C.c_uint64)]


class Contract(C.Structure):
    _fields_=[("width",C.c_uint32),("height",C.c_uint32),("origin_x",C.c_int64),("origin_y",C.c_int64),
              ("step_x",C.c_int64),("step_y",C.c_int64),("coordinate_fractional_bits",C.c_uint32),
              ("method",C.c_uint32),("edge",C.c_uint32),("native_depth",C.c_uint32),("fractional_bits",C.c_uint32),("word_normalization_divisor",C.c_uint32)]


class Query(C.Structure):_fields_=[("x",C.c_uint32),("y",C.c_uint32)]
class Result(C.Structure):
    _fields_=[("source_x_numerator",C.c_int64),("source_y_numerator",C.c_int64),("coordinate_denominator",C.c_uint64),
              ("raw_numerator",C.c_uint64),("raw_denominator",C.c_uint64),("native_denominator",C.c_uint64),("normalized_denominator",C.c_uint64)]


class NativeSamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        here=Path(__file__).resolve().parent;library=Path(cls.temp.name)/"sampling.so"
        subprocess.run(["cc","-std=c11","-O2","-fPIC","-shared","-Wall","-Wextra","-Werror","-Wconversion","-Wshadow",
                        *shlex.split(os.environ.get("YB_SAMPLING_TEST_CFLAGS","")),
                        str(here/"native_sampling_probe.c"),"-o",str(library)],check=True,capture_output=True)
        cls.library=C.CDLL(str(library));cls.call=cls.library.yb_sampling_probe
        cls.call.argtypes=[C.POINTER(Plane),C.POINTER(Contract),C.POINTER(Query),C.c_uint64,C.POINTER(Result),C.c_uint64];cls.call.restype=C.c_int

    def fixture(self,rows,contract,queries,padding=3):
        width=len(rows[0]);height=len(rows);stride=width+padding
        words=[]
        for i,row in enumerate(rows):words+=row+([0xDEAD]*padding if i<height-1 else [])
        owner=(C.c_uint16*len(words))(*words)
        plane=Plane(C.cast(C.c_void_p(C.addressof(owner)),C.POINTER(C.c_uint16)),len(words),width,height,stride)
        config=Contract(**contract.native_fields());q=(Query*len(queries))(*(Query(*v) for v in queries));out=(Result*len(queries))()
        C.memset(C.addressof(out),0xA5,C.sizeof(out));return owner,plane,config,q,out

    def compare(self,rows,contract,queries):
        owner,p,c,q,out=self.fixture(rows,contract,queries)
        source_before=bytes(owner)
        self.assertEqual(self.call(C.byref(p),C.byref(c),q,len(q),out,len(out)),0)
        self.assertEqual(bytes(owner),source_before)
        for point,result in zip(queries,out):
            oracle=sample_exact(rows,*point,contract)
            self.assertEqual((F(result.source_x_numerator,result.coordinate_denominator),F(result.source_y_numerator,result.coordinate_denominator)),oracle["source_coordinate"])
            for field,key in (("raw_denominator","raw_word"),("native_denominator","native_equivalent"),("normalized_denominator","diagnostic_normalized")):
                self.assertEqual(F(result.raw_numerator,getattr(result,field)),oracle[key])
        return out

    def test_explicit_halfpixel_illustration_not_rawpixel_or_texture_claim(self):
        contract=SamplingContract(2,1,F(1,2),0,1,1,"bilinear",65472)
        out=self.compare([[32768,32784]],contract,[(0,0),(1,0)])
        self.assertEqual(F(out[0].raw_numerator,out[0].raw_denominator),32776)
        self.assertEqual(F(out[0].raw_numerator,out[0].native_denominator),F(4097,8))
        self.assertEqual(F(out[0].raw_numerator,out[0].normalized_denominator),F(32776,65472))
        self.assertNotEqual(F(32768,65472),F(1,2));self.assertNotEqual(F(32776,65472),F(32776,65535))

    def test_fractional_words_overshoot_and_explicit_divisor_preserved(self):
        for divisor in (1,65472,65535,(1<<32)-1):
            rows=[[32768+d for d in range(64)],[65472]+[65535]*63]
            contract=SamplingContract(64,2,0,0,1,1,"integer-point",divisor)
            out=self.compare(rows,contract,[(x,y) for y in range(2) for x in range(64)])
            if divisor==65472:self.assertGreater(F(out[-1].raw_numerator,out[-1].normalized_denominator),1)

    def test_negative_dyadics_ramps_edges_padding_and_extreme_geometry(self):
        rows=[[0,1,32769],[65535,65472,32767]]
        for ox,oy,sx,sy in ((F(-1,2),F(-1,2),F(1,4),F(3,4)),(F(5,2),F(3,2),F(-1,4),F(-1,2)),
                           (F(-1,65536),F(1,65536),F(1,65536),F(-1,65536)),(-8192,8192,8192,-8192)):
            contract=SamplingContract(3,2,ox,oy,sx,sy,"bilinear",(1<<32)-1)
            self.compare(rows,contract,[(x,y) for x in (0,1,2,8191) for y in (0,1,8191)])
        out=self.compare([[32769]],SamplingContract(1,1,F(-1,2),F(1,2),1,1,"bilinear",65472),[(0,0),(8191,8191)])
        self.assertTrue(all(F(v.raw_numerator,v.raw_denominator)==32769 for v in out))

    def test_complete_batch_validation_before_any_write(self):
        contract=SamplingContract(2,1,0,0,F(1,2),1,"integer-point",65472)
        owner,p,c,q,out=self.fixture([[32768,32784]],contract,[(0,0),(1,0)])
        before=bytes(out);self.assertEqual(self.call(C.byref(p),C.byref(c),q,2,out,2),5);self.assertEqual(bytes(out),before)
        c.method=2;q[1].x=8192
        self.assertEqual(self.call(C.byref(p),C.byref(c),q,2,out,2),5);self.assertEqual(bytes(out),before)

    def test_invalid_metadata_extent_overflows_and_counts(self):
        cfg=SamplingContract(2,2,0,0,1,1,"bilinear",65472)
        for target,name,value in (("p","samples",1),("p","samples",(1<<64)-1),("p","stride_samples",(1<<64)-1),
                                  ("p","width",8193),("c","coordinate_fractional_bits",17),("c","origin_x",-(1<<63)),
                                  ("c","step_y",(1<<63)-1),("c","word_normalization_divisor",0),("c","fractional_bits",5),("c","method",3)):
            owner,p,c,q,out=self.fixture([[1,2],[3,4]],cfg,[(0,0),(1,1)]);setattr(p if target=="p" else c,name,value)
            before=bytes(out);self.assertNotEqual(self.call(C.byref(p),C.byref(c),q,2,out,2),0);self.assertEqual(bytes(out),before)
        owner,p,c,q,out=self.fixture([[1,2],[3,4]],cfg,[(0,0),(1,1)]);before=bytes(out)
        for count,result_count in ((0,0),(65537,65537),(2,1)):
            self.assertNotEqual(self.call(C.byref(p),C.byref(c),q,count,out,result_count),0);self.assertEqual(bytes(out),before)

    def test_source_query_config_descriptor_alias_rejected_before_write(self):
        cfg=SamplingContract(32,1,0,0,1,1,"bilinear",65472)
        owner,p,c,q,out=self.fixture([[32769]*32],cfg,[(0,0)])
        for victim in (owner,p,c,q):
            before=C.string_at(C.addressof(victim),C.sizeof(victim));ptr=C.cast(C.c_void_p(C.addressof(victim)),C.POINTER(Result))
            self.assertEqual(self.call(C.byref(p),C.byref(c),q,1,ptr,1),4)
            self.assertEqual(C.string_at(C.addressof(victim),C.sizeof(victim)),before)

    def test_python_contract_strict_immutable_no_approximation(self):
        cfg=SamplingContract(2,1,F(-1,2),0,1,1,"bilinear",65472)
        with self.assertRaises(Exception):cfg.method="integer-point"
        for kwargs in (dict(width=True),dict(origin_x=0.5),dict(step_x=F(1,3)),dict(origin_y=8193),dict(native_depth=True),dict(word_normalization_divisor=0)):
            params=dict(width=2,height=1,origin_x=0,origin_y=0,step_x=1,step_y=1,method="bilinear",word_normalization_divisor=65472);params.update(kwargs)
            with self.assertRaises(ValueError):SamplingContract(**params)
        with self.assertRaises(ValueError):cfg.source_coordinate(True,0)

    def test_maximum_batch_exact_and_unaligned_output_rejected(self):
        cfg=SamplingContract(1,1,0,0,0,0,"integer-point",65472)
        owner,p,c,q,out=self.fixture([[65535]],cfg,[(0,0)]*65536)
        self.assertEqual(self.call(C.byref(p),C.byref(c),q,65536,out,65536),0)
        self.assertEqual(out[0].raw_numerator,65535);self.assertEqual(out[-1].raw_numerator,65535)
        saved=bytes(out);bad=C.cast(C.c_void_p(C.addressof(out)+1),C.POINTER(Result))
        self.assertEqual(self.call(C.byref(p),C.byref(c),q,1,bad,1),3)
        self.assertEqual(bytes(out),saved)

    def test_null_and_misaligned_descriptors_data_queries_and_results(self):
        cfg=SamplingContract(2,1,0,0,1,1,"bilinear",65472)
        owner,p,c,q,out=self.fixture([[32768,65535]],cfg,[(0,0)])
        before=bytes(out)
        cases=[(None,C.byref(c),q,out,1),(C.byref(p),None,q,out,2),
               (C.byref(p),C.byref(c),None,out,3),(C.byref(p),C.byref(c),q,None,3)]
        bad_plane=C.cast(C.c_void_p(C.addressof(p)+1),C.POINTER(Plane))
        bad_contract=C.cast(C.c_void_p(C.addressof(c)+1),C.POINTER(Contract))
        bad_query=C.cast(C.c_void_p(C.addressof(q)+1),C.POINTER(Query))
        cases += [(bad_plane,C.byref(c),q,out,1),(C.byref(p),bad_contract,q,out,2),(C.byref(p),C.byref(c),bad_query,out,3)]
        for plane,config,query,result,status in cases:
            self.assertEqual(self.call(plane,config,query,1,result,1),status);self.assertEqual(bytes(out),before)
        p.data=C.POINTER(C.c_uint16)()
        self.assertEqual(self.call(C.byref(p),C.byref(c),q,1,out,1),1);self.assertEqual(bytes(out),before)
        p.data=C.cast(C.c_void_p(C.addressof(owner)+1),C.POINTER(C.c_uint16))
        self.assertEqual(self.call(C.byref(p),C.byref(c),q,1,out,1),1);self.assertEqual(bytes(out),before)


if __name__=="__main__":unittest.main()
