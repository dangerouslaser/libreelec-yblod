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
 "native_qsv_bl_compare_probe.c": "90a80193c1441f60c478894f15182ec65b1660b0e078a0093dd4df24a4b337e6",
 "test_native_qsv_bl_duration.c": "f4c65c177bb8ba1da9619371effeae8e8bf86494f8f42ac15b6d38d065d6f654",
 "test_native_qsv_bl_lifecycle.c": "22e02ad3dc7483f0de9a10c80d59f8879101878ed93362783c9018b26bfd98b9",
 "test_native_qsv_bl_pair_coverage.c": "6930fc44908a052f0c353a1ed1ee4657b1bd6c4df66ec65bb7fbe3322e7a7d5e",
 "native_qsv_bl_duration.h": "533a4568c6ce4d5abeaa4d799408c19a8ffa12f97a41c837f2d9ee2100a9847f",
 "native_qsv_bl_metadata_equal.h": "e04c0cc131a266250da1b9ad7b874a6a5247df013d944dbbd98a38305f30dc25",
 "native_qsv_bl_pair_coverage.h": "91b66775ba1477800d505a3d83b1a6c52e179840a074a11c020691438279d038",
 "native_qsv_bl_payload_guard.h": "a2aeb9de033c91ad2ecbf970443de9c3678cb74bbc62a72260f81b08329862e1",
 "native_qsv_bl_rpu_coverage.h": "ba90f277daa009b2bdeb862c0a7cb486ae79d6e6dbcd4858d8a454809481fa9b",
 "native_qsv_probe_handshake.h": "10d273de5c74f8f24e45d5b7dac6667541b4d4af4258a3a322b3c2037caec6d5"
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
 subprocess.run(['python3',str(SOURCE/'test_observe_picture_transport_qsv_bl_probe.py')],check=True,timeout=30)
 subprocess.run(['python3',str(SOURCE/'test_observe_picture_lifecycle_qsv_bl_probe.py')],check=True,timeout=30)
 guard();v=resources();events={k:int(n) for k,n in (x.split() for x in v['memory.events'].splitlines())}
 assert 0<int(v['memory.peak'])<=536870912 and not any(events.values()) and int(v['memory.swap.current'])==int(v['memory.swap.peak'])==0
 result={'compile_and_cpu_tests_passed':True,'hardware_or_media_executed':False,'duration_conversion_cases':14,'source_sha256':PINS,'outputs':outputs,'peak_memory_bytes':int(v['memory.peak']),'memory_events':events,'swap_peak_bytes':0}
 (OUT/'compile-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
