"""Explicit opt-in synthetic corpus gate for the isolated streamed MMR shader."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import stat
import sys

CANDIDATE_SHA='5c58ab7ae0f7220a360026153f4d4e5d0592bf00c9d660ce570cb553f531b64a'
BINARY_SHA='3b620fa0112736879bbadd5709876408566deb83b4bf4d11f960f629f0f81019'
BASELINE_SHA='a708d8c27ff75effdf166fbfe3f5cae88ffaec34a784f234441ed1cc96d166bb'

def run(source,candidate,destination):
    source=source.resolve(strict=True);candidate=candidate.resolve(strict=True)
    sys.path.insert(0,str(source))
    from native_gpu_probe import encode
    from native_gpu_vectors import vector_fixtures
    from native_gpu_run import digest,validate_cpu,validate_gpu,cgroup_snapshot,SOURCES
    binary=source/'native_gpu_probe'
    if digest(binary)!=BINARY_SHA or digest(candidate)!=CANDIDATE_SHA or digest(source/'native_gpu_probe.comp')!=BASELINE_SHA:
        raise ValueError('reviewed executable/baseline/candidate pins required')
    pins={name:digest(source/name) for name in SOURCES}
    root=destination.resolve();root.mkdir();(root/'dumps').mkdir()
    def kodi():
        result=[]
        for p in Path('/proc').iterdir():
            if p.name.isdigit():
                try:
                    if (p/'comm').read_text().strip()=='kodi.bin':result.append([int(p.name),(p/'stat').read_text().split(') ',1)[1].split()[19]])
                except (OSError,IndexError):pass
        return sorted(result)
    runner_pin=digest(Path(__file__))
    report=dict(schema='yblod.streamed-mmr-synthetic-run.v1',status='failed',candidate_sha256=CANDIDATE_SHA,binary_sha256=BINARY_SHA,baseline_shader_sha256=BASELINE_SHA,source_sha256=pins,runner_sha256=runner_pin,cases=[],cgroup_before=cgroup_snapshot(),kodi_before=kodi(),interpretation='Synthetic whole-code arithmetic and compiler inspection only; not real-frame performance or production playback.')
    runtime=[Path('/usr/lib/libgallium-26.2.4.so'),Path('/usr/lib/libEGL_mesa.so.0.0.0')]
    def runtime_digest(path):
        with path.open('rb') as stream:
            before=os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=64*1024*1024:raise ValueError('bounded runtime library required')
            h=hashlib.sha256();total=0
            while block:=stream.read(65536):
                total+=len(block)
                if total>64*1024*1024:raise ValueError('runtime library grew')
                h.update(block)
            after=os.fstat(stream.fileno())
            if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('runtime library changed')
            return h.hexdigest()
    report['runtime_library_sha256_before']={str(p):runtime_digest(p) for p in runtime}
    vectors=vector_fixtures()
    if len(vectors)!=32:raise ValueError('reviewed32-fixture corpus required')
    def unchanged():
        if digest(Path(__file__))!=runner_pin or digest(binary)!=BINARY_SHA or digest(candidate)!=CANDIDATE_SHA or any(digest(source/n)!=h for n,h in pins.items()):
            raise ValueError('source/artifact changed')
    def invoke(v,argv,phase,debug=False):
        unchanged();env=os.environ.copy()
        # Debug controls are child-only and used on exactly one public MMR3 case.
        for name in ('INTEL_DEBUG','INTEL_SHADER_BIN_DUMP_PATH','MESA_SHADER_CACHE_DISABLE','INTEL_SIMD_DEBUG'):
            env.pop(name,None)
        if debug:env.update(INTEL_DEBUG='cs,ann,perf',INTEL_SHADER_BIN_DUMP_PATH=str(root/'dumps'),MESA_SHADER_CACHE_DISABLE='true')
        r=subprocess.run(argv,env=env,capture_output=True,timeout=30)
        if len(r.stdout)>4*1024*1024 or len(r.stderr)>8*1024*1024:raise ValueError('bounded logs required')
        for kind,data in (('stdout',r.stdout),('stderr',r.stderr)):
            with (root/(v.name+'-'+phase+'.'+kind+'.log')).open('xb') as stream:stream.write(data)
        unchanged()
        return r,json.loads(r.stdout)
    try:
        accepted=[]
        for v in vectors:
            fixture=root/(v.name+'.bin')
            with fixture.open('xb') as stream:stream.write(encode(v.mapping,v.nlq,v.component,v.triplets,v.el_samples,v.output_depth))
            r,cpu=invoke(v,[str(binary),'--validate',str(fixture)],'cpu')
            eligible=validate_cpu(cpu,v)
            if r.returncode!=(0 if eligible else 3):raise ValueError('CPU validation exit mismatch')
            case=dict(name=v.name,fixture_sha256=digest(fixture),cpu=cpu,gpu_eligible=eligible)
            report['cases'].append(case)
            if eligible:accepted.append((v,case,fixture))
        report['all_independent_cpu_gates_complete']=True
        accepted.sort(key=lambda item:item[0].name!='mmr3-all-channel-clamps')
        if len(accepted)!=31 or sum(len(v.triplets) for v,_,_ in accepted)!=2128 or accepted[0][0].name!='mmr3-all-channel-clamps':raise ValueError('reviewed corpus eligibility changed')
        for i,(v,case,fixture) in enumerate(accepted):
            r,gpu=invoke(v,[str(binary),'/dev/dri/renderD128',str(candidate),str(fixture)],'gpu',debug=i==0)
            if r.returncode!=0:raise ValueError('GPU exit failed')
            validate_gpu(gpu,v);case['gpu']=gpu
            if digest(fixture)!=case['fixture_sha256']:raise ValueError('fixture changed')
        report.update(status='complete',gpu_case_count=len(accepted),unsupported_case_count=1,checked_stage_values=sum(len(v.triplets)*4 for v,_,_ in accepted))
    except Exception as error:
        report['error']=dict(type=type(error).__name__,message=str(error))
    report.update(cgroup_after=cgroup_snapshot(),kodi_after=kodi(),runtime_library_sha256_after={str(p):runtime_digest(p) for p in runtime})
    if report['kodi_before']!=report['kodi_after'] or report['runtime_library_sha256_before']!=report['runtime_library_sha256_after']:
        report['status']='failed';report['identity_changed']=True
    with (root/'report.json').open('x') as stream:json.dump(report,stream,indent=2)
    print(json.dumps(dict(status=report['status'],cases=len(report['cases']),gpu_case_count=report.get('gpu_case_count',0),checked_stage_values=report.get('checked_stage_values',0),error=report.get('error'))))
    return 0 if report['status']=='complete' else 1

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('reviewed_source_directory',type=Path);p.add_argument('candidate_shader',type=Path);p.add_argument('new_output_directory',type=Path)
    args=p.parse_args()
    return run(args.reviewed_source_directory,args.candidate_shader,args.new_output_directory)

if __name__=='__main__':sys.exit(main())
