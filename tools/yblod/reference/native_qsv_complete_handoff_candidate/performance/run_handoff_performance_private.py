"""Owned same-candidate EL API ABBA; reversible runtime and subtitle fixture."""
import argparse
import re
import math
from contextlib import redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import signal
from unit_start_barrier3_private import await_admission

def positive_movie_id(value):
    try:parsed=int(value)
    except (TypeError,ValueError):raise argparse.ArgumentTypeError('Movie ID must be a positive integer')
    if parsed<=0:raise argparse.ArgumentTypeError('Movie ID must be a positive integer')
    return parsed


def positive_seek(value):
    try:parsed=float(value)
    except (TypeError,ValueError):raise argparse.ArgumentTypeError('Seek must be finite and positive')
    if not math.isfinite(parsed) or parsed<=0:raise argparse.ArgumentTypeError('Seek must be finite and positive')
    return parsed


parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--stage',type=Path,required=True)
parser.add_argument('--attempt-tag',required=True)
parser.add_argument('--retained-source',type=Path,required=True)
parser.add_argument('--retained-sha256',required=True)
parser.add_argument('--candidate-sha256',required=True)
parser.add_argument('--driver-sha256',required=True)
parser.add_argument('--qualification-report',type=Path,required=True)
parser.add_argument('--qualification-sha256',required=True)
parser.add_argument('--tool-pin',action='append',required=True)
parser.add_argument('--baseline-report',type=Path,required=True)
parser.add_argument('--baseline-identity',type=Path,required=True)
parser.add_argument('--original-override',type=Path,required=True)
parser.add_argument('--movie-id',type=positive_movie_id,required=True)
parser.add_argument('--expected-title',default='Saving Private Ryan')
parser.add_argument('--seek-seconds',type=positive_seek,default=1200.0)
args=parser.parse_args()
tool_pairs=[value.split('=',1) for value in args.tool_pin]
TOOL_PINS=dict(tool_pairs)
if len(tool_pairs)!=len(TOOL_PINS):parser.error('Duplicate tooling pin')
if not args.expected_title.strip():parser.error('Expected title must not be empty')
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,48}',args.attempt_tag):
    parser.error('Invalid fresh attempt tag')
for value in (args.retained_sha256,args.candidate_sha256,args.driver_sha256):
    if not re.fullmatch(r'[0-9a-f]{64}',value):parser.error('Invalid code digest')
ROOT=args.stage
OLD_SOURCE=args.retained_source
if not ROOT.is_absolute() or not OLD_SOURCE.is_absolute() or not str(ROOT).startswith('/storage/') or not str(OLD_SOURCE).startswith('/storage/') or not re.fullmatch(r'/[A-Za-z0-9/_-]+',str(ROOT)):
    parser.error('This reviewed template requires explicit /storage paths')
for path in (args.baseline_report,args.baseline_identity,args.original_override):
    if not path.is_absolute() or path.parent!=ROOT:parser.error('Private evidence must be directly in the isolated stage')
sys.path.insert(0,str(ROOT/'baseline-tools'))
import capture_scene as capture
from collect_el_qsv_target_identity import gpu_identity,source_stat
OLD=args.retained_sha256
NEW=args.candidate_sha256
DRIVER=args.driver_sha256
TARGET=Path('/usr/lib/kodi/kodi.bin')
COMBINED=Path('/storage/yblod-bl-el-handoff-runtime-20261006')
NEW_SOURCE=COMBINED/'kodi.bin'
LIBRARY_PATH=str(COMBINED/'lib')+':'+str(ROOT/'lib')
OLD_MOUNT_ROOT=str(OLD_SOURCE)[len('/storage'):]
NEW_MOUNT_ROOT=str(NEW_SOURCE)[len('/storage'):]
TAG=args.attempt_tag

PREFIXES = ('libavcodec.so.', 'libavutil.so.', 'libavfilter.so.', 'libavformat.so.',
            'libswscale.so.', 'libswresample.so.', 'libavdevice.so.', 'libpostproc.so.', 'libvpl.so.', 'libmfx-gen.so.')


