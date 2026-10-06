"""Apply the published foundation and additive fix to disposable copies only."""
import pathlib
import hashlib
import runpy
import shutil
import subprocess

runpy.run_path('/candidate/stage_qsv_dovi_decoder_fixture.py', run_name='__main__')
root = pathlib.Path('/tmp/qsv-dovi-fixture')
subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i',
                '/candidate/qsv-bl-metadata-real-init-fix.patch'], cwd=root, check=True)
shutil.copyfile(root / 'libavcodec/qsvdec.c', root / 'qsvdec.c')
shutil.copyfile('/candidate/test_qsv_dovi_real_init.c', root / 'test_qsv_dovi_real_init.c')
print('corrected_qsvdec_source_sha256=' + hashlib.sha256((root / 'qsvdec.c').read_bytes()).hexdigest())
