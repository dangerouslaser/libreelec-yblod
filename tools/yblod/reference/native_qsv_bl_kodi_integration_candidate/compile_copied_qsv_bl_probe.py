#!/usr/bin/env python3
"""Compile the reviewed baseline probe only; no GPU/media execution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

COPY = Path('/candidate/ffmpeg-bl-qsv-candidate')
SDK = Path('/build/build.LibreELEC-Generic.x86_64-13.0-devel')
PUBLIC = Path('/public')
OUT = Path('/lab')
PINS = {
    'native_qsv_probe_handshake.h': '10d273de5c74f8f24e45d5b7dac6667541b4d4af4258a3a322b3c2037caec6d5',
    'native_qsv_bl_compare_probe.c': 'c66c574c7a9e114004dfdf202a90909ba28317ef3bdb3573e5a15a115f7748a8',
    'native_qsv_bl_metadata_equal.h': 'e04c0cc131a266250da1b9ad7b874a6a5247df013d944dbbd98a38305f30dc25',
    'build_native_qsv_bl_compare_probe.sh': 'ed2c60925098d8f19192136657cb494b65aacdab7f223d62c393fd0e3c44ddc5',
}
CODE = {
    'configure': '7abcd38af3a96b29f440e969dd8ac369ecfbbdec17f3a664e287c74874e3dba5',
    'libavcodec/qsvdec.c': 'bd88929d56c2105d1f9987c23b343c4b8fd468105b0b319061a105f885217226',
    'libavcodec/qsv_dovi.h': 'c7a409ec09971a745fbba8b5d87e14e770d501e8ef8f57a232029415f8254293',
}

def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()

def guard(report):
    for rel, wanted in PINS.items():
        assert sha(PUBLIC / 'tools/yblod/reference' / rel) == wanted
    for rel, wanted in CODE.items():
        assert sha(COPY / rel) == wanted
    for key in ('configuration_sha256', 'native_source_and_abi_sha256'):
        for rel, wanted in report[key].items():
            assert sha(COPY / rel) == wanted
            if key == 'native_source_and_abi_sha256':
                assert sha(SDK / 'build/ffmpeg-9.0.2' / rel) == wanted
    for rel, item in report['libraries'].items():
        assert (COPY / rel).stat().st_size == item['bytes']
        assert sha(COPY / rel) == item['sha256']

def main():
    cg = Path('/sys/fs/cgroup')
    assert (cg / 'memory.max').read_text().strip() == '536870912'
    assert (cg / 'memory.swap.max').read_text().strip() == '0'
    quota, period = (cg / 'cpu.max').read_text().split()
    assert quota != 'max' and 0 < int(quota) <= int(period)
    report_path = PUBLIC / 'tools/yblod/reference/native_qsv_bl_kodi_integration_candidate/QSV_BL_ISOLATED_BUILD_RESULTS.json'
    assert sha(report_path) == 'bfb36a978c6e5329ae25c48c692e4c82ace26d1348266cb1932b7837483a4789'
    report = json.loads(report_path.read_text())
    assert report['build_completed'] is True and report['sdk_sources_unchanged'] is True
    guard(report)
    runtime = OUT / 'runtime'
    runtime.mkdir()  # fresh output only
    for rel in report['libraries']:
        library = COPY / rel
        (runtime / library.name).symlink_to(library)
        (runtime / (library.name.split('.so.')[0] + '.so')).symlink_to(library)
    env = dict(os.environ, SDK_ROOT=str(SDK / 'toolchain'), PUBLIC_ROOT=str(PUBLIC),
               PROBE_OUTPUT=str(OUT), BL_FFMPEG_INCLUDE=str(COPY),
               BL_RUNTIME_LIB_DIR=str(runtime), CCACHE_DISABLE='1')
    with (OUT / 'compile.log').open('xb') as log:
        subprocess.run(['bash', str(PUBLIC / 'tools/yblod/reference/build_native_qsv_bl_compare_probe.sh')],
                       env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180, check=True)
    guard(report)
    for rel in report['libraries']:
        library = COPY / rel
        assert (runtime / library.name).resolve() == library.resolve()
        assert (runtime / (library.name.split('.so.')[0] + '.so')).resolve() == library.resolve()
    peak = int((cg / 'memory.peak').read_text())
    events = {k: int(v) for k, v in (line.split() for line in (cg / 'memory.events').read_text().splitlines())}
    assert 0 < peak <= 536870912 and not any(events.values())
    assert int((cg / 'memory.swap.current').read_text()) == 0
    assert int((cg / 'memory.swap.peak').read_text()) == 0
    binary = OUT / 'native_qsv_bl_compare_probe'
    result = {'schema': 'yblod.qsv-bl-copied-probe-compile.v1', 'compile_completed': True,
              'gpu_or_media_execution': False, 'sdk_native_and_abi_guards_unchanged': True,
              'candidate_guard_before_after': True, 'probe_sha256': sha(binary),
              'probe_bytes': binary.stat().st_size, 'source_sha256': PINS,
              'memory_peak_bytes': peak, 'memory_events': events, 'memory_swap_peak_bytes': 0,
              'note': 'Reviewed baseline probe only; pending AU scanner integration is not qualified.'}
    (OUT / 'probe-compile-results.json').write_text(json.dumps(result, indent=2) + '\n')

if __name__ == '__main__':
    main()
