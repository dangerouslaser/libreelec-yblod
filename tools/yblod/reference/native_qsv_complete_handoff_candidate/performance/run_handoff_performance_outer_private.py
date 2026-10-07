"""Launch one fresh bounded code-only loader unit; preserve private diagnostics."""
import hashlib
import json
from pathlib import Path
import subprocess
import signal
import os
import secrets
import stat
import argparse
import time

ROOT=Path('/storage/yblod-qsv-el-aff416-runtime')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mode',choices=('loader','capture','capture-qsv1','metadata','performance'),default='loader')
parser.add_argument('--tool-manifest-sha256')
options=parser.parse_args();MODE=options.mode
if MODE!='performance':parser.error('This launcher accepts the short handoff performance comparison only')
CODE_ONLY=MODE in ('loader','metadata')
ON=MODE=='capture-qsv1'
SCRIPT=ROOT/('check-header-target-loader3-private.py' if MODE=='loader' else 'capture-header-qsv-on1-private.py' if ON else 'capture-header-qsv-off3-private.py')
UNIT='yblod-qsv-header-9615-'+('loader3' if MODE=='loader' else 'on-capture1' if ON else 'off-capture3')
PREFIX='candidate-9615-'+('loader3' if MODE=='loader' else 'on1' if ON else 'off3')
EXPECTED_SHA='25b06603363679532af866aa055de86b4c9a370973d4f4f5934d5744de78ccf5' if MODE=='loader' else '64204d54d2100aba6a1b52c01017ff0da8bdf9ed7349b34c0f31663c7dedc650' if ON else '4399c9890289265ddbdddc31cfae433a7ad27664d8f84f32958876b1d642425f'
HELPER_SHA='651932bfe2eb990a9b7f6d7db3946b76bad3d168a110e48094129624d29fcf79'
if MODE=='metadata':
    SCRIPT=ROOT/'run-target-fel-metadata-inspector-private.py'
    UNIT='yblod-qsv-header-9615-fel-metadata1'
    PREFIX='candidate-9615-fel-metadata1'
    EXPECTED_SHA='8df88047edff3d7a826b77d463180ab85e20fd2775e2274c79071d0d1fb1ad8e'
if MODE=='performance':
    SCRIPT=ROOT/'run_handoff_performance_private.py'
    UNIT='yblod-bl-el-handoff-performance1'
    PREFIX='candidate-handoff-performance1'
    EXPECTED_SHA='58e13c89f9a198971be955724a08e69a6bf7d2e346fa7aa90ec5a0217310697d'
ARGV=['/usr/bin/python3',str(SCRIPT)]
if not CODE_ONLY:ARGV += ['--stage',str(ROOT),'--attempt-tag','candidate-handoff-performance1' if MODE=='performance' else 'candidate-9615-qsv-on1' if ON else 'candidate-9615-qsv-off3',
    '--retained-source','/storage/yblod-renderer-step1-20261006/kodi-native-scheduling.bin',
    '--retained-sha256','19379de491c0f53d835424edeae20191869854a5eeeacfcf5cc8a9c81b9ee9aa',
    '--candidate-sha256','db2ada4e0646f845c3bfa2dd96fab3f73dbc161fdfc0944691084753e30f104b',
    '--driver-sha256','fca0ac8e50a27e9278b8ad17b488dd662af34eb5cd48fe3670e7d7971b3d7d7f',
    '--baseline-report',str(ROOT/'retained-19379-qsv-off-spr-private.json'),
    '--baseline-identity',str(ROOT/'retained-19379-target-identity-private.json'),
    '--original-override',str(ROOT/'retained-19379-original-override-private.conf'),
    '--movie-id','3391','--expected-title','Saving Private Ryan','--seek-seconds','1200']
if MODE=='performance':
    if not options.tool_manifest_sha256 or len(options.tool_manifest_sha256)!=64:parser.error('Exact tooling manifest digest required')
    manifest=ROOT/'handoff-performance-tool-pins-private.json'
    assert hashlib.sha256(manifest.read_bytes()).hexdigest()==options.tool_manifest_sha256
    pins=json.loads(manifest.read_text())
    assert isinstance(pins,dict) and pins
    ARGV += ['--qualification-report',str(ROOT/'canonical-qualification-private/qualification2-private.json'),
        '--qualification-sha256','aad6cfcce9a57de3af5adc607a1ef163a2829ef078ba6e3ea440f23ad2ee8950']
    for path,digest in sorted(pins.items()):ARGV += ['--tool-pin',path+'='+digest]
def show():
    p=subprocess.run(['systemctl','show',UNIT,'-p','LoadState','-p','InvocationID','-p','MainPID','-p','ActiveState','-p','SubState','-p','ExecMainStatus','-p','Result'],capture_output=True,text=True,timeout=5)
    return dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)

