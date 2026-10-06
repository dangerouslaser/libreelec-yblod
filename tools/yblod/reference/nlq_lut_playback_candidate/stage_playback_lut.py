#!/usr/bin/env python3
"""Stage pinned private copies only. No changes to supplied repositories."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

def check(root, pins):
    for name, expected in pins.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
            raise SystemExit('Source pin mismatch: '+name)

def main():
    if len(sys.argv) not in (3,4):
        raise SystemExit('usage: stage_playback_lut.py REPO FRESH_OUTPUT [CANDIDATE13_KODI_TREE]')
    repo=Path(sys.argv[1]).resolve(); out=Path(sys.argv[2]).resolve()
    package=Path(__file__).resolve().parent
    pins=json.loads((package/'source-pins.json').read_text())
    check(repo,pins['engine']); check(repo,pins['compat'])
    kodi=Path(sys.argv[3]).resolve() if len(sys.argv)==4 else None
    if kodi: check(kodi,pins['kodi'])
    out.mkdir(exist_ok=False)
    shutil.copytree(repo/'engine',out/'engine',ignore=shutil.ignore_patterns('build','__pycache__'))
    for name in pins['compat']:
        target=out/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(repo/name,target)
    for patch in ('engine.patch','compatibility.patch'):
        subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(package/patch)],cwd=out,check=True)
    for name in ('native_gpu_composer_fp32.c','native_gpu_composer_fp32.h',
                 'native_gpu_composer_fp32_backend.c','native_gpu_composer_backend_libplacebo.c',
                 'native_gpu_nlq_lut.c','native_gpu_nlq_lut.h','native_playback_context.c','native_playback_context.h'):
        shutil.copyfile(out/'engine'/'experimental'/name,out/name)
    for name in ('native_gpu_composer_fp32_compare_probe.c','test_native_gpu_nlq_lut.c',
                 'test_nlq_lut_options.c','run_nlq_lut_guard.py','prepare_nlq_lut_guard_config.py',
                 'test_nlq_lut_guard.py','build_playback_lut_gate.sh','compile_kodi_lut_gate.py'):
        shutil.copyfile(package/name,out/name)
    if kodi:
        for name in pins['kodi']:
            target=out/'kodi'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(kodi/name,target)
        subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(package/'kodi-adapter.patch')],cwd=out/'kodi',check=True)
        shutil.copyfile(out/'kodi'/'xbmc'/'cores'/'VideoPlayer'/'VideoRenderers'/'DVBridgeGLES.cpp',out/'DVBridgeGLES.cpp')
    print('Pinned playback candidate staged; input repositories unchanged.')

if __name__=='__main__': main()
