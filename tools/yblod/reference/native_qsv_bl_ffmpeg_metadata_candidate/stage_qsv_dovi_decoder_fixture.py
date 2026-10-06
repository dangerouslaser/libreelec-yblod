"""Apply the source candidate only to disposable /tmp fixture copies."""
import hashlib
import pathlib
import shutil
import subprocess

source = pathlib.Path('/build/build.LibreELEC-Generic.x86_64-13.0-devel/build/ffmpeg-9.0.2')
candidate = pathlib.Path('/candidate')
destination = pathlib.Path('/tmp/qsv-dovi-fixture')
destination.mkdir()
(destination / 'libavcodec').mkdir()
expected = {
    'configure': 'ca57b961b55711e417c4d93123ca70cc56650f3005e747ce36531e7ab5d4043e',
    'libavcodec/qsvdec.c': '94187d5bf29fa060daac741cf12d9f9c99abee3b1f2b93ebc5fe3375369d5f4f',
}
for name in ('configure', 'libavcodec/qsvdec.c'):
    assert hashlib.sha256((source / name).read_bytes()).hexdigest() == expected[name], name
    shutil.copyfile(source / name, destination / name)
subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i',
                str(candidate / 'qsv-bl-metadata-source-only.patch')], cwd=destination, check=True)
for name in ('qsvdec.c', 'qsv_dovi.h'):
    shutil.copyfile(destination / 'libavcodec' / name, destination / name)
for name in ('test_qsv_dovi_mfx.c', 'test_qsv_dovi_allocator.c', 'test_qsv_dovi_gate.c',
             'test_qsv_dovi_config.h', 'test_qsv_dovi_nogpl_config.h'):
    shutil.copyfile(candidate / name, destination / name)
print('source_candidate_disposable_patch_PASS')
for name in ('qsvdec.c', 'qsv_dovi.h'):
    print(name + '_source_sha256=' + hashlib.sha256((destination / name).read_bytes()).hexdigest())
