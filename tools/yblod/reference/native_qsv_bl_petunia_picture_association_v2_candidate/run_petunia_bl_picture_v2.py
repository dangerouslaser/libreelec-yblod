"""Scoped target BL picture-association v2 controller; never changes Kodi."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import shutil
import secrets
import stat
from capture_scene import rpc, process_identity
from collect_el_qsv_target_identity import source_stat
from observe_live_el_qsv_probe_1536 import code_fingerprint
from observe_picture_transport_qsv_bl_probe import validate_raw
from run_target_el_qsv_probe import idle_movie_source
from collect_el_qsv_target_manifest import observe_target
from target_el_qsv_live_handshake import process_record

PIN_NAMES = {'observe_picture_transport_qsv_bl_probe.py','observe_live_el_qsv_probe_1536.py','collect_el_qsv_target_identity.py',
             'target_el_qsv_live_handshake.py','run_target_el_qsv_probe.py','capture_scene.py',
             'collect_el_qsv_target_manifest.py'}
PROBE_SHA='da9791a63a48638be26098c85f728cfae31f3e6f5ea07618671365354b718367'
OBSERVER_SHA='2b2f58cde3a4cba251c693debe54d30c20a05e4c4d62135887f53ae89b787186'
PTS=(1210000000,1220010000,1230020000)


def host_reserves(launch=False):
    available=next(int(row.split()[1])*1024 for row in Path('/proc/meminfo').read_text().splitlines() if row.startswith('MemAvailable:'))
    if available < (2415919104 if launch else 805306368):
        raise ValueError('Target host memory reserve')
    return available


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
    fields=('MainPID','ActiveState','SubState','InvocationID','ControlGroup','Result','ExecMainStatus')
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
    if invocation is None or generation is None:
        raise ValueError('Never adopt an unacknowledged live unit during cleanup')
    if int(state.get('MainPID','0'))==0 and state.get('SubState')=='exited':
        if state.get('InvocationID')!=invocation:
            raise ValueError('Exited unit invocation changed')
    else:
        own_live_unit(state,args.expected_observer_argv,invocation,generation)
    subprocess.run(['systemctl','stop',args.unit],stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL,timeout=15,check=True)
    final=unit_state(args.unit)
    if final.get('ActiveState') not in ('inactive','failed') or int(final.get('MainPID','0'))!=0:
        raise ValueError('Scoped unit not terminal after cleanup')
    return True


def admission(args,state):
    path=args.launch_ready
    if not path.exists():return None
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600:
            raise ValueError('Private regular launch checkpoint required')
        value=json.load(stream)
    if set(value)!={'pid','start_ticks','nonce'} or value['nonce']!=args.launch_nonce or type(value['pid']) is not int or type(value['start_ticks']) is not int or value['pid']!=int(state.get('MainPID','0')):
        raise ValueError('Exact launched nonce and unit PID required')
    invocation,generation=own_live_unit(state,args.expected_observer_argv,None,(value['pid'],value['start_ticks']))
    return invocation,generation


def literal_raw_pass(raw):
    validate_raw(raw,list(PTS))
    if raw['controlled_packet_window']['event_count'] != 725:
        raise ValueError('Exact approved 725-AU window required')
    return True


def command(args, source):
    return ['systemd-run', '--wait', '--pipe', '--unit=' + args.unit,
        '-p', 'MemoryMax=1610612736', '-p', 'MemorySwapMax=0', '-p', 'CPUQuota=100%',
        '-p', 'PrivateNetwork=yes', '-p', 'RuntimeMaxSec=180', '-p', 'TimeoutStopSec=10',
        '-p', 'KillMode=control-group', '-p', 'UMask=0077', '-p', 'RemainAfterExit=yes',
        sys.executable,str(args.barrier),args.launch_nonce,str(args.launch_ready),str(args.launch_ack),
        str(args.observer), '--binary', str(args.binary),
        '--binary-sha256', args.binary_sha256, '--loader', str(args.loader),
        '--runtime', str(args.runtime), '--driver', str(args.driver),
        '--driver-sha256', args.driver_sha256, '--source', str(source),
        '--node', '/dev/dri/renderD128', '--runtime-identity', str(args.runtime_identity),
        '--private-prefix', str(args.private_prefix), '--seek-us', '1200000000',
        '--pts-us', '1210000000', '--pts-us', '1220010000', '--pts-us', '1230020000',
        '--extra-library-dir',str(args.vpl_runtime)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=('plan','run'),default='plan')
    for name in ('binary', 'loader', 'runtime', 'driver', 'runtime-identity',
                 'observer', 'private-prefix', 'target-identity', 'vpl-runtime','barrier'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('binary-sha256', 'driver-sha256', 'observer-sha256', 'manifest-sha256', 'target-identity-sha256', 'unit'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--source-pin',action='append',required=True)
    parser.add_argument('--controller-sha256',required=True)
    parser.add_argument('--barrier-sha256',required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if code_fingerprint(__file__)[1]!=args.controller_sha256 or args.binary_sha256!=PROBE_SHA or args.observer_sha256!=OBSERVER_SHA:
        raise ValueError('Exact reviewed controller and probe required')
    if not args.unit.startswith('yblod-bl-picture-v2-') or any(
            c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.unit):
        raise ValueError('Dedicated fresh unit required')
    status = subprocess.check_output(['systemctl', 'show', args.unit, '-p', 'LoadState', '--value'], text=True,timeout=5).strip()
    if status != 'not-found':
        raise ValueError('Fresh nonexistent scoped unit required')
    before_kodi = process_identity()
    pins=verify_source_pins(args.source_pin)
    if pins['observe_picture_transport_qsv_bl_probe.py']!=str(args.observer.resolve(strict=True)):
        raise ValueError('Observer must be exact pinned source')
    if code_fingerprint(args.target_identity)[1]!=args.target_identity_sha256:
        raise ValueError('Pre-recorded target identity code guard failed')
    expected_target=json.loads(args.target_identity.read_text())
    if set(expected_target)!={'host','gpu'} or observe_target('/dev/dri/renderD128')!=expected_target:
        raise ValueError('Independent target host/GPU identity differs')
    source = idle_movie_source()
    memory=host_reserves(launch=True)
    before_source = source_stat(source)
    for path, digest in ((args.binary,args.binary_sha256),(args.driver,args.driver_sha256),
                         (args.observer,args.observer_sha256),(args.runtime_identity,args.manifest_sha256)):
        if code_fingerprint(path)[1] != digest:
            raise ValueError('Reviewed code/manifest identity mismatch')
    output = Path(str(args.private_prefix) + '.observer-private.json')
    errors = Path(str(args.private_prefix) + '.controller-stderr-private.log')
    args.launch_nonce=secrets.token_hex(32)
    args.launch_ready=Path(str(args.private_prefix)+'.launch-ready-private.json')
    args.launch_ack=Path(str(args.private_prefix)+'.launch-ack-private')
    if code_fingerprint(args.barrier)[1]!=args.barrier_sha256:
        raise ValueError('Exact admission barrier source required')
    if not args.private_prefix.is_absolute() or any(parent.is_symlink() for parent in args.private_prefix.parents):
        raise ValueError('Absolute private prefix without symlink parents required')
    if any(path.exists() or path.is_symlink() for path in (output, errors,args.launch_ready,args.launch_ack)):
        raise ValueError('Fresh private controller files required')
    if shutil.disk_usage(args.private_prefix.parent).free < 33554432:
        raise ValueError('At least 32MiB target disk reserve required')
    if args.phase=='plan':
        print(json.dumps({'phase':'plan','pass':True,'host_available_memory_bytes':memory,
                          'decode_started':False,'raw_frame_writes':False,'memory_limit_bytes':1610612736}))
        return 0
    result = {'pass': False, 'scope': 'Target BL picture-association.v2 725-AU/three raw frames, not Kodi playback performance'}
    started = time.monotonic()
    process = None
    invocation=None;generation=None;launch_attempted=False
    def interrupted(*unused):
        raise RuntimeError('Scoped controller interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
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
                    if generation is None:
                        observed=admission(args,state)
                        if observed is not None:
                            invocation,generation=observed
                            # Recheck stable owned process and unit before releasing decode.
                            own_live_unit(unit_state(args.unit),args.expected_observer_argv,invocation,generation)
                            building=Path(str(args.launch_ack)+'.building')
                            fd=os.open(building,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                            with os.fdopen(fd,'wb') as ack:ack.write(args.launch_nonce.encode())
                            os.link(building,args.launch_ack)
                            building.unlink()
                    elif int(state.get('MainPID','0')):
                        own_live_unit(state,args.expected_observer_argv,invocation,generation)
                    elif state.get('SubState')=='exited':
                        break
                if time.monotonic() - started > 185:
                    raise TimeoutError('Scoped controller deadline')
                host_reserves()
                if shutil.disk_usage(args.private_prefix.parent).free < 33554432:
                    raise ValueError('Target disk reserve')
                if rpc('Player.GetActivePlayers') != [] or process_identity() != before_kodi:
                    raise ValueError('User playback or retained Kodi identity changed')
                time.sleep(.2 if generation is None else 2)
        terminal=unit_state(args.unit)
        if invocation is None or generation is None or terminal.get('InvocationID')!=invocation or terminal.get('MainPID')!='0' or terminal.get('SubState')!='exited' or terminal.get('Result')!='success' or terminal.get('ExecMainStatus')!='0':
            raise ValueError('Exact observed invocation/generation and successful terminal unit required')
        raw = json.loads(output.read_text())
        if raw.get('pass') is not True:
            raise ValueError('Strict observer/raw comparison failed')
        literal_raw_pass(json.loads(Path(str(args.private_prefix) + '.stdout-private.json').read_text()))
        verify_source_pins(args.source_pin)
        if (source_stat(source) != before_source or process_identity() != before_kodi or rpc('Player.GetActivePlayers') != []
                or observe_target('/dev/dri/renderD128')!=expected_target):
            raise ValueError('Post-run retained identity or idle proof failed')
        result.update(observer=raw, literal_three_frame_samples_equal=True, retained_kodi_identity_unchanged=True,
                      private_source_stat_unchanged=True,actual_launch_generation_verified=True,
                      terminal_unit_exit_code=0,terminal_unit_result='success')
        result['pass'] = True
    except Exception as error:
        result['error_type'] = type(error).__name__
    finally:
        for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):
            signal.signal(sig,signal.SIG_IGN)
        if launch_attempted:
            try:
                result['scoped_unit_terminal_verified']=cleanup_unit(args,invocation,generation)
                if process is not None and process.wait(timeout=5)!=0:result['pass']=False
            except Exception:
                result.update(scoped_cleanup_failed=True)
                result['pass'] = False
        try:
            if output.exists():
                observed=json.loads(output.read_text())
                if isinstance(observed.get('resources'),dict):result['observer_resource_report']=observed['resources']
                result['observer_terminal_diagnostic']={key:observed[key] for key in ('pass','failure_stage','error_type','probe_exit_code') if key in observed}
        except Exception:
            result['observer_resource_report_unavailable']=True
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
