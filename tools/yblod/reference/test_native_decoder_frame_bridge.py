"""Synthetic same-build blob handoff; no FFmpeg structs or real RPU fabrication."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest
import native_integration_frame as frame
import native_stage as native

ROOT=Path(__file__).resolve().parent
class Instructions(C.Structure):
    _fields_=[("version",C.c_uint32),("enabled",C.c_int32),("depth",C.c_int32),
              ("spatial",C.c_uint32),("el_spatial",C.c_uint32),("chroma",C.c_uint32),
              ("full",C.c_uint32),("profile",C.c_uint32),("level",C.c_uint32),
              ("mapping",native.Mapping),("nlq",native.NLQ*3)]

class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory()
        out=Path(cls.directory.name)/"bridge.so"
        subprocess.run(["cc","-std=c11","-O2","-shared","-fPIC","-Wall","-Wextra","-Werror",
                        "-Wconversion","-Wshadow",*(str(ROOT/p) for p in
                        ("native_decoder_frame_bridge.c","native_integration_probe.c",
                         "native_composer.c","native_sampling_probe.c")),"-o",str(out)],check=True)
        cls.lib=C.CDLL(str(out))
        cls.lib.yb_decoder_frame_bridge_sizeof_instructions.restype=C.c_uint64
        cls.call=cls.lib.yb_decoder_frame_bridge_init
        cls.call.argtypes=[C.POINTER(frame.Context),C.POINTER(frame.Descriptor),C.c_void_p,C.c_size_t]
        cls.call.restype=C.c_int
    @classmethod
    def tearDownClass(cls): cls.directory.cleanup()
    def fixture(self):
        obj=Instructions();obj.version=1;obj.depth=12
        obj.mapping.bit_depth=10;obj.mapping.denominator=23
        for curve in obj.mapping.components:
            curve.pivot_count=2;curve.pivots[1]=1023
            curve.segments[0].method=0;curve.segments[0].order=1
            curve.segments[0].coefficients[0][1]=1<<23
        return obj,frame.Descriptor(1,1,2,2,12,0),frame.Context()
    def test_size_and_owned_copy(self):
        obj,desc,ctx=self.fixture()
        self.assertEqual(self.lib.yb_decoder_frame_bridge_sizeof_instructions(),C.sizeof(obj))
        self.assertEqual(self.call(C.byref(ctx),C.byref(desc),C.byref(obj),C.sizeof(obj)),0)
        obj.mapping.components[0].pivots[1]=0
        self.assertEqual(ctx.mapping.components[0].pivots[1],1023)
    def test_invalid_blobs_leave_context_untouched(self):
        for field,value in (("version",2),("enabled",2),("chroma",1),("depth",8),
                            ("spatial",2),("el_spatial",2),("full",2),("profile",16),("level",16)):
            obj,desc,ctx=self.fixture();setattr(obj,field,value)
            before=bytes(ctx)
            self.assertNotEqual(self.call(C.byref(ctx),C.byref(desc),C.byref(obj),C.sizeof(obj)),0)
            self.assertEqual(bytes(ctx),before)
        obj,desc,ctx=self.fixture()
        for size in (0,C.sizeof(obj)-1,C.sizeof(obj)+1):
            self.assertNotEqual(self.call(C.byref(ctx),C.byref(desc),C.byref(obj),size),0)
            self.assertEqual(bytes(ctx),bytes(frame.Context()))
    def test_disabled_nlq_and_descriptor_mismatch_rejected(self):
        obj,desc,ctx=self.fixture();obj.nlq[2].offset=1
        self.assertNotEqual(self.call(C.byref(ctx),C.byref(desc),C.byref(obj),C.sizeof(obj)),0)

    def test_descriptor_and_blob_aliases_rejected(self):
        obj,desc,ctx=self.fixture()
        alias=C.cast(C.byref(ctx),C.POINTER(frame.Descriptor))
        self.assertEqual(self.call(C.byref(ctx),alias,C.byref(obj),C.sizeof(obj)),8)
        self.assertEqual(bytes(ctx),bytes(frame.Context()))
        self.assertEqual(self.call(C.byref(ctx),C.byref(desc),C.byref(ctx),C.sizeof(obj)),8)
        obj,desc,ctx=self.fixture();desc.enhancement_enabled=1
        self.assertNotEqual(self.call(C.byref(ctx),C.byref(desc),C.byref(obj),C.sizeof(obj)),0)

if __name__=="__main__": unittest.main()