def private_launcher_bytes(original, library_directory):
    marker=b'/usr/lib/kodi/kodi.bin $SAVED_ARGS'
    if original.count(marker)!=1:raise ValueError('launcher invocation contract')
    return original.replace(marker,('LD_LIBRARY_PATH='+str(library_directory)+':$LD_LIBRARY_PATH ').encode()+marker)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1048576),b''):digest.update(chunk)
    return digest.hexdigest()


def verify_tools():
    for path,digest in TOOL_PINS.items():
        if not re.fullmatch('[a-f0-9]{64}',digest) or Path(path).resolve()!=Path(path) or sha(path)!=digest:
            raise ValueError('Tooling source identity')
    for name,module in list(sys.modules.items()):
        value=getattr(module,'__file__',None)
        if value and name!='__main__':
            path=str(Path(value).resolve())
            if path.startswith(str(ROOT)+'/') and (path not in TOOL_PINS or sha(path)!=TOOL_PINS[path]):
                raise ValueError('Unexpected imported private tooling')


def mounts():
    return [line.split()[3] for line in Path('/proc/self/mountinfo').read_text().splitlines()
            if line.split()[4] == str(TARGET)]


def observe():
    return dict(host=hashlib.sha256(Path('/etc/machine-id').read_bytes()).hexdigest(),
                gpu=gpu_identity('/dev/dri/renderD128'))


def mapped_family(pid):
    result = {}
    for line in (Path('/proc')/str(pid)/'maps').read_text().splitlines():
        fields = line.split(None,5)
        if len(fields)!=6 or not fields[5].startswith('/'):
            continue
        path = Path(fields[5])
        if any(path.name.startswith(prefix) for prefix in PREFIXES):
            result[str(path)] = sha(path)
    return result


def resources():
    relative = Path('/proc/self/cgroup').read_text().split('0::',1)[1].strip()
    base = Path('/sys/fs/cgroup')/relative.lstrip('/')
    values = {key:(base/key).read_text().strip() for key in
        ('memory.max','memory.swap.max','cpu.max','memory.peak','memory.events','memory.swap.current','memory.swap.peak')}
    q,p = values['cpu.max'].split()
    return dict(memory_limit_bytes=int(values['memory.max']),swap_limit_bytes=int(values['memory.swap.max']),
        cpu_limit=int(q)/int(p),peak_memory_bytes=int(values['memory.peak']),
        memory_events={key:int(value) for key,value in (row.split() for row in values['memory.events'].splitlines())},
        swap_current_bytes=int(values['memory.swap.current']),swap_peak_bytes=int(values['memory.swap.peak']))


def restore_owned(prior_mounts, original, override, old_maps, bound_new, removed_old, stop_attempted):
    """Only remove our verified top; unknown ownership is never guessed."""
    pid = int(capture.command('systemctl','show','kodi','-p','MainPID','--value').strip())
    if pid:
        identity = capture.process_identity()
        expected = NEW if bound_new else OLD
        if identity['binary_sha256'] != expected or (removed_old and not bound_new):
            raise RuntimeError('unknown process ownership')
        if bound_new:
            for player in capture.rpc('Player.GetActivePlayers'):
                if player['type']=='video':
                    item=capture.rpc('Player.GetItem',{'playerid':player['playerid']})['item']
                    if (item.get('id'),item.get('type'))!=(args.movie_id,'movie'):
                        raise RuntimeError('Playback ownership changed; refusing rollback stop')
                    capture.rpc('Player.Stop',{'playerid':player['playerid']})
            capture.command('systemctl','stop','kodi')
            if capture.command('systemctl','show','kodi','-p','MainPID','--value').strip()!='0':
                raise RuntimeError('owned process still alive')
    if bound_new:
        if len(mounts())!=len(prior_mounts) or mounts()[-1]!=NEW_MOUNT_ROOT or sha(TARGET)!=NEW:
            raise RuntimeError('unexpected owned top')
        capture.command('umount',str(TARGET))
    if removed_old:
        if mounts()!=prior_mounts[:-1]:raise RuntimeError('unexpected lower layers')
        capture.command('mount','--bind',str(OLD_SOURCE),str(TARGET))
    if mounts()!=prior_mounts or sha(TARGET)!=OLD:raise RuntimeError('original mount not restored')
    override.write_bytes(original)
    capture.command('systemctl','daemon-reload')
    if stop_attempted and not int(capture.command('systemctl','show','kodi','-p','MainPID','--value').strip()):
        capture.command('systemctl','start','kodi')
    for _ in range(30):
        try:
            if capture.rpc('Player.GetActivePlayers')==[]:
                identity=capture.process_identity()
                if identity['binary_sha256']==OLD and mapped_family(identity['pid'])==old_maps:
                    return dict(original_top_source_and_layer_count_restored=True,
                        original_override_restored=override.read_bytes()==original,
                        retained_binary_restored=True,original_runtime_maps_restored=True,restored_idle=True)
        except (OSError,RuntimeError):pass
        time.sleep(1)
    raise RuntimeError('restored runtime not verified')


