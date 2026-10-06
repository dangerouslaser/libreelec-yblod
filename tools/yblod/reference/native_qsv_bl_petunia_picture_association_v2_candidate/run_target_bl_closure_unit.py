"""Review-gated CPU-only closure collector under an exact owned systemd unit."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import run_petunia_bl_picture_v2 as c

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--phase',choices=('plan','run'),default='plan')
    for n in ('binary','output','collector','barrier'):
        p.add_argument('--'+n,type=Path,required=True)
    for n in ('collector-sha256','barrier-sha256','controller-sha256'):
        p.add_argument('--'+n,required=True)
    p.add_argument('--source-pin',action='append',required=True)
    a=p.parse_args();os.umask(0o077)
    c.verify_source_pins(a.source_pin)
    for path,sha in ((a.binary,c.PROBE_SHA),(a.collector,a.collector_sha256),(a.barrier,a.barrier_sha256),(Path(c.__file__),a.controller_sha256)):
        assert c.code_fingerprint(path)[1]==sha
    assert a.output.is_absolute() and a.output.parent.resolve()==a.output.parent and not a.output.exists() and not a.output.is_symlink()
    c.host_reserves(True)
    retained=c.process_identity();assert c.rpc('Player.GetActivePlayers')==[]
    unit='yblod-bl-picture-v2-closure1'
    assert subprocess.run(['systemctl','show',unit,'-p','LoadState','--value'],capture_output=True,text=True,timeout=5,check=True).stdout.strip()=='not-found'
    if a.phase=='plan':
        print(json.dumps({'pass':True,'phase':'plan','collector_started':False}));return 0
    a.output.mkdir(mode=0o700)
    args=SimpleNamespace(unit=unit,launch_nonce=secrets.token_hex(32),launch_ready=a.output/'launch.ready',launch_ack=a.output/'launch.ack')
    argv=[sys.executable,str(a.barrier),args.launch_nonce,str(args.launch_ready),str(args.launch_ack),str(a.collector),'--binary',str(a.binary),'--output',str(a.output/'runtime-identity-private.json')]
    args.expected_observer_argv=argv
    command=['systemd-run','--quiet','--wait','--pipe','--unit='+unit,'-p','MemoryMax=536870912','-p','MemorySwapMax=0','-p','CPUQuota=100%',
             '-p','PrivateNetwork=yes','-p','PrivateDevices=yes','-p','RuntimeMaxSec=90','-p','TimeoutStopSec=10','-p','KillMode=control-group','-p','RemainAfterExit=yes','-p','UMask=0077']+argv
    invocation=generation=process=None
    result={'pass':False,'probe_executed':False,'kodi_executed':False}
    def interrupted(*unused):raise RuntimeError('Owned code-only closure interrupted')
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,interrupted)
    try:
        with (a.output/'collector-private.json').open('x') as out,(a.output/'collector-stderr-private.log').open('x') as err:
            process=subprocess.Popen(command,stdout=out,stderr=err)
            deadline=time.monotonic()+100
            while process.poll() is None:
                state=c.unit_state(unit)
                if state.get('InvocationID'):
                    if generation is None:
                        observed=c.admission(args,state)
                        if observed:
                            invocation,generation=observed
                            c.own_live_unit(c.unit_state(unit),argv,invocation,generation)
                            temporary=Path(str(args.launch_ack)+'.building')
                            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                            with os.fdopen(fd,'wb') as stream:stream.write(args.launch_nonce.encode())
                            os.link(temporary,args.launch_ack);temporary.unlink()
                    elif int(state.get('MainPID','0')):c.own_live_unit(state,argv,invocation,generation)
                    elif state.get('SubState')=='exited':break
                assert time.monotonic()<deadline
                c.host_reserves(False)
                assert c.rpc('Player.GetActivePlayers')==[] and c.process_identity()==retained
                time.sleep(.2 if generation is None else 1)
        state=c.unit_state(unit)
        assert invocation and generation and state.get('InvocationID')==invocation and state.get('MainPID')=='0' and state.get('ExecMainStatus')=='0' and state.get('Result')=='success'
        child=json.loads((a.output/'collector-private.json').read_text())
        assert child['pass'] is True
        result.update(child);result['launch_generation_verified']=True
    except BaseException as error:result.update(pass_=False,error_type=type(error).__name__)
    finally:
        for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,signal.SIG_IGN)
        try:
            result['terminal_confirmed']=c.cleanup_unit(args,invocation,generation)
            if process is not None and process.wait(timeout=5)!=0:result['pass']=False
        except BaseException:result.update(pass_=False,cleanup_uncertain=True)
        try:
            child=json.loads((a.output/'collector-private.json').read_text())
            if 'resources' in child:result['resources']=child['resources']
            result['retained_kodi_unchanged']=c.process_identity()==retained and c.rpc('Player.GetActivePlayers')==[]
            if not result['retained_kodi_unchanged']:result['pass']=False
        except BaseException:result['pass']=False
        if result.pop('pass_',None) is False:result['pass']=False
        with (a.output/'controller-private.json').open('x') as stream:json.dump(result,stream)
        print(json.dumps(result))
    return 0 if result['pass'] else 1

if __name__=='__main__':raise SystemExit(main())
