"""Exact correction-table synthetic host guards; no hardware speed claim."""
import os
from pathlib import Path
import shlex
import subprocess

import test_native_gpu_scaled_frame_preloaded_probe as base

ROOT = Path(__file__).resolve().parent


class GPUScaledFrameNLQLUTHostTests(base.GPUScaledFramePreloadedHostTests):
    source_name = "native_gpu_scaled_frame_nlq_lut_probe.c"
    report_schema = "yblod.native-gpu-scaled-frame-nlq-lut-probe.v1"

    def validated(self, result, counts, dispatches):
        report = super().validated(result, counts, dispatches)
        self.assertEqual(report["lut_entries"], 3072)
        self.assertEqual(report["lut_bytes"], 12288)
        self.assertIs(report["lut_setup_in_warm_timing"], False)
        self.assertEqual(report["lut_upload_wall_ns"], 0)
        for field in ("lut_generation_wall_ns", "lut_generation_cpu_ns"):
            self.assertIs(type(report[field]), int)
            self.assertGreaterEqual(report[field], 0)
        return report

    def test_source_keeps_cpu_subchunks_and_suffix_indices(self):
        source = (ROOT / self.source_name).read_text()
        self.assertIn("enum { CHUNK=65536, GPU_BATCH=262144, NLQ_LUT_ENTRIES=3072 };", source)
        self.assertEqual(source.count(
            "uint32_t subcount=n-offset;if(subcount>CHUNK)subcount=CHUNK;"), 2)
        self.assertIn("dispatch(w,c,substart,subcount,&reference,NULL,scratch)", source)
        self.assertIn("suffix_offset(final_gpu_count,last_count,&suffix)", source)
        self.assertIn("size_t index=(size_t)suffix+i;", source)

    def test_source_table_upload_is_cold_and_not_each_warm_chunk(self):
        # Structural contract check only; no graphics APIs execute.
        source = (ROOT / self.source_name).read_text()
        allocation = source.index("gl.GenBuffers(4,buffers)")
        warm_passes = source.index("for(unsigned pass=0;pass<5;pass++)", allocation)
        self.assertIn("NLQ_LUT_ENTRIES*sizeof(int32_t)", source[allocation:warm_passes])
        self.assertIn("i==3 ? (const void *)lut", source[allocation:warm_passes])
        upload = source.index('operation="chunk SSBO upload";', warm_passes)
        fence = source.index('operation="preload completion fence";', upload)
        self.assertIn("for(GLuint i=0;i<3;i++)", source[upload:fence])
        self.assertIn("GLuint i=slot==0?3:slot-1;", source[allocation:warm_passes])
        self.assertIn("uploaded_lut!=GL_CONDITION_SATISFIED", source[allocation:warm_passes])
        self.assertIn('\\"lut_setup_in_warm_timing\\":false', source)
        self.assertIn('\\"lut_upload_in_cold_setup\\":true', source)

    def test_lut_exhaustive_reference_floor_limits_reconfiguration_and_atomicity(self):
        directory = Path(self.directory.name)
        harness = directory / "nlq-lut-helper.c"
        harness.write_text('#define main yb_lut_original_main\n#include "'
            + str(ROOT / self.source_name) + '"\n#undef main\n' + r'''
static int compare_all(struct yb_nlq_config configs[3],int32_t table[3072])
{
 if(build_nlq_lut(configs,table)!=YB_OK)return 1;
 for(unsigned c=0;c<3;c++)for(unsigned code=0;code<1024;code++){
  int64_t expected=INT64_MIN;
  if(yb_nlq(&configs[c],(int64_t)code,&expected)!=YB_OK||
     expected!=table[c*1024+code])return 2;
 }
 return 0;
}
int main(void)
{
 struct yb_nlq_config configs[3];int32_t table[3072],saved[3072];
 for(unsigned c=0;c<3;c++)configs[c]=(struct yb_nlq_config){10,23,(int32_t)(c*511),1024,17,2048};
 if(compare_all(configs,table))return 1;
 memcpy(saved,table,sizeof(saved));
 for(unsigned c=0;c<3;c++){configs[c].offset=400+(int32_t)c;configs[c].slope=1003;}
 if(compare_all(configs,table)||!memcmp(saved,table,sizeof(saved)))return 2;
 for(unsigned c=0;c<3;c++)configs[c]=(struct yb_nlq_config){10,16,512,1,0,100};
 if(compare_all(configs,table))return 3;
 for(unsigned c=0;c<3;c++)if(table[c*1024+511]!=-1||table[c*1024+512]!=0||
  table[c*1024+513]!=0||table[c*1024]!=-100||table[c*1024+1023]!=100)return 4;
 for(unsigned c=0;c<3;c++)configs[c]=(struct yb_nlq_config){10,15,(int32_t)(c*511),65535,65535,65535};
 if(compare_all(configs,table))return 5;
 for(unsigned c=0;c<3;c++)configs[c]=(struct yb_nlq_config){10,32,(int32_t)(c*511),
  (UINT64_C(1)<<33)-1,(UINT64_C(1)<<33)-1,(UINT64_C(1)<<33)-1};
 if(compare_all(configs,table))return 6;
 for(unsigned c=0;c<3;c++)configs[c]=(struct yb_nlq_config){10,23,512,0,0,0};
 if(compare_all(configs,table))return 7;
 for(unsigned i=0;i<3072;i++)if(table[i])return 8;
 for(unsigned trial=0;trial<7;trial++){
  for(unsigned c=0;c<3;c++)configs[c]=(struct yb_nlq_config){10,23,512,1024,17,2048};
  if(trial==0){configs[2].bit_depth=8;configs[2].offset=128;}
  if(trial==1)configs[2].denominator=22;
  if(trial==2)configs[2].offset=1024;
  if(trial==3)configs[2].slope=UINT64_C(1)<<24;
  if(trial==4)configs[2].threshold=UINT64_C(1)<<24;
  if(trial==5)configs[2].maximum=UINT64_C(1)<<24;
  if(trial==6)configs[2].denominator=33;
  for(unsigned i=0;i<3072;i++)table[i]=INT32_C(123456789);
  memcpy(saved,table,sizeof(saved));
  if(build_nlq_lut(configs,table)==YB_OK||memcmp(saved,table,sizeof(saved)))return 9;
 }
 if(build_nlq_lut(NULL,table)==YB_OK||memcmp(saved,table,sizeof(saved)))return 10;
 if(build_nlq_lut(configs,NULL)==YB_OK)return 11;
 union {int32_t table[3072];struct yb_nlq_config configs[3];} alias;
 for(unsigned i=0;i<3072;i++)alias.table[i]=INT32_C(123456789);
 memcpy(saved,alias.table,sizeof(saved));
 if(build_nlq_lut(alias.configs,alias.table)==YB_OK||memcmp(saved,alias.table,sizeof(saved)))return 12;
 return 0;
}
''')
        binary = directory / "nlq-lut-helper"
        compiled = subprocess.run(["cc", "-std=c11", "-O2", "-fno-lto",
            "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
            "-DYB_GPU_PROBE_HOST_ONLY", "-I", str(ROOT),
            *shlex.split(os.environ.get("YB_GPU_FRAME_TEST_CFLAGS", "")),
            str(harness), *(str(ROOT / name) for name in (
                "native_gpu_guard.c", "native_gpu_probe_fixture.c",
                "native_mmr_composer.c", "native_scaled_surface.c",
                "native_decoder_frame_bridge.c", "native_integration_probe.c",
                "native_composer.c", "native_sampling_probe.c")),
            "-o", str(binary)], capture_output=True, text=True)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        result = subprocess.run([str(binary)], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
