"""Pure host validation for explicit reconstructed420 expansion; no GPU."""
import ctypes
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
class Plan(ctypes.Structure):
    _fields_=[('version',ctypes.c_uint32),('width',ctypes.c_uint32),('height',ctypes.c_uint32),('output_depth',ctypes.c_uint32),('sampling_contract',ctypes.c_uint32),('textures',ctypes.c_uint32*3),('frame_id',ctypes.c_uint8*32)]

class GPUYCCBackendHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory()
        binary=Path(cls.directory.name)/'ycc.so'
        source=ROOT/'engine/experimental/native_gpu_ycc_backend.c'
        subprocess.run(['cc','-std=c11','-O2','-fPIC','-shared','-Wall','-Wextra','-Werror','-Wconversion','-Wshadow','-DYB_GPU_YCC_HOST_ONLY','-I',str(ROOT/'engine/include'),*shlex.split(os.environ.get('YB_GPU_FRAME_TEST_CFLAGS','')),str(source),'-o',str(binary)],check=True,capture_output=True,text=True)
        cls.lib=ctypes.CDLL(str(binary))
        cls.lib.yb_gpu_ycc_validate_plan.argtypes=[ctypes.POINTER(Plan)]
        cls.lib.yb_gpu_ycc_validate_plan.restype=ctypes.c_int
    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()
    def plan(self):
        p=Plan(1,4,4,12,1,(ctypes.c_uint32*3)(1,2,3))
        p.frame_id[31]=1
        return p
    def test_explicit_route_all_frame_token_bytes(self):
        self.assertEqual(self.lib.yb_gpu_ycc_validate_plan(ctypes.byref(self.plan())),0)
        for i in range(32):
            p=self.plan();p.frame_id[31]=0;p.frame_id[i]=1
            self.assertEqual(self.lib.yb_gpu_ycc_validate_plan(ctypes.byref(p)),0)
    def test_malformed_argument_precedes_unsupported_policy(self):
        for field,value in [('version',0),('width',0),('width',3842),('height',2162),('width',3)]:
            p=self.plan();setattr(p,field,value);p.sampling_contract=0
            before=bytes(p)
            self.assertEqual(self.lib.yb_gpu_ycc_validate_plan(ctypes.byref(p)),1)
            self.assertEqual(bytes(p),before)
        for textures in ((0,2,3),(1,1,3),(1,2,1)):
            p=self.plan();p.textures[:]=textures
            self.assertEqual(self.lib.yb_gpu_ycc_validate_plan(ctypes.byref(p)),1)
        p=self.plan();p.frame_id[31]=0
        self.assertEqual(self.lib.yb_gpu_ycc_validate_plan(ctypes.byref(p)),1)
    def test_valid_unsupported_depth_and_sampling(self):
        for field,value in [('output_depth',10),('output_depth',0),('sampling_contract',0),('sampling_contract',2)]:
            p=self.plan();setattr(p,field,value)
            self.assertEqual(self.lib.yb_gpu_ycc_validate_plan(ctypes.byref(p)),3)
        self.assertEqual(self.lib.yb_gpu_ycc_validate_plan(None),1)
    def test_source_finite_transactional_image_contract(self):
        s=(ROOT/'engine/experimental/native_gpu_ycc_backend.c').read_text()
        self.assertEqual(s.count('g->DispatchCompute('),1)
        self.assertEqual(s.count('g->FenceSync('),1)
        self.assertIn('UINT64_C(5000000000)',s)
        self.assertIn('if(error)return YB_GPU_BACKEND_FRAME_REJECTED;',s)
        self.assertIn('if(b->pending)return YB_GPU_BACKEND_BUSY;',s)
        self.assertIn('GL_RGBA32F',s)
        self.assertIn('format==GL_R16UI',s)
        self.assertNotIn('eglCreate',s)

    def test_synthetic_runner_oracle_and_rejection_scope(self):
        s=(ROOT/'engine/experimental/native_gpu_ycc_runner.c').read_text()
        self.assertIn('uint32_t numerator=',s)
        self.assertIn('return (float)numerator/32768.0f;',s)
        self.assertIn('memcmp(actual,expected,',s)
        self.assertIn('YB_GPU_BACKEND_FRAME_REJECTED',s)
        self.assertIn('memcmp(&out,&sentinel,sizeof(out))',s)
        main=s.split('int main(',1)[1]
        self.assertLess(main.index('prepare_fixture(4,4,'),main.index('execute(argv[1]'))

if __name__=='__main__':unittest.main()
