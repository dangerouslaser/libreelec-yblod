"""CPU-only direct SDK loader argv shape fixture; no GPU or media access."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from observe_live_el_qsv_probe import resources,code_fingerprint,stop_owned_child
from target_el_qsv_live_handshake import process_record

SDK=Path('/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain')
loader=(SDK/'x86_64-libreelec-linux-gnu/sysroot/usr/lib/ld-linux-x86-64.so.2').resolve(strict=True)
library=str(SDK/'x86_64-libreelec-linux-gnu/sysroot/usr/lib')+':'+str(SDK/'x86_64-libreelec-linux-gnu/lib')
command=[str(loader),'--library-path',library,'/usr/bin/sleep','2']
child=None;result={'pass':False};started=time.monotonic()
def interrupted(*unused):raise TimeoutError('CPU fixture deadline')
signal.signal(signal.SIGALRM,interrupted);signal.alarm(10)
try:
    limits=resources()
    if limits['memory_limit_bytes']!=536870912 or limits['swap_limit_bytes']!=0 or not 0<limits['cpu_limit']<=1:raise ValueError('Limits')
    before=code_fingerprint(loader)
    child=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    time.sleep(.2)
    observed=process_record(child.pid)
    time.sleep(.1)
    if process_record(child.pid)!=observed:raise ValueError('Fixture child identity changed')
    result.update(actual_executable_is_direct_sdk_loader=observed['executable']==str(loader),
        actual_parent_is_fixture=observed['ppid']==os.getpid(),
        argv_matches_full_loader_command=observed['argv']==command,
        argv_matches_exact_binary_tail=observed['argv']==command[3:])
    result['argv_shape']='full_loader_command' if result['argv_matches_full_loader_command'] else 'exact_binary_tail' if result['argv_matches_exact_binary_tail'] else 'other'
    child.wait(timeout=4)
    result.update(child_exit_code=child.returncode,loader_code_identity_unchanged=before==code_fingerprint(loader))
    result['pass']=child.returncode==0 and result['actual_executable_is_direct_sdk_loader'] and result['actual_parent_is_fixture'] and result['loader_code_identity_unchanged']
except BaseException as error:result.update({'pass':False,'error_type':type(error).__name__})
finally:
    signal.alarm(0)
    try:stop_owned_child(child)
    except BaseException:result.update({'pass':False,'cleanup_failed':True})
    result['resources']=resources();r=result['resources']
    if not 0<r['peak_memory_bytes']<=r['memory_limit_bytes'] or any(r['memory_events'].values()) or r['swap_current_bytes'] or r['swap_peak_bytes']:result['pass']=False
    result['elapsed_seconds']=time.monotonic()-started
    print(json.dumps(result))
raise SystemExit(0 if result['pass'] else 1)
