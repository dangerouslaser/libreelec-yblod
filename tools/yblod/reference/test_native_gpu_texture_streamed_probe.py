"""Host-only normalized texture ABI guards; no GPU/VA import is executed."""
import os
from pathlib import Path
import shlex
import struct
import subprocess
import test_native_gpu_scaled_frame_batch_probe as base

ROOT=Path(__file__).resolve().parent
ENGINE=ROOT.parents[2]/'engine'/'experimental'

class GPUTextureStreamedHostTests(base.GPUScaledFrameBatchHostTests):
    source_name='native_gpu_texture_streamed_probe.c'
    report_schema='yblod.native-gpu-texture-streamed-probe.v1'

    def test_source_keeps_cpu_subchunks_and_suffix_indices(self):
        source=(ROOT/self.source_name).read_text()
        self.assertIn('enum { CHUNK=65536, GPU_BATCH=262144 };',source)
        # Only the complete oracle gate extracts CPU subchunks; warm input
        # packing is deliberately gone, not a weakened oracle check.
        self.assertEqual(source.count('uint32_t subcount=n-offset;if(subcount>CHUNK)subcount=CHUNK;'),1)
        self.assertIn('dispatch(w,c,substart,subcount,&reference,NULL,scratch)',source)
        self.assertIn('suffix_offset(final_gpu_count,last_count,&suffix)',source)
        self.assertNotIn('input_words',source)
        self.assertIn('gl.Uniform3ui(0,width,height,(GLuint)start)',source)
        self.assertIn('gl.DeleteTextures(5,textures)',source)

    def test_shader_reuses_streamed_arithmetic_and_explicit_guide(self):
        source=(ENGINE/'native_gpu_texture_streamed_probe.comp').read_text()
        original=(ENGINE/'native_gpu_streamed_mmr_probe.comp').read_text()
        self.assertEqual(source.split('int64_t floor_power_two',1)[1].split('void main()',1)[0],original.split('int64_t floor_power_two',1)[1].split('void main()',1)[0])
        self.assertEqual(source.split('    int64_t original=',1)[1],original.split('    int64_t original=',1)[1])
        self.assertNotIn('Samples {',source)
        self.assertIn('texelFetch(prepared_guide,coordinate,0)',source)
        self.assertIn('floor(normalized*65535.0+0.5)',source)
        self.assertIn('((cb|cr|enhancement)&63u)!=0u',source)
        self.assertIn('results[index]=ivec4(-2147483647-1)',source)
        self.assertNotIn('texture(',source)

    def test_float32_normalized_word_recovery_model_exhaustive(self):
        def f32(value):return struct.unpack('<f',struct.pack('<f',value))[0]
        for word in range(65536):
            normalized=f32(word/65535)
            recovered=int(f32(f32(normalized*65535)+0.5))
            self.assertEqual(recovered,word)
        # This is a model, not proof of an imported driver format or sampling.

    def test_actual_c_word_and_coordinate_helpers(self):
        directory=Path(self.directory.name)
        harness=directory/'texture-helpers.c'
        harness.write_text('#define main yb_texture_original_main\n#include "'+str(ROOT/self.source_name)+'"\n#undef main\n#include <math.h>\n'
          'int main(void){\n'
          ' for(uint32_t i=0;i<65536U;i++){uint16_t out=17;float n=(float)i/65535.0f;if(!texture_recover_word(n,&out)||out!=i)return 1;}\n'
          ' const float bad[]={-1.0f,2.0f,NAN,INFINITY};\n'
          ' for(unsigned i=0;i<4;i++){uint16_t out=17;if(texture_recover_word(bad[i],&out)||out!=17)return 2;}\n'
          ' if(texture_recover_word(0.0f,NULL))return 3;\n'
          ' uint32_t x=17,y=19;\n'
          ' if(!texture_coordinate(3840,2160,0,8294399,1,0,&x,&y)||x!=3839||y!=2159)return 4;\n'
          ' if(!texture_coordinate(3840,2160,2,2073599,1,0,&x,&y)||x!=1919||y!=1079)return 5;\n'
          ' if(!texture_coordinate(3840,2160,1,262143,2,1,&x,&y)||x!=1024||y!=136)return 6;\n'
          ' const uint32_t badcoords[][6]={{0,2,0,0,1,0},{2,3,0,0,1,0},{3842,2,0,0,1,0},{2,2162,0,0,1,0},{2,2,3,0,1,0},{2,2,0,4,1,0},{2,2,0,0,0,0},{2,2,0,0,262145,0},{2,2,0,0,1,1}};\n'
          ' for(unsigned i=0;i<9;i++){x=17;y=19;if(texture_coordinate(badcoords[i][0],badcoords[i][1],badcoords[i][2],badcoords[i][3],badcoords[i][4],badcoords[i][5],&x,&y)||x!=17||y!=19)return 7;}\n'
          ' if(texture_coordinate(2,2,0,0,1,0,&x,&x)||texture_coordinate(2,2,0,0,1,0,NULL,&y))return 8;\n'
          ' return 0;}\n')
        binary=directory/'texture-helpers'
        compiled=subprocess.run(['cc','-std=c11','-O2','-fno-lto','-Wall','-Wextra','-Werror','-Wconversion','-Wshadow','-DYB_GPU_PROBE_HOST_ONLY','-I',str(ROOT),*shlex.split(os.environ.get('YB_GPU_FRAME_TEST_CFLAGS','')),str(harness),*(str(ROOT/name) for name in ('native_gpu_guard.c','native_gpu_probe_fixture.c','native_mmr_composer.c','native_scaled_surface.c','native_decoder_frame_bridge.c','native_integration_probe.c','native_composer.c','native_sampling_probe.c')),'-o',str(binary)],capture_output=True,text=True)
        self.assertEqual(compiled.returncode,0,compiled.stderr)
        result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
