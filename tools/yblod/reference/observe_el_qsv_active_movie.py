"""Add active-runtime admission and signal-safe fixture to the proven observer."""
import hashlib
import json
import os
from pathlib import Path
import signal
import capture_scene
from observe_el_qsv_movie import with_el_markers
from el_qsv_observer_fixture import interrupted


def verify_measured_generation(report,expected):
    snapshot=report.get('active_el_runtime',{});identity=snapshot.get('identity',{})
    if snapshot.get('active_before_measurement') is not True or identity.get('binary_sha256')!=expected:
        raise ValueError('Missing genuinely active candidate runtime evidence')
    if any(type(identity.get(key)) is not int or identity[key]<=0 for key in ('pid','start_ticks','service_pid')):
        raise ValueError('Invalid process generation')
    samples=report.get('gpu_samples')
    if not isinstance(samples,list) or len(samples)<2 or any(type(sample.get('pid')) is not int or type(sample.get('process_start_ticks')) is not int or sample['pid']!=identity['pid'] or sample['process_start_ticks']!=identity['start_ticks'] for sample in samples):
        raise ValueError('Active runtime and measured process generation differ')
    for phase in ('kodi_before','kodi_after'):
        service=dict(line.split('=',1) for line in report[phase].splitlines() if '=' in line)
        if service.get('MainPID')!=str(identity['service_pid']):raise ValueError('Measured service generation differs')
    return snapshot


def active_runtime_snapshot(expected):
    identity=capture_scene.process_identity()
    if identity['binary_sha256']!=expected:raise RuntimeError('Unexpected active Kodi binary')
    manifest_path=Path(os.environ['YB_EL_RUNTIME_MANIFEST'])
    manifest=json.loads(manifest_path.read_text());root=manifest_path.parent/'lib';maps={}
    prefixes=('libavcodec.so.','libavutil.so.','libavfilter.so.','libavformat.so.',
        'libswscale.so.','libswresample.so.','libavdevice.so.','libvpl.so.','libmfx-gen.so.')
    for line in (Path('/proc')/str(identity['pid'])/'maps').read_text().splitlines():
        fields=line.split(maxsplit=5)
        if len(fields)!=6 or not fields[5].startswith('/'):continue
        path=Path(fields[5])
        if not any(path.name.startswith(prefix) for prefix in prefixes):continue
        if str(path) in maps:continue
        if path.parent!=root or path.name not in manifest['artifacts']:raise RuntimeError('Foreign active runtime family')
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1048576),b''):digest.update(chunk)
        if digest.hexdigest()!=manifest['artifacts'][path.name]['sha256']:raise RuntimeError('Active runtime code changed')
        maps[str(path)]=digest.hexdigest()
    if capture_scene.process_identity()!=identity:raise RuntimeError('Active Kodi generation changed')
    return dict(identity=identity,mapped_families=maps,active_before_measurement=True)


def main():
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    source=with_el_markers(Path(__file__).with_name('observe_native_movie.py').read_text())
    replacements={
        'from observe_subtitle_fixture import subtitles_off_fixture':'from el_qsv_observer_fixture import subtitles_off_fixture',
        '    started = time.monotonic()':'    active_el_runtime = active_runtime_snapshot(args.expected_binary_sha256)\n    started = time.monotonic()',
        "    report = {'media': args.expected_title":"    report = {'active_el_runtime': active_el_runtime, 'media': args.expected_title"}
    for old,new in replacements.items():
        if source.count(old)!=1:raise RuntimeError('Observer layout changed; review additive hooks')
        source=source.replace(old,new)
    namespace=dict(__name__='__main__',__file__=str(Path(__file__).with_name('observe_native_movie.py')),
        active_runtime_snapshot=active_runtime_snapshot)
    exec(compile(source,namespace['__file__'],'exec'),namespace)


if __name__=='__main__':main()
