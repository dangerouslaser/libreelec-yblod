import ctypes as C
import os
from pathlib import Path
import random
import shlex
import subprocess
import tempfile
import unittest

from scaling_oracle import expand
from test_annex_b_resampler_vectors import SOURCE,Y_VERTICAL,C_VERTICAL,Y_OUTPUT,C_OUTPUT


class Plane(C.Structure):
    _fields_=[("data",C.POINTER(C.c_uint16)),("samples",C.c_uint64),("width",C.c_uint64),("height",C.c_uint64),("stride_samples",C.c_uint64)]
class Rect(C.Structure):_fields_=[("x",C.c_uint64),("y",C.c_uint64),("width",C.c_uint64),("height",C.c_uint64)]
class Output(C.Structure):_fields_=[("data",C.POINTER(C.c_uint16)),("samples",C.c_uint64),("stride_samples",C.c_uint64)]


def pointer(owner):return C.cast(C.c_void_p(C.addressof(owner)),C.POINTER(C.c_uint16))


class NativeAnnexBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        here=Path(__file__).resolve().parent;library=Path(cls.temp.name)/"annexb.so"
        subprocess.run(["cc","-std=c11","-O2","-fPIC","-shared","-Wall","-Wextra","-Werror","-Wconversion","-Wshadow",
                        *shlex.split(os.environ.get("YB_ANNEXB_TEST_CFLAGS","")),str(here/"native_annexb_probe.c"),"-o",str(library)],check=True,capture_output=True)
        cls.library=C.CDLL(str(library));cls.call=cls.library.yb_annexb_probe
        cls.call.argtypes=[C.POINTER(Plane),C.c_uint32,C.c_uint32,C.POINTER(Rect),C.POINTER(Output),C.c_uint64,C.POINTER(C.c_uint16),C.c_uint64];cls.call.restype=C.c_int

    def fixture(self,rows,rect):
        height=len(rows);width=len(rows[0]);stride=width+3;words=[]
        for i,row in enumerate(rows):words+=list(row)+([0xDEAD]*3 if i<height-1 else [])
        source=(C.c_uint16*len(words))(*words);plane=Plane(pointer(source),len(words),width,height,stride)
        region=Rect(*rect);outstride=region.width+5;extent=(region.height-1)*outstride+region.width+3
        output=(C.c_uint16*extent)(*([0xBEEF]*extent));descriptor=Output(pointer(output),extent,outstride)
        scratch=(C.c_uint16*(width+1))(*([0xCAFE]*(width+1)))
        return source,plane,region,output,descriptor,scratch

    def execute(self,rows,component,mode,rect):
        source,p,r,out,o,scratch=self.fixture(rows,rect);before=bytes(source)
        self.assertEqual(self.call(C.byref(p),component,mode,C.byref(r),C.byref(o),r.width*r.height,pointer(scratch),p.width),0)
        self.assertEqual(bytes(source),before);self.assertEqual(scratch[-1],0xCAFE)
        used={y*o.stride_samples+x for y in range(r.height) for x in range(r.width)}
        self.assertTrue(all(v==0xBEEF for i,v in enumerate(out) if i not in used))
        return tuple(tuple(out[y*o.stride_samples+x] for x in range(r.width)) for y in range(r.height)),tuple(scratch[:p.width])

    def test_literal_final_and_vertical_answers_all_components(self):
        for component,vertical,final in ((0,Y_VERTICAL,Y_OUTPUT),(1,C_VERTICAL,C_OUTPUT),(2,C_VERTICAL,C_OUTPUT)):
            self.assertEqual(self.execute(SOURCE,component,1,(0,0,2,4))[0],vertical)
            self.assertEqual(self.execute(SOURCE,component,2,(0,0,4,4))[0],final)
            for y in range(4):self.assertEqual(self.execute(SOURCE,component,2,(0,y,4,1))[1],vertical[y])
        self.assertEqual(Y_OUTPUT[0][1],1);self.assertEqual(Y_OUTPUT[3][3],9)

    def test_fraction_oracle_seeded_grids_and_partial_global_rects(self):
        rng=random.Random(71023)
        for index in range(12):
            width,height=rng.randrange(1,10),rng.randrange(1,8)
            rows=[[rng.randrange(65536) for _ in range(width)] for _ in range(height)]
            for component,name in enumerate(("Y","Cb","Cr")):
                final,vertical,_=expand(rows,name)
                for mode,expected in ((1,vertical),(2,final)):
                    ow=len(expected[0]);oh=len(expected)
                    self.assertEqual(self.execute(rows,component,mode,(0,0,ow,oh))[0],tuple(map(tuple,expected)))
                    x=rng.randrange(ow);y=rng.randrange(oh);w=rng.randrange(1,ow-x+1);h=rng.randrange(1,oh-y+1)
                    self.assertEqual(self.execute(rows,component,mode,(x,y,w,h))[0],tuple(tuple(row[x:x+w]) for row in expected[y:y+h]))

    def test_native10_overshoot_and_storage_clip_are_not_nominal_clamp(self):
        native=((0,1023),(1023,0));full=((0,65535),(65535,0))
        self.assertEqual(self.execute(native,0,1,(0,0,2,1))[0],((0,1095),))
        self.assertEqual(self.execute(full,0,1,(0,0,2,4))[0],((0,65535),(13312,52223),(52223,13312),(65535,0)))
        for component in range(3):self.assertEqual(self.execute(((65535,),),component,2,(0,0,2,2))[0],((65535,65535),(65535,65535)))

    def test_late_scratch_and_metadata_failures_preserve_output_and_scratch(self):
        changes=[("p","samples",1),("p","samples",(1<<64)-1),("p","stride_samples",(1<<64)-1),("p","width",8193),
                 ("r","x",4),("r","width",(1<<64)-1),("r","height",65537),("o","samples",1),("o","stride_samples",(1<<64)-1)]
        for target,name,value in changes:
            owner,p,r,out,o,scratch=self.fixture(SOURCE,(0,0,4,4));setattr({"p":p,"r":r,"o":o}[target],name,value)
            before=(bytes(out),bytes(scratch));status=self.call(C.byref(p),0,2,C.byref(r),C.byref(o),16,pointer(scratch),2)
            self.assertNotEqual(status,0);self.assertEqual((bytes(out),bytes(scratch)),before)
        for component,mode,count,scratchcount in ((3,2,16,2),(0,0,16,2),(0,2,15,2),(0,2,16,1)):
            owner,p,r,out,o,scratch=self.fixture(SOURCE,(0,0,4,4));before=(bytes(out),bytes(scratch))
            self.assertNotEqual(self.call(C.byref(p),component,mode,C.byref(r),C.byref(o),count,pointer(scratch),scratchcount),0)
            self.assertEqual((bytes(out),bytes(scratch)),before)

    def test_alias_source_descriptors_output_and_scratch_before_any_write(self):
        owner,p,r,out,o,scratch=self.fixture(SOURCE,(0,0,2,2))
        for victim in (owner,p,r,o,scratch):
            save=C.string_at(C.addressof(victim),C.sizeof(victim));o.data=pointer(victim)
            # Save descriptor after deliberately setting its pointer.
            if victim is o:save=bytes(o)
            self.assertEqual(self.call(C.byref(p),0,2,C.byref(r),C.byref(o),4,pointer(scratch),2),6)
            self.assertEqual(C.string_at(C.addressof(victim),C.sizeof(victim)),save)
        o.data=pointer(out)
        for victim in (owner,p,r,o,out):
            before=(bytes(out),C.string_at(C.addressof(victim),C.sizeof(victim)))
            self.assertEqual(self.call(C.byref(p),0,2,C.byref(r),C.byref(o),4,pointer(victim),2),6)
            self.assertEqual((bytes(out),C.string_at(C.addressof(victim),C.sizeof(victim))),before)

    def test_null_and_misaligned_inputs_fail_before_any_write(self):
        owner,p,r,out,o,scratch=self.fixture(SOURCE,(0,0,4,4));before=(bytes(out),bytes(scratch))
        cases=[(None,C.byref(r),C.byref(o),pointer(scratch)),(C.byref(p),None,C.byref(o),pointer(scratch)),
               (C.byref(p),C.byref(r),None,pointer(scratch)),(C.byref(p),C.byref(r),C.byref(o),None)]
        for descriptor,typ in ((p,Plane),(r,Rect),(o,Output)):
            args=[C.byref(p),C.byref(r),C.byref(o),pointer(scratch)]
            args[(Plane,Rect,Output).index(typ)]=C.cast(C.c_void_p(C.addressof(descriptor)+1),C.POINTER(typ));cases.append(tuple(args))
        for plane,rect,output,work in cases:
            self.assertNotEqual(self.call(plane,0,2,rect,output,16,work,2),0);self.assertEqual((bytes(out),bytes(scratch)),before)
        source_pointer=p.data;output_pointer=o.data
        for victim,field,base in ((p,"data",owner),(o,"data",out)):
            for invalid in (C.POINTER(C.c_uint16)(),C.cast(C.c_void_p(C.addressof(base)+1),C.POINTER(C.c_uint16))):
                setattr(victim,field,invalid)
                self.assertNotEqual(self.call(C.byref(p),0,2,C.byref(r),C.byref(o),16,pointer(scratch),2),0)
                self.assertEqual((bytes(out),bytes(scratch)),before)
            setattr(victim,field,source_pointer if victim is p else output_pointer)
        bad_scratch=C.cast(C.c_void_p(C.addressof(scratch)+1),C.POINTER(C.c_uint16))
        self.assertNotEqual(self.call(C.byref(p),0,2,C.byref(r),C.byref(o),16,bad_scratch,2),0)
        self.assertEqual((bytes(out),bytes(scratch)),before)

    def test_stitched_global_tiles_have_no_new_internal_edges(self):
        rows=((0,1023,0,1023,65535),(1,512,32768,9,0),(65535,0,17,1023,1))
        for component,name in enumerate(("Y","Cb","Cr")):
            expected=expand(rows,name)[0];ow=len(expected[0]);oh=len(expected);stitched=[[None]*ow for _ in range(oh)]
            for y in range(0,oh,2):
                for x in range(0,ow,3):
                    w=min(3,ow-x);h=min(2,oh-y);tile=self.execute(rows,component,2,(x,y,w,h))[0]
                    for row in range(h):stitched[y+row][x:x+w]=tile[row]
            self.assertEqual(stitched,expected)

    def test_3840_output_bounded_rectangle_and_maximum_count(self):
        width,height=1920,1080;owner=(C.c_uint16*(width*height))() # all-zero synthetic source, no Python pixel loop
        p=Plane(pointer(owner),width*height,width,height,width);r=Rect(0,2000,3840,16)
        out=(C.c_uint16*61440)();o=Output(pointer(out),61440,3840);scratch=(C.c_uint16*width)()
        self.assertEqual(self.call(C.byref(p),0,2,C.byref(r),C.byref(o),61440,pointer(scratch),width),0)
        self.assertEqual(bytes(out),bytes(122880))
        r=Rect(0,0,256,256);out=(C.c_uint16*65536)();o=Output(pointer(out),65536,256)
        self.assertEqual(self.call(C.byref(p),2,2,C.byref(r),C.byref(o),65536,pointer(scratch),width),0)
        r.height=257;before=(bytes(out),bytes(scratch))
        self.assertNotEqual(self.call(C.byref(p),2,2,C.byref(r),C.byref(o),65792,pointer(scratch),width),0)
        self.assertEqual((bytes(out),bytes(scratch)),before)


if __name__=="__main__":unittest.main()