def main():
    os.umask(0o077)
    original = args.original_override.read_bytes()
    override = Path('/run/systemd/system/kodi.service.d/yblod-native-playback.conf')
    result = dict(pass_=False, comparison='BL_QSV_ABBA_EL_QSV1_batch0')
    started = time.monotonic()
    removed_old = False
    bound_new = False
    ready = False
    stopped = False
    def interrupted(*args):raise RuntimeError('scoped interruption')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGALRM, interrupted)
    signal.alarm(1100)
    try:
        limits = resources()
        if limits['memory_limit_bytes']!=536870912 or limits['swap_limit_bytes']!=0 or not 0<limits['cpu_limit']<=1:
            raise ValueError('limits')
        await_admission()
        verify_tools()
        if capture.rpc('Player.GetActivePlayers')!=[] or capture.process_identity()['binary_sha256']!=OLD or override.read_bytes()!=original:
            raise ValueError('precondition')
        old_maps = mapped_family(capture.process_identity()['pid'])
        if any(not path.startswith('/usr/lib/') for path in old_maps):raise ValueError('old runtime')
        prior_mounts = mounts()
        if not prior_mounts or prior_mounts[-1]!=OLD_MOUNT_ROOT or sha(OLD_SOURCE)!=OLD or sha(TARGET)!=OLD or sha(NEW_SOURCE)!=NEW:
            raise ValueError('mount identity')
        if sha('/usr/lib/dri/iHD_drv_video.so')!=DRIVER:raise ValueError('driver')
        # Logs and scalar reports only; never write raw capture buffers.
        diagnostic_budget=8*1024*1024
        result['diagnostic_storage_budget_bytes']=diagnostic_budget
        if os.statvfs(ROOT).f_bavail*os.statvfs(ROOT).f_frsize<diagnostic_budget:raise ValueError('space')
        baseline_report=json.loads(args.baseline_report.read_text())
        if baseline_report.get('movie')!={'id':args.movie_id,'title':args.expected_title,'seek_seconds':args.seek_seconds} or len(baseline_report.get('frames',[]))!=3:
            raise ValueError('baseline movie identity')
        movie=capture.rpc('VideoLibrary.GetMovieDetails',{'movieid':args.movie_id,'properties':['title','file']})['moviedetails']
        if movie['title']!=args.expected_title:raise ValueError('movie')
        source=movie['file'];source_before=source_stat(source);target_before=observe()
        previous_evidence=json.loads(args.baseline_identity.read_text())
        if target_before!=previous_evidence['before'] or tuple(previous_evidence['source_stat_before'])!=source_before:raise ValueError('baseline identity')
        report_path=ROOT/(TAG+'-capture-private.json')
        config=ROOT/(TAG+'-capture-private.conf')
        if report_path.exists() or config.exists():raise ValueError('fresh')
        controlled=(ROOT/'baseline-tools/capture-el-qsv-planar1-flag0.conf').read_text()
        if controlled.count('Environment=DVBRIDGE_FEL_QSV=0')!=1:raise ValueError('QSV flag contract')
        if controlled.count('Environment=DVBRIDGE_CAPTURE_OUTPUTS=1')!=1:raise ValueError('capture flag contract')
        controlled=controlled.replace('Environment=DVBRIDGE_CAPTURE_OUTPUTS=1','Environment=DVBRIDGE_CAPTURE_OUTPUTS=0')
        controlled=controlled.replace('Environment=DVBRIDGE_FEL_QSV=0','Environment=DVBRIDGE_FEL_QSV=1')
        controlled+='Environment=DVBRIDGE_BASE_QSV=0\n'
        controlled+='Environment=LD_LIBRARY_PATH='+LIBRARY_PATH+'\nEnvironment=ONEVPL_PRIORITY_PATH='+str(ROOT/'lib')+'\n'
        original_launcher=Path('/usr/lib/kodi/kodi.sh')
        launcher=ROOT/(TAG+'-launcher-private.sh')
        expected_start='ExecStart=/usr/lib/kodi/kodi.sh --standalone -fs $KODI_AUDIO_ARGS $KODI_ARGS $KODI_DEBUG'
        starts=[line for line in Path('/usr/lib/systemd/system/kodi.service').read_text().splitlines() if line.startswith('ExecStart=')]
        if starts!=[expected_start] or b'ExecStart=' in original:raise ValueError('original start contract')
        marker=b'/usr/lib/kodi/kodi.bin $SAVED_ARGS'
        launcher_bytes=original_launcher.read_bytes()
        if launcher.exists() or launcher_bytes.count(marker)!=1:raise ValueError('launcher source')
        patched_launcher=private_launcher_bytes(launcher_bytes,LIBRARY_PATH)
        with launcher.open('xb') as stream:stream.write(patched_launcher)
        launcher.chmod(original_launcher.stat().st_mode & 0o777)
        result['original_launcher_sha256']=sha(original_launcher)
        result['private_launcher_sha256']=sha(launcher)
        result['launcher_only_invocation_environment_changed']=True
        controlled+='ExecStart=\nExecStart='+str(launcher)+' --standalone -fs $KODI_AUDIO_ARGS $KODI_ARGS $KODI_DEBUG\n'
        config.write_text(controlled)
        ready=True
        stopped=True
        capture.command('systemctl','stop','kodi')
        if capture.command('systemctl','show','kodi','-p','MainPID','--value').strip()!='0':raise ValueError('stop')
        capture.command('umount',str(TARGET));removed_old=True
        if mounts()!=prior_mounts[:-1]:raise ValueError('unexpected lower mount')
        capture.command('mount','--bind',str(NEW_SOURCE),str(TARGET));bound_new=True
        if len(mounts())!=len(prior_mounts) or mounts()[-1]!=NEW_MOUNT_ROOT or sha(TARGET)!=NEW:raise ValueError('candidate bind')
        from types import SimpleNamespace
        sys.path.insert(0,str(ROOT/'handoff-perf-tools'))
        import run_handoff_matrix as matrix
        from run_colour_import_matrix import run_configured_matrix
        verify_tools()
        configs=ROOT/(TAG+'-configs-private');configs.mkdir(mode=0o700)
        reports=ROOT/(TAG+'-reports-private');reports.mkdir(mode=0o700)
        for flag in (0,1):
            text=controlled.replace('Environment=DVBRIDGE_BASE_QSV=0','Environment=DVBRIDGE_BASE_QSV='+str(flag))
            (configs/('native-el-qsv-planar1-flag'+str(flag)+'.conf')).write_text(text)
        request=SimpleNamespace(binary_sha256=NEW,root=reports,
            observer=ROOT/'handoff-perf-tools/observe_el_qsv_active_movie.py',config_dir=configs,
            movie_id=args.movie_id,expected_title=args.expected_title,seek_seconds=int(args.seek_seconds),
            seconds=90,startup_settle_seconds=20,subtitles_off=True,planar_flag=1,
            qualification_report=args.qualification_report,qualification_sha256=args.qualification_sha256)
        proof=matrix.validate_args(request)
        import run_colour_import_matrix as lifecycle
        from run_el_qsv_observer_owned import ObserverSubprocess
        from observe_el_qsv_active_movie import verify_measured_generation
        lifecycle.subprocess=ObserverSubprocess(ROOT/'handoff-performance-runtime-manifest-private.json',args.movie_id)
        validate=matrix.make_validator(1)
        manifest=json.loads((ROOT/'handoff-performance-runtime-manifest-private.json').read_text())
        def runtime_validator(report,stopped,enabled,binary_hash):
            snapshot=verify_measured_generation(report,NEW)
            loaded=snapshot.get('mapped_families',{})
            if not isinstance(loaded,dict) or not loaded:raise ValueError('Empty active runtime evidence')
            for path,digest in loaded.items():
                item=Path(path)
                if item.name not in manifest['artifacts'] or str(item)!=manifest['artifacts'][item.name]['runtime_path'] or digest!=manifest['artifacts'][item.name]['sha256']:
                    raise ValueError('candidate actual runtime')
            prefixes=('libavcodec.so.','libavutil.so.','libavformat.so.','libavfilter.so.','libswscale.so.','libswresample.so.','libvpl.so.')
            prefixes+=('libmfx-gen.so.','libpostproc.so.')
            if any(not any(Path(path).name.startswith(prefix) for path in loaded) for prefix in prefixes):
                raise ValueError('missing actual new family')
            verify_tools()
            value=validate(report,stopped,enabled,binary_hash)
            value['actual_isolated_runtime_verified']=True
            return value
        with (ROOT/(TAG+'-matrix-private.log')).open('x') as log,redirect_stdout(log):
            run_configured_matrix(request,matrix.config_paths(request),'el-qsv-canonical-planar1',
                lambda flag:'BL_QSV='+str(flag)+' EL_QSV=1 async_depth=1 planar=1 other_optimizations=0',
                runtime_validator)
        if target_before!=observe() or source_before!=source_stat(source) or sha('/usr/lib/dri/iHD_drv_video.so')!=DRIVER:
            raise ValueError('after identity')
        result.update(matrix_passed=True,cases=4,requested_seconds_each=90,
            actual_candidate_runtime_verified_each_case=True,source_stat_unchanged=True,
            qualification_method=proof['method'],capture_outputs=False,batched_planes=0,immutable_instructions=0)
        verify_tools()
        result['pass_']=True
    except BaseException as error:
        result['matrix_error']=True
        result['matrix_error_type']=type(error).__name__
    finally:
        signal.alarm(0)
        # Reserve rollback after the bounded 1100-second matrix work deadline.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            if ready:result.update(restore_owned(prior_mounts,original,override,old_maps,bound_new,removed_old,stopped))
            if 'original_launcher_sha256' in result:
                result['original_launcher_unchanged']=sha('/usr/lib/kodi/kodi.sh')==result['original_launcher_sha256']
                if not result['original_launcher_unchanged']:result['pass_']=False
        except BaseException:
            result.update(pass_=False,rollback_error=True,rollback_uncertain=True)
        try:
            result['resources']=resources();r=result['resources']
            if not 0<r['peak_memory_bytes']<=r['memory_limit_bytes'] or any(r['memory_events'].values()) or r['swap_current_bytes'] or r['swap_peak_bytes']:result['pass_']=False
        except BaseException:result.update(pass_=False,resource_evidence_missing=True)
        result['elapsed_seconds']=time.monotonic()-started;result['pass']=result.pop('pass_')
        result['scope']='Matched four-case same-candidate BL VAAPI versus QSV playback with EL QSV fixed. Whole Kodi CPU, GPU clients, RAM and health are observer measurements. Controller cgroup peak is not Kodi RAM. No whole-film or display conformance claim.'
        print(json.dumps(result))
    return 0 if result['pass'] else 1


if __name__=='__main__':raise SystemExit(main())
