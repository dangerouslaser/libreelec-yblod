"""Build-wrapper env forwarding using a fake Docker CLI; no builds or GPU."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
class NativeBuildWrapperTests(unittest.TestCase):
    def run_wrapper(self,value):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);tools=root/'tools/yblod';tools.mkdir(parents=True)
            wrapper=tools/'build.sh';wrapper.write_bytes((ROOT/'tools/yblod/build.sh').read_bytes())
            bin_dir=root/'bin';bin_dir.mkdir();capture=root/'docker.args'
            docker=bin_dir/'docker'
            docker.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$YB_TEST_DOCKER_ARGS"\nexit 0\n')
            docker.chmod(0o755)
            env=os.environ.copy();env.pop('YBLOD_NATIVE_RECONSTRUCTION',None)
            env.update(PATH=str(bin_dir)+os.pathsep+env['PATH'],YB_TEST_DOCKER_ARGS=str(capture),BUILD_JOBS='1',BUILD_MEMORY='4g')
            if value is not None:env['YBLOD_NATIVE_RECONSTRUCTION']=value
            result=subprocess.run(['bash',str(wrapper),'synthetic-test'],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            return capture.read_text().splitlines()
    def test_default_off_forwarded_to_container(self):
        args=self.run_wrapper(None)
        self.assertIn('YBLOD_NATIVE_RECONSTRUCTION=0',args)
        self.assertNotIn('YBLOD_NATIVE_RECONSTRUCTION=1',args)
    def test_explicit_opt_in_forwarded_to_container(self):
        args=self.run_wrapper('1')
        self.assertIn('YBLOD_NATIVE_RECONSTRUCTION=1',args)
        self.assertEqual(args[args.index('--memory')+1],'4g')
        self.assertEqual(args[args.index('--memory-swap')+1],'4g')
        self.assertIn('CONCURRENCY_MAKE_LEVEL=1',args)
    def test_bash_syntax(self):
        result=subprocess.run(['bash','-n',str(ROOT/'tools/yblod/build.sh')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
if __name__=='__main__':unittest.main()
