"""Code-only explicit target loader listings; no Kodi or probe execution."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from observe_live_el_qsv_probe_1536 import code_fingerprint,resources

PROBE_SHA='da9791a63a48638be26098c85f728cfae31f3e6f5ea07618671365354b718367'
CODEC_SHA='60084d80290a491b1d37c104437ffc8c75e2033416e0f61c64bd29d4668230fc'
DRIVER_SHA='fca0ac8e50a27e9278b8ad17b488dd662af34eb5cd48fe3670e7d7971b3d7d7f'
RECEIPT_SHA='6308730700ad4d2094f57eedf8ace81fe747253eb818317c4f15e25fbc8aeb89'
CORE={'/usr/lib/ld-linux-x86-64.so.2':'3bd22d737cff5359c57bd420318561e34a9cffb9738a65feb5d0b56ded9f0126',
 '/storage/yblod-qsv-el-aff416-runtime/lib/libvpl.so.2.17':'299c300702dff1464781bbaba3cb6037bd8ddabdfd9241708a9ba877baca02d0',
 '/storage/yblod-qsv-el-aff416-runtime/lib/libmfx-gen.so.1.2.17':'a0e2acafa74214e7d6247dca26168a0814a51065aa08d09e99ad0990c3baf13c'}
LIBS={
 'libavcodec.so.63':CODEC_SHA,
 'libavdevice.so.63':'3e2af51ed6ac166e765e8ab338376df25cf5cff6d61295be824f4407b266d39d',
 'libavfilter.so.12':'61d43c0e242dd9eb4c56697ed6e6dcc8f16976f536a462d96add5407016028cf',
 'libavformat.so.63':'c2efe42da66a6abe79b8decf299a7c8d7ac6c975f75858a54518e8b833de2660',
 'libavutil.so.61':'87c9577f0ede0948ce199dbb54a1380c20b5ae9b4e8a6ee0a6ddf1aa450719c1',
 'libpostproc.so.59':'1f9d7856c3bbf069bbf4f2c96a7d5e16f3157a22f81b21d8f10beea83dba8f75',
 'libswresample.so.7':'72ee1b7f34ca9b7231a290e96362f668370d3e6cf201e126961f5289f287a634',
 'libswscale.so.10':'ad867d0a6cff3b0b4cd93b33d7aa7e924d04908f87492185ef56dca9591f02bd'}

def resolved_rows(stdout,runtime,vpl):
    assert 'not found' not in stdout.lower(),'Unresolved loader dependency'
    rows=[]
    for row in stdout.splitlines():
        found=re.match(r'\s*(\S+) => (/\S+) \(',row)
        if found:
            name,path=found.groups()
            path=Path(path).resolve(strict=True)
            assert path.is_relative_to('/usr/lib') or path.is_relative_to(runtime) or path.is_relative_to(vpl)
            if re.match(r'lib(?:avcodec|avdevice|avfilter|avformat|avutil|postproc|swresample|swscale)\.so',name):
                assert name in LIBS and path==(runtime/name).resolve(strict=True),'FFmpeg escaped staged overlay'
            rows.append((name,path))
    assert rows,'Nonempty dependency listing required'
    return rows

def main():
    p=argparse.ArgumentParser()
    for n in ('binary','output'):
        p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args()
    os.umask(0o077)
    caps=resources()
    assert caps['memory_limit_bytes']==536870912 and caps['swap_limit_bytes']==0 and 0<caps['cpu_limit']<=1
    runtime=Path('/storage/yblod-bl-el-keyflag-runtime-20261006/lib')
    vpl=Path('/storage/yblod-qsv-el-aff416-runtime/lib')
    driver=Path('/usr/lib/dri/iHD_drv_video.so').resolve(strict=True)
    loader=Path('/usr/lib/ld-linux-x86-64.so.2').resolve(strict=True)
    assert code_fingerprint(a.binary)[1]==PROBE_SHA
    receipt=runtime.parent/'artifacts-private.json'
    assert code_fingerprint(receipt)[1]==RECEIPT_SHA
    admitted=json.loads(receipt.read_text())
    assert set(admitted)==set(LIBS)|{'kodi.bin'}
    assert admitted['kodi.bin']['sha256']=='0436e639c1f549316cfe960c5bbf7c1eadd2d2a57bdff741ad9295176e47b5c3'
    for path,digest in CORE.items():assert code_fingerprint(path)[1]==digest
    for name,digest in LIBS.items():
        assert admitted[name]['sha256']==digest and (runtime/name).stat().st_size==admitted[name]['bytes']
    for name,digest in LIBS.items():assert code_fingerprint(runtime/name)[1]==digest
    assert code_fingerprint(driver)[1]==DRIVER_SHA
    assert not a.output.exists() and not a.output.is_symlink()
    library_path=str(runtime)+':'+str(vpl)
    files={}
    # Shared objects are listed by the system loader, never dlopened/executed.
    for binary in (a.binary,vpl/'libvpl.so.2.17',vpl/'libmfx-gen.so.1.2.17',driver):
        result=subprocess.run([str(loader),'--library-path',library_path,'--list',str(binary)],capture_output=True,text=True,timeout=15)
        assert result.returncode==0 and not result.stderr
        for name,path in resolved_rows(result.stdout,runtime,vpl):
            item={'path':str(path),'sha256':code_fingerprint(path)[1]}
            assert name not in files or files[name]==item
            files[name]=item
    for name,path in (('ld-linux-x86-64.so.2',loader),('libvpl.so.2',vpl/'libvpl.so.2.17'),('libmfx-gen.so.1.2',vpl/'libmfx-gen.so.1.2.17')):
        path=path.resolve(strict=True)
        item={'path':str(path),'sha256':code_fingerprint(path)[1]}
        assert name not in files or files[name]==item
        files[name]=item
    assert files['libavcodec.so.63']['sha256']==CODEC_SHA
    for name,digest in LIBS.items():
        assert code_fingerprint(runtime/name)[1]==digest
        if name in files:assert files[name]['path']==str((runtime/name).resolve(strict=True)) and files[name]['sha256']==digest
    for name,item in files.items():
        assert code_fingerprint(item['path'])[1]==item['sha256']
    assert code_fingerprint(receipt)[1]==RECEIPT_SHA
    for path,digest in CORE.items():assert code_fingerprint(path)[1]==digest
    with a.output.open('x') as stream:json.dump({'files':files},stream,indent=2)
    caps=resources()
    assert not any(caps['memory_events'].values()) and caps['swap_current_bytes']==caps['swap_peak_bytes']==0
    print(json.dumps({'pass':True,'code_only_closure_files':len(files),'probe_executed':False,'kodi_executed':False,
                      'manifest_sha256':code_fingerprint(a.output)[1],'resources':caps}))

if __name__=='__main__':
    try:main()
    except BaseException as error:
        result={'pass':False,'error_type':type(error).__name__,'probe_executed':False,'kodi_executed':False}
        try:result['resources']=resources()
        except BaseException:result['resource_evidence_missing']=True
        print(json.dumps(result))
        raise SystemExit(1)
