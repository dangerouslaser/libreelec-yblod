#!/usr/bin/env python3
"""Container-local, privately logged BL hardware diagnostic. Not a benchmark."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

from observe_live_el_qsv_probe import code_fingerprint
import observe_picture_lifecycle_qsv_bl_probe as observer

SDK = Path('/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain')
LIB = SDK / 'x86_64-libreelec-linux-gnu/sysroot/usr/lib'
GCC = SDK / 'x86_64-libreelec-linux-gnu/lib'
SOURCE = SDK.parent / 'build/ffmpeg-9.0.2'
COPY = Path('/candidate/ffmpeg-bl-qsv-candidate')
PROBE = Path('/probe/native_qsv_bl_compare_probe')
OUT = Path('/diagnostics')
PROVENANCE = Path('/duration-source')
EXPECTED_DIAGNOSTIC_REPORT_SHA = 'c1024b3856dfe0b9e2d6ddbd9c3de4e273e1c87dfe402f89541fea3a3c1c5c26'
EXPECTED_DIAGNOSTIC_AVCODEC_SHA = '871a5b008e907d67bc4ba3b36cc9dbe932657505c194c9d2f34784309c394a95'
BINARY = '112a42a3f48d4ad48b036e5c83dc7a7a07c6e8e0832a399b0c83fe68aa3ebfab'
DRIVER = 'd30f166ce5f9949b8195a8f6a4124baa302978b427a3714dcba09b2226cfe798'
PINS = {
    'native_qsv_bl_compare_probe.c':'c66c574c7a9e114004dfdf202a90909ba28317ef3bdb3573e5a15a115f7748a8',
    'native_qsv_bl_metadata_equal.h':'e04c0cc131a266250da1b9ad7b874a6a5247df013d944dbbd98a38305f30dc25',
    'native_qsv_probe_handshake.h':'10d273de5c74f8f24e45d5b7dac6667541b4d4af4258a3a322b3c2037caec6d5',
    'build_native_qsv_bl_compare_probe.sh':'ed2c60925098d8f19192136657cb494b65aacdab7f223d62c393fd0e3c44ddc5',
}
CODE = {
    'configure':'7abcd38af3a96b29f440e969dd8ac369ecfbbdec17f3a664e287c74874e3dba5',
    'libavcodec/qsvdec.c':'a87bbcec949bc5668a0fdcf14100bf20901a9b9242c3df0627aa3ac4dd74e8ed',
    'libavcodec/qsv_dovi.h':'d0612fbabd19dd9797d17191204d9d57b57789ff00fbab6d638d83f1c8e3350f',
}

def guard(report):
    assert code_fingerprint(PROBE)[1] == BINARY
    assert code_fingerprint(LIB / 'dri/iHD_drv_video.so')[1] == DRIVER
    compiled_path = Path('/probe/compile-results.json')
    assert code_fingerprint(compiled_path)[1] == '5d9bb6581b09b76e50fcd25a615f0a1c7a0bbb05d603cefb6e5f181faa53cd97'
    compiled = json.loads(compiled_path.read_text())
    assert compiled['compile_and_cpu_tests_passed'] is True and compiled['hardware_or_media_executed'] is False
    assert compiled['outputs']['native_qsv_bl_compare_probe']['sha256'] == BINARY
    assert compiled['source_sha256']['native_qsv_bl_compare_probe.c'] == '90a80193c1441f60c478894f15182ec65b1660b0e078a0093dd4df24a4b337e6'
    assert len(compiled['source_sha256']) == 10
    for name, wanted in compiled['source_sha256'].items():
        assert code_fingerprint(PROVENANCE/name)[1] == wanted
    for name, wanted in CODE.items():
        assert code_fingerprint(COPY / name)[1] == wanted
    for field in ('configuration_sha256','native_source_and_abi_sha256'):
        for name, wanted in report[field].items():
            assert code_fingerprint(COPY / name)[1] == wanted
            if field == 'native_source_and_abi_sha256':
                assert code_fingerprint(SOURCE / name)[1] == wanted
    for name, item in report['libraries'].items():
        assert (COPY / name).stat().st_size == item['bytes']
        assert code_fingerprint(COPY / name)[1] == item['sha256']

def make_runtime_and_closure(report):
    runtime = OUT / 'runtime'
    runtime.mkdir()
    for name in report['libraries']:
        library = COPY / name
        (runtime / library.name).symlink_to(library)
        (runtime / (library.name.split('.so.')[0]+'.so')).symlink_to(library)
    def resolve(path):
        result = path.resolve(strict=True)
        if not result.is_file() or not (result.is_relative_to(SDK) or result.is_relative_to(COPY)):
            raise ValueError('Explicit copied candidate or SDK code required')
        return result
    def dependencies(path):
        dynamic = subprocess.check_output(['readelf','-d',str(path)], text=True, timeout=10)
        lines = [line for line in dynamic.splitlines() if '(NEEDED)' in line]
        if not lines and path.resolve(strict=True) != (LIB / 'ld-linux-x86-64.so.2').resolve(strict=True):
            raise ValueError('Required dynamic code has no dependencies')
        names = []
        for line in lines:
            found = re.fullmatch(r'\s*0x[0-9a-fA-F]+\s+\(NEEDED\)\s+Shared library: \[([^]/]+)\]\s*', line)
            if found is None:
                raise ValueError('Unparsed dynamic dependency forbidden')
            names.append(found.group(1))
        for name in names:
            options = [p/name for p in (runtime,LIB,GCC) if (p/name).exists()]
            if not options:
                raise ValueError('Dependency unavailable in explicit closure')
            selected = resolve(options[0])
            if name.startswith(('libavcodec.so','libavformat.so','libavutil.so','libavfilter.so','libavdevice.so','libpostproc.so','libswscale.so','libswresample.so')) and not selected.is_relative_to(COPY):
                raise ValueError('SDK FFmpeg substitution forbidden')
            yield selected
    pending = [resolve(COPY / name) for name in report['libraries']]
    pending += [resolve(LIB / name) for name in ('ld-linux-x86-64.so.2','libvpl.so','libmfx-gen.so','dri/iHD_drv_video.so')]
    pending += list(dependencies(PROBE))
    files = {}
    while pending:
        path = pending.pop()
        if str(path) in files:
            continue
        files[str(path)] = {'path':str(path),'sha256':code_fingerprint(path)[1]}
        pending += list(dependencies(path))
        if len(files) > 256:
            raise ValueError('Bounded code closure exceeded')
    manifest = OUT / 'runtime-identity-private.json'
    with manifest.open('x') as stream:
        json.dump({'files':files}, stream)
    return runtime, manifest, files

def classify_private_stderr(text):
    """Whitelist diagnostic identifiers/numbers only; never expose log prefixes."""
    classified = {}
    for name in ('header_result','init_result','prepare_error','consume_error','queued_sync_error','output_association_error','output_reject','interlace_reject','drain_reject','retry_deadline','surface_cap'):
        values = re.findall(r'QSV_DOVI_DIAG '+name+r'=(-?[0-9]+)(?:\n|$)',text)
        if values:
            numbers = [int(value) for value in values]
            if len(numbers) > 64 or any(not -2147483648 <= value <= 2147483647 for value in numbers):
                raise ValueError('Unexpected diagnostic number extent')
            if name in ('output_reject','interlace_reject','drain_reject','retry_deadline','surface_cap') and any(value != 1 for value in numbers):
                raise ValueError('Expected rejection boolean marker')
            classified[name] = numbers
    fields = ('progressive','pool_present','video_io','p010','frame_context','frame_qsv','frame_p010','device_identity','initialized','session_present')
    pattern = r'QSV_DOVI_DIAG input_invalid '+' '.join(name+r'=([01])' for name in fields)+r'(?:\n|$)'
    rows = re.findall(pattern,text)
    if len(rows) > 64:
        raise ValueError('Unexpected diagnostic row extent')
    if rows:
        classified['input_invalid'] = [dict(zip(fields,map(int,row))) for row in rows]
    for name in ('retry_sync_reject','incompatible_reject','progress_reject'):
        pattern = r'QSV_DOVI_DIAG '+name+r' status=(-?[0-9]+) sync=([01]) consumed=([01])(?:\n|$)'
        rows = re.findall(pattern,text)
        if len(rows)>64 or any(not -32768 <= int(row[0]) <= 32767 for row in rows):
            raise ValueError('Unexpected SDK status extent')
        if rows:
            classified[name] = [{'status':int(row[0]),'sync':int(row[1]),'consumed':int(row[2])} for row in rows]
    return classified

def main():
    os.umask(0o077)
    def interrupted(*unused):
        raise RuntimeError('Owned inner diagnostic interrupted')
    for name in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(name, interrupted)
    report_path = Path('/public/tools/yblod/reference/native_qsv_bl_kodi_integration_candidate/QSV_BL_ISOLATED_BUILD_RESULTS.json')
    assert code_fingerprint(report_path)[1] == 'bfb36a978c6e5329ae25c48c692e4c82ace26d1348266cb1932b7837483a4789'
    original_report = json.loads(report_path.read_text())
    diagnostic_path = Path('/candidate/keyflag-build-results.json')
    assert code_fingerprint(diagnostic_path)[1] == EXPECTED_DIAGNOSTIC_REPORT_SHA
    report = json.loads(diagnostic_path.read_text())
    assert report['build_completed'] is True and report['diagnostic_only'] is False
    assert report['schema'] == 'yblod.qsv-bl-keyflag-library-build.v1'
    assert report['hardware_or_quality_qualified'] is False and report['original_candidate_unchanged'] is True
    assert report['base_report_sha256'] == 'd46b736f6288ada414b1384bdf7cba43094b5e7fe7dae4b0f008ad7c99a14cae'
    assert report['base_provenance']['compatible_param_patch_sha256'] == '797f752ebb38a23c4e0efb81705f70e8c14358a62e7d783d2765c6a70e9cc2d2'
    assert report['qsv_dovi_header_sha256'] == CODE['libavcodec/qsv_dovi.h']
    assert report['public_headers_unchanged'] is True and report['elf_contract_unchanged'] is True
    assert report['sdk_native_and_abi_guards_unchanged'] is True
    assert report['qsvdec_sha256'] == CODE['libavcodec/qsvdec.c']
    for field in ('configuration_sha256','native_source_and_abi_sha256'):
        assert report[field] == original_report[field]
    assert set(report['libraries']) == set(original_report['libraries'])
    for name,item in original_report['libraries'].items():
        if not name.startswith('libavcodec/'):
            assert report['libraries'][name] == item
    assert report['libraries']['libavcodec/libavcodec.so.63']['sha256'] == EXPECTED_DIAGNOSTIC_AVCODEC_SHA
    limits = observer.resources()
    assert limits['memory_limit_bytes'] == 1610612736 and limits['swap_limit_bytes'] == 0 and 0 < limits['cpu_limit'] <= 1
    guard(report)
    runtime, manifest, closure = make_runtime_and_closure(report)
    if os.environ.get('YB_BL_CLOSURE_ONLY') == '1':
        guard(report)
        for item in closure.values():
            assert code_fingerprint(Path(item['path']))[1] == item['sha256']
        limits = observer.resources()
        assert 0 < limits['peak_memory_bytes'] <= 1610612736 and not any(limits['memory_events'].values())
        assert limits['swap_current_bytes'] == 0 and limits['swap_peak_bytes'] == 0
        result = {'scope':'Code closure preparation only; no GPU or media access', 'pass':True,
                  'closure_code_files':len(closure),'candidate_sources_and_eight_libraries_guarded_before_after':True,
                  'resources':limits}
        with (OUT/'closure-only-results.json').open('x') as stream:
            json.dump(result,stream)
        print(json.dumps(result))
        return 0
    sys.argv = ['observer', '--binary',str(PROBE),'--binary-sha256',BINARY,
                '--loader',str(LIB/'ld-linux-x86-64.so.2'),'--runtime',str(runtime),
                '--extra-library-dir',str(LIB),'--extra-library-dir',str(GCC),
                '--driver',str(LIB/'dri/iHD_drv_video.so'),'--driver-sha256',DRIVER,
                '--source','/input/source.mkv','--node','/dev/dri/renderD128',
                '--runtime-identity',str(manifest),'--private-prefix',str(OUT/'live'),
                '--seek-us','1200000000','--pts-us','1210000000','--pts-us','1220010000','--pts-us','1230020000']
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        status = observer.main()
    result = json.loads(capture.getvalue())
    guard(report)
    for name,item in closure.items():
        assert code_fingerprint(Path(item['path']))[1] == item['sha256']
    result['private_error_classification'] = classify_private_stderr((OUT/'live.stderr-private.log').read_text())
    result.update(diagnostic_library_sources_and_eight_libraries_guarded_before_after=True,
                  duration_window_compiled_source_verified=True, sdk_native_and_abi_guards_unchanged=True,
                  closure_code_files=len(closure), selected_direct_mapped_frames=3 if result['pass'] else 0)
    limits = observer.resources()
    result['resources'] = limits
    if any(limits['memory_events'].values()) or limits['swap_peak_bytes'] or limits['swap_current_bytes'] or not 0 < limits['peak_memory_bytes'] <= 1610612736:
        result['pass'] = False
    with (OUT/'observer-results.json').open('x') as stream:
        json.dump(result, stream)
    print(json.dumps(result))
    return status if result['pass'] else 1

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except BaseException as error:
        if isinstance(error, SystemExit) and error.code == 0:
            raise
        try:
            failure = {'pass':False, 'error_type':type(error).__name__, 'resources':observer.resources()}
            (OUT/'failure-resources-private.json').write_text(json.dumps(failure))
        except BaseException:
            pass
        raise
