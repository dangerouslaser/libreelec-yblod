"""Pure CPU backend guards/packing; no context or GPU dispatch."""
import ctypes as C
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
import native_stage as native
from native_gpu_vectors import vector_fixtures,width_oracle

ROOT=Path(__file__).resolve().parents[3]
ENGINE=ROOT/'engine'/'experimental'

class Plan(C.Structure):
    _fields_=[('version',C.c_uint32),('width',C.c_uint32),('height',C.c_uint32),('input_format',C.c_uint32),('enhancement_enabled',C.c_int32),('output_depth',C.c_int32),('textures',C.c_uint32*5),('frame_id',C.c_uint8*32),('guide_frame_id',C.c_uint8*32),('enhancement_frame_id',C.c_uint8*32),('guide_contract_id',C.c_uint8*32),('enhancement_scale_contract_id',C.c_uint8*32),('mapping',native.Mapping),('nlq',native.NLQ*3)]

def plan_for(vector):
    p=Plan();p.version=1;p.width=p.height=4;p.input_format=1;p.enhancement_enabled=1;p.output_depth=vector.output_depth
    p.textures[:]=range(1,6)
    p.frame_id[0]=p.guide_frame_id[0]=p.enhancement_frame_id[0]=1
    p.guide_contract_id[0]=2;p.enhancement_scale_contract_id[0]=3
    _,p.mapping=native._mapping(vector.mapping)
    for i in range(3):
        n=p.nlq[i];n.bit_depth=vector.mapping.bit_depth;n.denominator=vector.mapping.denominator
        n.offset=1<<(n.bit_depth-1)
    return p

class BackendHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory();cls.binary=Path(cls.directory.name)/'backend.so'
        command=['cc','-std=c11','-O2','-fno-lto','-fPIC','-shared','-Wall','-Wextra','-Werror','-Wconversion','-Wshadow','-DYB_GPU_BACKEND_HOST_ONLY','-I',str(ENGINE),'-I',str(ROOT/'engine'/'include'),*shlex.split(os.environ.get('YB_GPU_FRAME_TEST_CFLAGS','')),str(ENGINE/'native_gpu_composer_backend.c'),str(ENGINE/'native_gpu_guard.c'),str(ROOT/'engine'/'src'/'native_composer.c'),'-o',str(cls.binary)]
        r=subprocess.run(command,capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr)
        cls.lib=C.CDLL(str(cls.binary))
        cls.lib.yb_gpu_backend_validate_plan.argtypes=[C.POINTER(Plan)];cls.lib.yb_gpu_backend_validate_plan.restype=C.c_int
        cls.lib.yb_gpu_backend_pack_metadata.argtypes=[C.POINTER(Plan),C.c_uint32,C.POINTER(C.c_int64)];cls.lib.yb_gpu_backend_pack_metadata.restype=C.c_int
        cls.lib.yb_gpu_backend_submit.argtypes=[C.c_void_p,C.POINTER(Plan)];cls.lib.yb_gpu_backend_submit.restype=C.c_int
    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()
    def test_metadata_corpus_valid_vs_unsupported(self):
        for v in vector_fixtures():
            p=plan_for(v)
            expected=0 if v.mapping.bit_depth==10 and width_oracle(v.mapping)['supported'] else 3
            self.assertEqual(self.lib.yb_gpu_backend_validate_plan(C.byref(p)),expected,v.name)
    def test_all_419_packed_words(self):
        for v in vector_fixtures():
            p=plan_for(v)
            if self.lib.yb_gpu_backend_validate_plan(C.byref(p)):continue
            for c in range(3):
                words=(C.c_int64*419)(*([77]*419))
                self.assertEqual(self.lib.yb_gpu_backend_pack_metadata(C.byref(p),c,words),0)
                n=p.nlq[c];curve=p.mapping.components[c]
                expected=[16 if c==0 else 4,c,1,p.output_depth,10,p.mapping.denominator,n.bit_depth,n.offset,n.slope,n.threshold,n.maximum]
                for mapping in p.mapping.components:expected.extend((mapping.pivots[0],mapping.pivots[mapping.pivot_count-1]))
                expected.extend((curve.pivot_count,*curve.pivots))
                for segment in curve.segments:
                    expected.extend((segment.method,segment.order,segment.constant))
                    expected.extend(v for row in segment.coefficients for v in row)
                self.assertEqual(len(expected),419);self.assertEqual(list(words),expected)
    def test_wide_does_not_hide_late_bad_nlq_and_atomic_pack(self):
        v=next(v for v in vector_fixtures() if not width_oracle(v.mapping)['supported'])
        p=plan_for(v);self.assertEqual(self.lib.yb_gpu_backend_validate_plan(C.byref(p)),3)
        words=(C.c_int64*419)(*([77]*419));before=bytes(words)
        self.assertEqual(self.lib.yb_gpu_backend_pack_metadata(C.byref(p),1,words),3);self.assertEqual(bytes(words),before)
        p.nlq[2].denominator-=1
        self.assertEqual(self.lib.yb_gpu_backend_validate_plan(C.byref(p)),2)
        self.assertEqual(self.lib.yb_gpu_backend_pack_metadata(C.byref(p),1,words),2);self.assertEqual(bytes(words),before)
    def test_geometry_tokens_alias_and_invalid_component_atomic(self):
        v=vector_fixtures()[0]
        for field,value in (('version',2),('width',3),('height',2162),('input_format',2),('enhancement_enabled',2),('output_depth',16)):
            p=plan_for(v);setattr(p,field,value);self.assertEqual(self.lib.yb_gpu_backend_validate_plan(C.byref(p)),1)
        for field in ('frame_id','guide_contract_id','enhancement_scale_contract_id'):
            p=plan_for(v);getattr(p,field)[0]=0;self.assertEqual(self.lib.yb_gpu_backend_validate_plan(C.byref(p)),1)
        p=plan_for(v);p.guide_frame_id[0]=9;self.assertEqual(self.lib.yb_gpu_backend_validate_plan(C.byref(p)),1)
        p=plan_for(v);p.textures[4]=p.textures[0];self.assertEqual(self.lib.yb_gpu_backend_validate_plan(C.byref(p)),1)
        p=plan_for(v);words=(C.c_int64*419)(*([77]*419));before=bytes(words)
        self.assertEqual(self.lib.yb_gpu_backend_pack_metadata(C.byref(p),3,words),1);self.assertEqual(bytes(words),before)
        before=bytes(p);alias=C.cast(C.byref(p),C.POINTER(C.c_int64))
        self.assertEqual(self.lib.yb_gpu_backend_pack_metadata(C.byref(p),0,alias),1);self.assertEqual(bytes(p),before)
    def test_host_build_never_dispatches(self):
        p=plan_for(vector_fixtures()[0]);self.assertEqual(self.lib.yb_gpu_backend_submit(None,C.byref(p)),3)
        p.nlq[2].denominator-=1;self.assertEqual(self.lib.yb_gpu_backend_submit(None,C.byref(p)),2)
    def test_source_three_planes_one_fence_and_frame_error(self):
        c=(ENGINE/'native_gpu_composer_backend.c').read_text();s=(ENGINE/'native_gpu_composer_backend.comp').read_text()
        submit=c.split('int yb_gpu_backend_submit',1)[1].split('int yb_gpu_backend_finish',1)[0]
        self.assertIn('yb_gpu_backend_validate_plan(p);if(status)return status;',submit)
        self.assertIn('for(uint32_t c=0;c<3;c++)',submit)
        self.assertEqual(submit.count('g->DispatchCompute('),1);self.assertEqual(submit.count('g->FenceSync('),1)
        self.assertNotIn('ClientWaitSync(',submit);self.assertNotIn('GetBufferSubData(',submit)
        self.assertIn('g->GetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,4,&error)',c)
        self.assertIn('if(error)return YB_GPU_BACKEND_FRAME_REJECTED',c)
        self.assertNotIn('eglCreate',c);self.assertNotIn('fopen(',c)
        destroy=c.split('int yb_gpu_backend_destroy',1)[1].split('int yb_gpu_backend_abandon',1)[0]
        self.assertLess(destroy.index('if(g->GetError()!=GL_NO_ERROR)'),destroy.index('g->DeleteTextures'))
        self.assertIn('b->outputs[i]=0',destroy);self.assertIn('b->buffers[i]=0',destroy)
        self.assertIn('b->program=0',destroy)
        self.assertIn('for(int32_t s=0;s<curve->pivot_count-1;s++)',c)
        self.assertIn('atomicOr(frame_error,1u)',s)
        self.assertEqual(s.count('imageStore('),3)
        self.assertNotIn('Results {',s);self.assertNotIn('samples[]',s)
        arithmetic=(ENGINE/'native_gpu_texture_streamed_probe.comp').read_text()
        self.assertEqual(s.split('int64_t floor_power_two',1)[1].split('void main()',1)[0],arithmetic.split('int64_t floor_power_two',1)[1].split('void main()',1)[0])
        self.assertEqual(s.split('    int64_t original=',1)[1].split('    uvec4 value=',1)[0],arithmetic.split('    int64_t original=',1)[1].split('    results[index]=',1)[0])

if __name__=='__main__':unittest.main()
