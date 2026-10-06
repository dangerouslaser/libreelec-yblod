#!/usr/bin/env python3
"""CPU-only fixtures and complete probe compile against the qualified copy."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

SOURCE=Path('/source'); OUT=Path('/lab'); COPY=Path('/candidate/ffmpeg-bl-qsv-candidate')
SDK=Path('/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain')
PINS={
 'native_qsv_bl_compare_probe.c':'6957b59ef987bc33e68f17d90319721f486ad2a4dfd92f53de4153d817be5ee8',
 'native_qsv_bl_duration.h':'7e336a51090d84b513438f8eac1e04c2195dc78afa9db46bf770bdca0ec29c9d',
 'native_qsv_bl_metadata_equal.h':'166050399b5425810ee08fe36762750399b141f0bec88f758cacd732c21c6a7a',
 'native_qsv_bl_pair_coverage.h':'2430fb2a6599527e39bba608a603bddd7f34237ccd4925a833faf013f3c56feb',
 'native_qsv_bl_payload_guard.h':'a4f543caf5cef13c0e326e1d0e446687f6bf017dd233bd63d40599b5a6ab9bba',
 'native_qsv_bl_rpu_coverage.h':'62174b5c92defe46bd423ceaeb99119b2dbacfcd5352c865c2fbb03c0c7a922c',
 'native_qsv_probe_handshake.h':'15eb0523b22d0c2ec6bdd87c7a4ece46566dd1d237273895e793978f35e04d7c',
 'test_native_qsv_bl_duration.c':'2b3cef37129e87650d6cf81a96d5048def82189bfebcc6e92a7c5d2193061d8c',
 'test_native_qsv_bl_lifecycle.c':'d3c474c800f8afbc8b53598dc83c4b0f0ff8a41be0cf7da05f3af0ca8c1aafe8',
 'test_native_qsv_bl_pair_coverage.c':'f89fd0c4c3a92b4a773ca9f88e8334248de403b7130ef57bc39b082cef85ae54',
}
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as s:
  for b in iter(lambda:s.read(1048576),b''):h.update(b)
 return h.hexdigest()
def guard():
 for name,want in PINS.items():assert sha(SOURCE/name)==want
 p=Path('/candidate/compatible-param-build-results.json')
 assert sha(p)=='d46b736f6288ada414b1384bdf7cba43094b5e7fe7dae4b0f008ad7c99a14cae'
 report=json.loads(p.read_text());assert report['build_completed'] is True
 for name,record in report['libraries'].items():
  assert sha(COPY/name)==record['sha256'] and (COPY/name).stat().st_size==record['bytes']
 for group in ('configuration_sha256','native_source_and_abi_sha256'):
  for name,want in report[group].items():
   assert sha(COPY/name)==want
   if group=='native_source_and_abi_sha256':assert sha(SDK.parent/'build/ffmpeg-9.0.2'/name)==want
 assert sha(COPY/'libavcodec/qsvdec.c')=='ffe1541b756e835ca2384d50192f3a244c59e68a5bd24e39de4ee5dcd9e9378d'
 return report
def resources():
 cg=Path('/sys/fs/cgroup');v={n:(cg/n).read_text().strip() for n in ('memory.max','memory.peak','memory.events','memory.swap.max','memory.swap.current','memory.swap.peak','cpu.max')}
 quota,period=v['cpu.max'].split();assert quota!='max' and 0<int(quota)<=int(period)
 assert int(v['memory.max'])==536870912 and int(v['memory.swap.max'])==0
 return v
def main():
 resources();guard(); runtime=OUT/'runtime';runtime.mkdir()
 report=json.loads(Path('/candidate/compatible-param-build-results.json').read_text())
 for name in report['libraries']:
  path=COPY/name
  (runtime/path.name).symlink_to(path)
  (runtime/(path.name.split('.so.')[0]+'.so')).symlink_to(path)
 cc=str(SDK/'bin/x86_64-libreelec-linux-gnu-gcc')
 flags=['-std=c11','-D_DEFAULT_SOURCE','-D_POSIX_C_SOURCE=200809L','-Wall','-Wextra','-Werror','-O2','-fno-lto','-fuse-ld=bfd','-ffunction-sections','-fdata-sections','-I'+str(SOURCE),'-I'+str(COPY),'-L'+str(runtime)]
 env=dict(os.environ,CCACHE_DISABLE='1')
 outputs={}
 for name in ('test_native_qsv_bl_duration','test_native_qsv_bl_pair_coverage','test_native_qsv_bl_lifecycle','native_qsv_bl_compare_probe'):
  binary=OUT/name
  subprocess.run([cc,*flags,str(SOURCE/(name+'.c')),'-Wl,--gc-sections','-lavformat','-lavcodec','-lavutil','-o',str(binary)],check=True,timeout=60,env=env)
  outputs[name]={'sha256':sha(binary),'bytes':binary.stat().st_size}
  if name.startswith('test_'):
   loader=SDK/'x86_64-libreelec-linux-gnu/sysroot/usr/lib/ld-linux-x86-64.so.2'
   libs=str(runtime)+':'+str(SDK/'x86_64-libreelec-linux-gnu/sysroot/usr/lib')+':'+str(SDK/'x86_64-libreelec-linux-gnu/lib')
   subprocess.run([str(loader),'--library-path',libs,str(binary)],check=True,timeout=30)
 guard();v=resources();events={k:int(n) for k,n in (x.split() for x in v['memory.events'].splitlines())}
 assert 0<int(v['memory.peak'])<=536870912 and not any(events.values()) and int(v['memory.swap.current'])==int(v['memory.swap.peak'])==0
 result={'compile_and_cpu_tests_passed':True,'hardware_or_media_executed':False,'duration_conversion_cases':14,'property_diagnostic_cases':17,'source_sha256':PINS,'outputs':outputs,'peak_memory_bytes':int(v['memory.peak']),'memory_events':events,'swap_peak_bytes':0}
 (OUT/'compile-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()


