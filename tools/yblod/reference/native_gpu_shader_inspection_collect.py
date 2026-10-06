"""One public synthetic shader inspection; no movie inputs or timing claims."""
import hashlib,json,os,pathlib,subprocess,sys,time

SOURCE=pathlib.Path('/storage/yblod-native-gpu-probe-20261005b')
PINS={'native_gpu_probe':'3b620fa0112736879bbadd5709876408566deb83b4bf4d11f960f629f0f81019','native_gpu_probe.c':'e51107f2d3c30bb96045f8388442a6f0d35eda56426227a387894023e15468e2','native_gpu_probe.comp':'a708d8c27ff75effdf166fbfe3f5cae88ffaec34a784f234441ed1cc96d166bb'}
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def resources():
    cg=next(x.split(':',2)[2] for x in pathlib.Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
    root=pathlib.Path('/sys/fs/cgroup')/cg.lstrip('/')
    return {n:(root/n).read_text().strip() for n in ('memory.max','memory.peak','memory.swap.max','memory.swap.current','memory.events')}
def kodi():
    result=[]
    for p in pathlib.Path('/proc').iterdir():
        if p.name.isdigit():
            try:
                if (p/'comm').read_text().strip()=='kodi.bin':result.append({'pid':int(p.name),'stat':(p/'stat').read_text().split(') ',1)[1].split()[19]})
            except (OSError,IndexError):pass
    return result
def main():
    root=pathlib.Path(sys.argv[1]);root.mkdir();(root/'dumps').mkdir()
    assert all(sha(SOURCE/n)==v for n,v in PINS.items())
    sys.path.insert(0,str(SOURCE))
    from native_gpu_vectors import vector_fixtures
    from native_gpu_probe import encode
    from native_gpu_run import validate_cpu,validate_gpu
    v=next(v for v in vector_fixtures() if v.name=='mmr3-all-channel-clamps')
    fixture=root/(v.name+'.bin');fixture.write_bytes(encode(v.mapping,v.nlq,v.component,v.triplets,v.el_samples,v.output_depth))
    report={'schema':'yblod.synthetic-shader-inspection.v1','source_sha256':PINS,'fixture_sha256':sha(fixture),'samples':len(v.triplets),'resources_before':resources(),'kodi_before':kodi(),'interpretation':'Compiler inspection only; not playback performance or private media.'}
    r=subprocess.run([str(SOURCE/'native_gpu_probe'),'--validate',str(fixture)],capture_output=True,timeout=30)
    assert r.returncode==0 and validate_cpu(json.loads(r.stdout),v)
    (root/'cpu.json').write_bytes(r.stdout)
    report['independent_cpu_gate_passed']=True
    env=os.environ.copy();flags={'INTEL_DEBUG':'cs,ann,perf','INTEL_SHADER_BIN_DUMP_PATH':str(root/'dumps'),'MESA_SHADER_CACHE_DISABLE':'true'};env.update(flags)
    argv=[str(SOURCE/'native_gpu_probe'),'/dev/dri/renderD128',str(SOURCE/'native_gpu_probe.comp'),str(fixture)]
    report.update(argv=argv,debug_environment=flags)
    loaded=set()
    with (root/'gpu.json').open('xb') as out,(root/'compiler.log').open('xb') as err:
        p=subprocess.Popen(argv,stdout=out,stderr=err,env=env)
        deadline=time.monotonic()+30
        while p.poll() is None:
            try:
                for line in pathlib.Path('/proc',str(p.pid),'maps').read_text().splitlines():
                    fields=line.split();path=fields[-1]
                    if path.startswith('/') and '.so' in path:loaded.add(path)
            except OSError:pass
            if time.monotonic()>deadline:p.kill();p.wait();raise RuntimeError('30-second timeout')
            time.sleep(.005)
    assert p.returncode==0
    validate_gpu(json.loads((root/'gpu.json').read_text()),v)
    assert all(sha(SOURCE/n)==v for n,v in PINS.items())
    report.update(status='exact',exit_status=p.returncode,resources_after=resources(),kodi_after=kodi(),loaded_library_sha256={s:sha(s) for s in sorted(loaded)},artifact_sha256={str(s.relative_to(root)):sha(s) for s in root.rglob('*') if s.is_file()})
    assert report['kodi_before']==report['kodi_after']
    (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
if __name__=='__main__':main()