result={'pass':False};owned=None;generation=None;p=None
os.umask(0o077)
nonce=secrets.token_hex(32);ready=ROOT/(PREFIX+'-ready-private.json');ack=ROOT/(PREFIX+'-ack-private')
def interrupted(*args):raise RuntimeError('scoped interruption')
for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,interrupted)
def process_generation(pid):
    base=Path('/proc')/str(pid)
    argv=base.joinpath('cmdline').read_bytes().rstrip(b'\0').split(b'\0')
    assert argv==[a.encode() for a in ARGV]
    stat=base.joinpath('stat').read_text().rsplit(')',1)[1].split()
    return (pid,int(stat[19]),base.joinpath('cgroup').read_text())
def ready_generation(pid):
    if not ready.exists():return None
    result['qualification_stage']='complete_ready_file'
    fd=os.open(ready,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode) and stat.S_IMODE(s.st_mode)==0o600
        value=json.load(f)
    assert value=={'pid':pid,'nonce':nonce} and type(value['pid']) is int
    result['qualification_stage']='post_ready_process_generation'
    return process_generation(pid)
try:
    result['qualification_stage']='source_admission'
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest()==EXPECTED_SHA
    assert hashlib.sha256((ROOT/'unit_start_barrier3_private.py').read_bytes()).hexdigest()==HELPER_SHA
    assert show().get('LoadState')=='not-found'
    assert not any(path.exists() or path.is_symlink() for path in (ready,ack))
    out=ROOT/(PREFIX+'-private.json');err=ROOT/(PREFIX+'-unit-private.log')
    with out.open('xb') as stdout,err.open('xb') as stderr:
        command=['systemd-run','--quiet','--unit='+UNIT,'--wait','--pipe',
            '-p','MemoryMax=536870912','-p','MemorySwapMax=0','-p','CPUQuota=100%',
            '-p','RuntimeMaxSec='+('1250' if MODE=='performance' else '90' if CODE_ONLY else '330'),'-p','TimeoutStopSec='+('120' if MODE=='performance' else '5' if CODE_ONLY else '30'),
            '-p','KillMode=control-group','-p','RemainAfterExit=yes',
            '--setenv=YB_UNIT_READY='+str(ready),'--setenv=YB_UNIT_ACK='+str(ack),
            '--setenv=YB_UNIT_NONCE='+nonce]
        if CODE_ONLY:command+=['-p','PrivateNetwork=yes']
        p=subprocess.Popen(command+ARGV,stdout=stdout,stderr=stderr)
        deadline=time.monotonic()+(1400 if MODE=='performance' else 100 if CODE_ONLY else 390)
        while p.poll() is None:
            state=show()
            if state.get('InvocationID'):
                if owned is None:owned=state['InvocationID']
                result['qualification_stage']='unit_invocation'
                assert state['InvocationID']==owned
                pid=int(state.get('MainPID','0'))
                if pid:
                    current=ready_generation(pid)
                    if current is not None:
                        if generation is None:generation=current
                        assert generation==current
                    if current is not None and not ack.exists():
                        result['qualification_stage']='stable_generation_before_ack'
                        assert process_generation(pid)==generation and show()['InvocationID']==owned
                        fd=os.open(ack,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                        with os.fdopen(fd,'wb') as f:f.write(nonce.encode())
                if generation and state.get('MainPID')=='0' and state.get('SubState')=='exited':break
            if time.monotonic()>deadline:raise TimeoutError('owned loader deadline')
            time.sleep(.2)
    child=json.loads(out.read_text());assert child.get('pass') is True
    terminal=show();assert generation and terminal.get('MainPID')=='0' and terminal.get('ExecMainStatus')=='0' and terminal.get('Result')=='success' and terminal.get('InvocationID')==owned
    assert ack.exists()
    proof=ROOT/(PREFIX+'-unit-identity-private.json')
    with proof.open('x') as stream:json.dump({'invocation':owned,'pid':generation[0],'start_ticks':generation[1],'cgroup':generation[2]},stream)
    subprocess.run(['systemctl','stop',UNIT],check=True,timeout=130 if MODE=='performance' else 10 if CODE_ONLY else 40)
    assert p.wait(timeout=10)==0
    result.update(pass_=True,owned_unit_terminal=True,mode=MODE,child_pass=True)
except BaseException as e:result.update(pass_=False,error_type=type(e).__name__)
finally:
    try:
        state=show()
        if state.get('MainPID','0')!='0' or state.get('ActiveState')=='active':
            if not owned or state.get('InvocationID')!=owned:raise RuntimeError('unit ownership unknown')
            if state.get('MainPID','0')!='0' and (generation is None or process_generation(int(state['MainPID']))!=generation):raise RuntimeError('process ownership unknown')
            subprocess.run(['systemctl','stop',UNIT],check=True,timeout=130 if MODE=='performance' else 10 if CODE_ONLY else 40)
        if p is not None and p.poll() is None:p.wait(timeout=10)
        terminal=show();result['cleanup_terminal']=terminal.get('MainPID')=='0' and terminal.get('ActiveState') in ('inactive','failed')
        if not result['cleanup_terminal']:result['pass_']=False
    except BaseException:result.update(pass_=False,cleanup_uncertain=True)
    result['pass']=result.pop('pass_',False);print(json.dumps(result))
raise SystemExit(0 if result['pass'] else 1)
