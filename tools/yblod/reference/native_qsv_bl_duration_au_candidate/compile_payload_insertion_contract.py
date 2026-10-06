#!/usr/bin/env python3
"""Owned, bounded CPU-only insertion fixture; no media or decoder execution."""
import hashlib,json,os,subprocess
from pathlib import Path
SOURCE=Path('/source');OUT=Path('/lab')
SDK=Path('/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain')
PINS={'native_qsv_bl_payload_guard-insertion-rule.h':'4bfeca5759fea80cb55a5fbe42ec2621db99751c11ac9809076a40ae39ddce44',
      'test_payload_insertion_rule.c':'bf72328e25bdb4941585de2e5023331924b35a3e03c28b7079fa84da68aeaa2c'}
def guard():
 for name,wanted in PINS.items():assert hashlib.sha256((SOURCE/name).read_bytes()).hexdigest()==wanted
def resources():
 c=Path('/sys/fs/cgroup');q,p=(c/'cpu.max').read_text().split();assert q!='max' and 0<int(q)<=int(p)
 assert int((c/'memory.max').read_text())==536870912 and int((c/'memory.swap.max').read_text())==0
 return c
def main():
 c=resources();guard();binary=OUT/'test_payload_insertion_rule'
 subprocess.run([str(SDK/'bin/x86_64-libreelec-linux-gnu-gcc'),'-std=c11','-Wall','-Wextra','-Werror','-O2','-fno-lto','-I/source',str(SOURCE/'test_payload_insertion_rule.c'),'-o',str(binary)],check=True,timeout=60,env=dict(os.environ,CCACHE_DISABLE='1'))
 lib=SDK/'x86_64-libreelec-linux-gnu/sysroot/usr/lib'
 subprocess.run([str(lib/'ld-linux-x86-64.so.2'),'--library-path',str(lib),str(binary)],check=True,timeout=10)
 guard();c=resources();peak=int((c/'memory.peak').read_text());events={k:int(v) for k,v in (r.split() for r in (c/'memory.events').read_text().splitlines())}
 assert 0<peak<=536870912 and not any(events.values()) and int((c/'memory.swap.current').read_text())==int((c/'memory.swap.peak').read_text())==0
 result={'scope':'CPU synthetic upstream insertion contract only; no media or hardware','all_passed':True,'cases':14,'source_sha256':PINS,'peak_memory_bytes':peak,'memory_events':events,'swap_peak_bytes':0}
 (OUT/'contract-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
