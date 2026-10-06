"""PID-namespace-local bounded C-probe observer; not a final target qualifier."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import stat
import hashlib
import time

from collect_el_qsv_target_identity import fingerprint, gpu_identity, source_stat
from target_el_qsv_live_handshake import acknowledge_unit_child, process_record
from run_target_el_qsv_probe import handshake_environment

SAFE_FAILURE_CODES={
    'Unit process generation changed':'unit_generation',
    'Exactly one actual unit child must own checkpoint':'unit_child_association',
    'Actual loader/probe invocation differs':'loader_or_argv',
    'Actual probe code mapping mismatch':'probe_code_mapping',
    'Deleted probe mapping':'deleted_probe_mapping',
    'Actual probe mapping proof required':'probe_mapping_proof',
    'Actual probe DRM client association missing':'drm_client',
    'Mapped library outside the exact isolated closure/current driver':'mapped_library_closure',
    'Actual required hardware route library not mapped':'required_mapped_library',
    'Actual live GPU client and complete mapped closure required':'live_gpu_or_closure',
    'Live proof changed before acknowledgement':'live_generation_recheck',
    'Private regular checkpoint required':'checkpoint_permissions',
    'Exact private checkpoint required':'checkpoint_identity',
}


def code_fingerprint(path):
    """Bound SDK code hashing file-cache charges; never used for movie bytes."""
    digest=hashlib.sha256()
    page_size=os.sysconf('SC_PAGE_SIZE')
    if page_size<=0 or 1048576%page_size:raise ValueError('Code cache advice requires aligned chunks')
    with Path(path).open('rb') as stream:
        before=os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):raise ValueError('Regular code artifact required')
        offset=0
        for chunk in iter(lambda:stream.read(1048576),b''):
            digest.update(chunk)
            complete=len(chunk)//page_size*page_size
            if complete:os.posix_fadvise(stream.fileno(),offset,complete,os.POSIX_FADV_DONTNEED)
            offset+=len(chunk)
        after=os.fstat(stream.fileno())
    fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
    identity=tuple(getattr(before,key) for key in fields)
    if identity!=tuple(getattr(after,key) for key in fields):raise ValueError('Code changed during fingerprint')
    return identity,digest.hexdigest()


def resources():
    relative=Path('/proc/self/cgroup').read_text().split('0::',1)[1].strip()
    root=Path('/sys/fs/cgroup')/relative.lstrip('/')
    values={name:(root/name).read_text().strip() for name in ('memory.max','memory.swap.max','cpu.max','memory.peak','memory.events','memory.swap.current','memory.swap.peak')}
    quota,period=values['cpu.max'].split()
    return dict(memory_limit_bytes=int(values['memory.max']),swap_limit_bytes=int(values['memory.swap.max']),
        cpu_limit=int(quota)/int(period),peak_memory_bytes=int(values['memory.peak']),
        memory_events={key:int(value) for key,value in (row.split() for row in values['memory.events'].splitlines())},
        swap_current_bytes=int(values['memory.swap.current']),swap_peak_bytes=int(values['memory.swap.peak']))


def observe(args,runtime_files):
    return dict(gpu=gpu_identity(args.node),input=source_stat(args.source),
        binary=code_fingerprint(args.binary),driver=code_fingerprint(args.driver),
        runtime={name:code_fingerprint(path) for name,path in runtime_files.items()})


def stop_owned_child(child):
    if child is not None and child.poll() is None:
        child.terminate()
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill();child.wait(timeout=2)


def validate_raw_report(raw,pts):
    if raw.get('pass') is not True or type(raw.get('qsv_mapped_frames')) is not int or raw['qsv_mapped_frames']<3:
        raise ValueError('Actual three mapped QSV comparisons required')
    frames=raw.get('frames')
    if not isinstance(frames,list) or len(frames)!=3:raise ValueError('Exactly three literal raw frame records required')
    for frame,expected in zip(frames,pts):
        if type(frame.get('requested_pts_microseconds')) is not int or frame['requested_pts_microseconds']!=expected:
            raise ValueError('Raw source timestamps differ from exact requested frames')
        for phase in ('before','after'):
            item=frame.get(phase,{})
            if type(item.get('pts_microseconds')) is not int or item['pts_microseconds']!=expected:
                raise ValueError('Original decoded timestamps differ from exact requested frames')
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','loader','runtime','driver','source','node','runtime-identity','private-prefix'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--binary-sha256',required=True)
    parser.add_argument('--driver-sha256',required=True)
    parser.add_argument('--seek-us',type=int,required=True)
    parser.add_argument('--pts-us',type=int,action='append',required=True)
    parser.add_argument('--extra-library-dir',type=Path,action='append',default=[])
    args=parser.parse_args()
    os.umask(0o077)
    result=dict(pass_=False,scope='Live raw EL probe diagnostic only; final raw equality and capture-target identity qualification are separate.')
    child=None;proof=None;stage='preflight'
    started=time.monotonic()
    def interrupted(*unused):raise RuntimeError('Scoped observer interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    try:
        limits=resources()
        if limits['memory_limit_bytes']!=536870912 or limits['swap_limit_bytes']!=0 or not 0<limits['cpu_limit']<=1:raise ValueError('Required observer cgroup limits absent')
        if args.seek_us!=1200000000 or len(args.pts_us)!=3 or args.pts_us!=sorted(set(args.pts_us)) or any(not args.seek_us<p<=1380000000 for p in args.pts_us):raise ValueError('Exact three source timestamps required')
        if not args.private_prefix.is_absolute():raise ValueError('Absolute private output prefix required')
        paths={name:Path(str(args.private_prefix)+suffix) for name,suffix in
            (('ready','.ready'),('ack','.ack'),('stdout','.stdout-private.json'),('stderr','.stderr-private.log'),('proof','.live-proof-private.json'))}
        if any(path.exists() or path.is_symlink() for path in paths.values()):raise ValueError('Fresh private observer paths required')
        manifest=json.loads(args.runtime_identity.read_text())
        if set(manifest)!={'files'} or not manifest['files']:raise ValueError('Reviewed explicit code closure required')
        runtime_files={name:Path(item['path']).resolve(strict=True) for name,item in manifest['files'].items()}
        before=observe(args,runtime_files)
        if before['binary'][1]!=args.binary_sha256 or before['driver'][1]!=args.driver_sha256 or any(before['runtime'][name][1]!=manifest['files'][name]['sha256'] for name in runtime_files):raise ValueError('Expected code/driver closure differs')
        loader=args.loader.resolve(strict=True);binary=args.binary.resolve(strict=True);runtime=args.runtime.resolve(strict=True)
        if not loader.is_file() or not runtime.is_dir() or loader not in runtime_files.values():raise ValueError('Expected target or SDK loader must be in closure')
        directories=[runtime]+[path.resolve(strict=True) for path in args.extra_library_dir]
        if any(not path.is_dir() for path in directories):raise ValueError('Explicit library directories required')
        library_path=':'.join(map(str,directories))
        argv=[str(loader),'--library-path',library_path,str(binary),str(args.source.resolve(strict=True)),str(args.node.resolve(strict=True)),str(args.seek_us),*(str(p) for p in args.pts_us)]
        nonce=secrets.token_hex(32)
        environment=os.environ.copy()
        environment.update(handshake_environment(paths['ready'],paths['ack'],nonce))
        environment.update(LD_LIBRARY_PATH=library_path,ONEVPL_PRIORITY_PATH=str(runtime),LIBVA_DRIVER_NAME='iHD',LIBVA_DRIVERS_PATH=str(args.driver.resolve(strict=True).parent),
            EXPECTED_QSV_LIBVPL=str((runtime/'libvpl.so.2.17').resolve(strict=True)),
            EXPECTED_QSV_IMPLEMENTATION=str((runtime/'libmfx-gen.so.1.2.17').resolve(strict=True)),
            EXPECTED_QSV_VA_DRIVER=str(args.driver.resolve(strict=True)))
        parent=process_record(os.getpid())
        with paths['stdout'].open('xb') as output,paths['stderr'].open('xb') as error:
            stage='probe_launch'
            child=subprocess.Popen(argv,env=environment,stdout=output,stderr=error)
            deadline=time.monotonic()+170
            while child.poll() is None:
                if time.monotonic()>=deadline:raise TimeoutError('Scoped probe deadline reached')
                if paths['ready'].exists() and proof is None:
                    stage='live_identity_callback'
                    proof=acknowledge_unit_child(paths['ready'],paths['ack'],nonce,parent['pid'],parent['start_ticks'],loader,binary,args.binary_sha256,argv,args.node,runtime_files,args.driver)
                    if proof['probe_pid']!=child.pid:raise ValueError('Ready checkpoint differs from actually launched child')
                    stage='remaining_raw_comparisons'
                time.sleep(.05)
        stage='post_probe_identity'
        after=observe(args,runtime_files)
        if before!=after or proof is None:raise ValueError('Identity changed or no live handshake')
        if paths['stdout'].stat().st_size>1048576:raise ValueError('Unexpected probe report extent')
        raw=json.loads(paths['stdout'].read_text())
        if child.returncode!=0 or raw.get('pass') is not True:raise ValueError('C probe did not pass after actual live acknowledgement')
        stage='raw_report_validation'
        validate_raw_report(raw,args.pts_us)
        paths['proof'].write_text(json.dumps(dict(before=before,after=after,live=proof,raw=raw)))
        result.update(pass_=True,probe_exit_code=child.returncode,live_child_identity_verified=True,
            actual_gpu_client_verified=True,actual_mapped_code_closure_verified=True,
            code_driver_and_source_stat_unchanged=True,private_raw_report_pass=True,
            source_identity_scope='same local file stat/dev/inode/size/mtime/ctime; not content immutability')
        result.update(raw_source_pts_microseconds=args.pts_us,raw_matched_frame_count=3,qsv_mapped_frames=raw['qsv_mapped_frames'])
    except BaseException as error:
        result.update(pass_=False,error_type=type(error).__name__,failure_stage=stage)
        if str(error) in SAFE_FAILURE_CODES:result['failure_code']=SAFE_FAILURE_CODES[str(error)]
    finally:
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        try:stop_owned_child(child)
        except BaseException:result.update(pass_=False,child_cleanup_failed=True)
        if child is not None:result['probe_exit_code']=child.returncode
        try:
            result['resources']=resources();r=result['resources']
            if not 0<r['peak_memory_bytes']<=r['memory_limit_bytes'] or any(r['memory_events'].values()) or r['swap_current_bytes'] or r['swap_peak_bytes']:result['pass_']=False
        except BaseException:result.update(pass_=False,resource_evidence_missing=True)
        result['elapsed_seconds']=time.monotonic()-started
        result['pass']=result.pop('pass_')
        print(json.dumps(result))
    return 0 if result['pass'] else 1


if __name__=='__main__':raise SystemExit(main())
