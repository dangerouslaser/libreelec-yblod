"""Scoped observer child: terminate gracefully, then restore recorded subtitles."""
import os
from pathlib import Path
import subprocess
import time
import capture_scene
from el_qsv_observer_fixture import recover


def run_observer(argv,*,stdout,stderr,check,timeout,manifest,movie_id):
    report_root=Path(argv[argv.index('--output-dir')+1])
    label=argv[argv.index('--label')+1]
    recovery=report_root/(label+'.subtitle-recovery-private.json')
    env=dict(os.environ,YB_EL_SUBTITLE_RECOVERY=str(recovery),YB_EL_RUNTIME_MANIFEST=str(manifest))
    child=subprocess.Popen(argv,stdout=stdout,stderr=stderr,env=env)
    status=None
    try:
        status=child.wait(timeout=timeout)
        if check and status:raise subprocess.CalledProcessError(status,argv)
        return subprocess.CompletedProcess(argv,status)
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill();child.wait(timeout=5)
        if recovery.exists():recover(recovery,capture_scene.rpc,time.sleep,movie_id)


class ObserverSubprocess:
    def __init__(self,manifest,movie_id):self.manifest=manifest;self.movie_id=movie_id
    def __getattr__(self,name):return getattr(subprocess,name)
    def run(self,argv,**kwargs):
        return run_observer(argv,manifest=self.manifest,movie_id=self.movie_id,**kwargs)
