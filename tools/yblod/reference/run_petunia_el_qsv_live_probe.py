"""Scoped target raw-EL controller; uses existing runtime/driver, never changes Kodi."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from capture_scene import rpc, process_identity
from collect_el_qsv_target_identity import source_stat
from observe_live_el_qsv_probe import code_fingerprint
from run_target_el_qsv_probe import idle_movie_source
from collect_el_qsv_target_manifest import observe_target
from target_el_qsv_live_handshake import process_record

PIN_NAMES = {'observe_live_el_qsv_probe.py','collect_el_qsv_target_identity.py',
             'target_el_qsv_live_handshake.py','run_target_el_qsv_probe.py','capture_scene.py',
             'collect_el_qsv_target_manifest.py','observe_subtitle_fixture.py'}


def verify_source_pins(values):
    pins = {}
    for value in values:
        path, digest = value.rsplit('=',1)
        path=Path(path).resolve(strict=True)
        if path.name in pins or code_fingerprint(path)[1] != digest:
            raise ValueError('Imported code identity mismatch')
        pins[path.name]=str(path)
    if set(pins)!=PIN_NAMES:
        raise ValueError('Complete exact imported source pins required')
    if len({str(Path(path).parent) for path in pins.values()}) != 1:
        raise ValueError('One explicit imported source directory required')
    for name,path in pins.items():
        module=sys.modules.get(name[:-3])
        if module is None or Path(module.__file__).resolve(strict=True)!=Path(path):
            raise ValueError('Actual imported source path differs from pin')
    return pins


def unit_state(unit):
    fields=('MainPID','ActiveState','SubState','InvocationID','ControlGroup','Result')
    text=subprocess.check_output(['systemctl','show',unit,*sum((['-p',key] for key in fields),[])],text=True,timeout=5)
    return dict(line.split('=',1) for line in text.splitlines() if '=' in line)


def own_live_unit(state, expected_argv, invocation=None, generation=None):
    if not state.get('InvocationID') or not state.get('ControlGroup'):
        raise ValueError('Actual scoped unit identity required')
    if invocation is not None and state['InvocationID']!=invocation:
        raise ValueError('Scoped unit invocation changed')
    pid=int(state.get('MainPID','0'))
    if pid:
        actual=process_record(pid)
        if actual['argv']!=expected_argv:
            raise ValueError('Unknown process owns scoped unit')
        if generation is not None and (pid,actual['start_ticks'])!=generation:
            raise ValueError('Scoped unit process generation changed')
        relative=Path('/proc')/str(pid)/'cgroup'
        if relative.read_text().split('0::',1)[1].strip()!=state['ControlGroup']:
            raise ValueError('Scoped unit cgroup mismatch')
        return state['InvocationID'],(pid,actual['start_ticks'])
    return state['InvocationID'],generation


def cleanup_unit(args, invocation, generation):
    state=unit_state(args.unit)
    if state.get('ActiveState') in ('inactive','failed') and int(state.get('MainPID','0'))==0:
        if invocation is not None and state.get('InvocationID') not in ('',invocation):
            raise ValueError('Terminal unit invocation changed')
        return True
    own_live_unit(state,args.expected_observer_argv,invocation,generation)
    subprocess.run(['systemctl','stop',args.unit],stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL,timeout=15,check=True)
    final=unit_state(args.unit)
    if final.get('ActiveState') not in ('inactive','failed') or int(final.get('MainPID','0'))!=0:
        raise ValueError('Scoped unit not terminal after cleanup')
    return True


def literal_raw_pass(raw):
    if raw.get('pass') is not True or type(raw.get('qsv_mapped_frames')) is not int or raw['qsv_mapped_frames'] < 3:
        raise ValueError('Actual raw comparison pass required')
    frames = raw.get('frames')
    if not isinstance(frames, list) or len(frames) != 3:
        raise ValueError('Three actual raw frames required')
    for frame, pts in zip(frames, (1210000000, 1220010000, 1230020000)):
        if (frame.get('format') != 'P010' or type(frame.get('code_bit_depth')) is not int or
                frame['code_bit_depth'] != 10 or frame.get('active_width') != 1920 or frame.get('active_height') != 1080):
            raise ValueError('Exact active P010 geometry required')
        if type(frame.get('requested_pts_microseconds')) is not int or frame['requested_pts_microseconds'] != pts:
            raise ValueError('Exact source timestamp required')
        if any(frame.get(key) is not True for key in ('properties_equal', 'active_geometry_equal',
                 'chroma_location_equal', 'colour_properties_equal', 'original_timestamps_equal')):
            raise ValueError('Exact frame properties required')
        for phase in ('before', 'after'):
            if type(frame.get(phase, {}).get('pts_microseconds')) is not int or frame[phase]['pts_microseconds'] != pts:
                raise ValueError('Exact returned timestamp required')
        planes = frame.get('planes')
        if not isinstance(planes, list) or len(planes) != 3:
            raise ValueError('Three raw plane records required')
        for plane, name, count in zip(planes, ('Y', 'U', 'V'), (2073600, 518400, 518400)):
            if plane.get('plane') != name or type(plane.get('sample_count')) is not int or plane['sample_count'] != count:
                raise ValueError('Literal active plane sample counts required')
            for key in ('differing_samples', 'maximum_absolute_sample_codes'):
                if type(plane.get(key)) is not int or plane[key] != 0:
                    raise ValueError('Literal raw sample equality required')
            if plane.get('p010_low_bits_zero') is not True:
                raise ValueError('P010 alignment required')
    return True


def command(args, source):
    return ['systemd-run', '--wait', '--pipe', '--unit=' + args.unit,
        '-p', 'MemoryMax=536870912', '-p', 'MemorySwapMax=0', '-p', 'CPUQuota=100%',
        '-p', 'PrivateNetwork=yes', '-p', 'RuntimeMaxSec=180', '-p', 'TimeoutStopSec=10',
        '-p', 'KillMode=control-group', '-p', 'UMask=0077',
        sys.executable, str(args.observer), '--binary', str(args.binary),
        '--binary-sha256', args.binary_sha256, '--loader', str(args.loader),
        '--runtime', str(args.runtime), '--driver', str(args.driver),
        '--driver-sha256', args.driver_sha256, '--source', str(source),
        '--node', '/dev/dri/renderD128', '--runtime-identity', str(args.runtime_identity),
        '--private-prefix', str(args.private_prefix), '--seek-us', '1200000000',
        '--pts-us', '1210000000', '--pts-us', '1220010000', '--pts-us', '1230020000',
        '--expected-code-root', str(args.runtime)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'loader', 'runtime', 'driver', 'runtime-identity',
                 'observer', 'private-prefix', 'target-identity'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('binary-sha256', 'driver-sha256', 'observer-sha256', 'manifest-sha256', 'target-identity-sha256', 'unit'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--source-pin',action='append',required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if not args.unit.startswith('yblod-qsv-target-live-') or any(
            c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.unit):
        raise ValueError('Dedicated fresh unit required')
    status = subprocess.check_output(['systemctl', 'show', args.unit, '-p', 'LoadState', '--value'], text=True,timeout=5).strip()
    if status != 'not-found':
        raise ValueError('Fresh nonexistent scoped unit required')
    before_kodi = process_identity()
    pins=verify_source_pins(args.source_pin)
    if pins['observe_live_el_qsv_probe.py']!=str(args.observer.resolve(strict=True)):
        raise ValueError('Observer must be exact pinned source')
    if code_fingerprint(args.target_identity)[1]!=args.target_identity_sha256:
        raise ValueError('Pre-recorded target identity code guard failed')
    expected_target=json.loads(args.target_identity.read_text())
    if set(expected_target)!={'host','gpu'} or observe_target('/dev/dri/renderD128')!=expected_target:
        raise ValueError('Independent target host/GPU identity differs')
    source = idle_movie_source()
    before_source = source_stat(source)
    for path, digest in ((args.binary,args.binary_sha256),(args.driver,args.driver_sha256),
                         (args.observer,args.observer_sha256),(args.runtime_identity,args.manifest_sha256)):
        if code_fingerprint(path)[1] != digest:
            raise ValueError('Reviewed code/manifest identity mismatch')
    output = Path(str(args.private_prefix) + '.observer-private.json')
    errors = Path(str(args.private_prefix) + '.controller-stderr-private.log')
    if not args.private_prefix.is_absolute() or any(parent.is_symlink() for parent in args.private_prefix.parents):
        raise ValueError('Absolute private prefix without symlink parents required')
    if any(path.exists() or path.is_symlink() for path in (output, errors)):
        raise ValueError('Fresh private controller files required')
    result = {'pass': False, 'scope': 'Target standalone EL raw comparison, not Kodi playback performance'}
    started = time.monotonic()
    process = None
    invocation=None;generation=None;launch_attempted=False
    def interrupted(*unused):
        raise RuntimeError('Scoped controller interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        argv=command(args,source)
        args.expected_observer_argv=argv[argv.index(sys.executable):]
        with output.open('x') as out, errors.open('x') as err:
            launch_attempted=True
            process = subprocess.Popen(argv, stdout=out, stderr=err,
                env={**os.environ,'PYTHONPATH':str(Path(args.observer).resolve(strict=True).parent)})
            while process.poll() is None:
                state=unit_state(args.unit)
                if state.get('InvocationID'):
                    invocation,generation=own_live_unit(state,args.expected_observer_argv,invocation,generation)
                if time.monotonic() - started > 185:
                    raise TimeoutError('Scoped controller deadline')
                if rpc('Player.GetActivePlayers') != [] or process_identity() != before_kodi:
                    raise ValueError('User playback or retained Kodi identity changed')
                time.sleep(5)
        raw = json.loads(output.read_text())
        if process.returncode != 0 or raw.get('pass') is not True:
            raise ValueError('Strict observer/raw comparison failed')
        literal_raw_pass(json.loads(Path(str(args.private_prefix) + '.stdout-private.json').read_text()))
        verify_source_pins(args.source_pin)
        if (source_stat(source) != before_source or process_identity() != before_kodi or rpc('Player.GetActivePlayers') != []
                or observe_target('/dev/dri/renderD128')!=expected_target):
            raise ValueError('Post-run retained identity or idle proof failed')
        result.update(observer=raw, literal_three_frame_samples_equal=True, retained_kodi_identity_unchanged=True,
                      private_source_stat_unchanged=True)
        result['pass'] = True
    except Exception as error:
        result['error_type'] = type(error).__name__
    finally:
        if launch_attempted:
            try:
                result['scoped_unit_terminal_verified']=cleanup_unit(args,invocation,generation)
                if process is not None:process.wait(timeout=5)
            except Exception:
                result.update(scoped_cleanup_failed=True)
                result['pass'] = False
        try:
            result['retained_state_after_cleanup_verified']=(process_identity()==before_kodi and rpc('Player.GetActivePlayers')==[])
        except Exception:
            result['retained_state_after_cleanup_verified']=False
        if not result['retained_state_after_cleanup_verified']:result['pass']=False
        result['elapsed_seconds'] = time.monotonic() - started
        print(json.dumps(result))
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
