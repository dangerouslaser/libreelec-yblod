"""Compare completed captures on the VM; export only numeric evidence, not media or media hashes."""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess

CAPTURES = Path('/storage/dvbridge-output-captures')
STAGE_PARENT = Path('/storage')
FRAME = re.compile(r'frame-[A-Za-z0-9_-]+\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')


def canonical(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or path.resolve() != path:
        raise ValueError('Noncanonical or symlink path')
    return path


def read_json(path, maximum=1048576):
    path = canonical(str(path))
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('Invalid bounded JSON input')
    return json.loads(path.read_text())


def check_report(report, sha, movie_id, title, seek, planar, packed, qsv):
    if not SHA.fullmatch(sha):
        raise ValueError('Invalid expected executable hash')
    identity = report['identity_before']
    if identity != report['identity_after'] or identity.get('binary_sha256') != sha:
        raise ValueError('Executable/process identity changed')
    if any(type(identity.get(k)) is not int or identity[k] <= 0 for k in ('pid', 'service_pid', 'start_ticks')):
        raise ValueError('Invalid process identity')
    if set(report['shutdown'].splitlines()) != {'ActiveState=inactive', 'Result=success', 'MainPID=0'}:
        raise ValueError('Unclean capture shutdown')
    if report.get('movie') != dict(id=movie_id, title=title, seek_seconds=seek):
        raise ValueError('Unexpected movie/seek identity')
    frames = report['frames']
    if not isinstance(frames, list) or not 1 <= len(frames) <= 16:
        raise ValueError('Invalid frame count')
    seen = set()
    for frame in frames:
        path = canonical(frame['directory'])
        if path.parent != CAPTURES or not FRAME.fullmatch(path.name) or path.name in seen:
            raise ValueError('Unexpected capture location')
        seen.add(path.name)
        if (frame.get('width'), frame.get('height')) != (3840, 2160):
            raise ValueError('Unexpected capture dimensions')
        for key, expected in (('native', 1), ('native_planar', planar), ('direct_packed', packed), ('qsv_mode', qsv)):
            if type(frame.get(key)) is not int or frame[key] != expected:
                raise ValueError('Unexpected actual frame route')
        for key in ('pts', 'el_pts'):
            value = frame.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError('Invalid frame timestamp')
        if read_json(path/'frame.json', 4096) != {k:v for k,v in frame.items() if k != 'directory'}:
            raise ValueError('Frame/report association differs')
    return frames


def parse_output(stdout):
    report, end = json.JSONDecoder().raw_decode(stdout)
    lines = stdout[end:].strip().splitlines()
    if len(lines) < 6 or lines[0] != 'memory.peak' or lines[2] != 'memory.events':
        raise ValueError('Missing resource evidence')
    peak = int(lines[1])
    index = lines.index('memory.swap.current', 3)
    if len(lines) != index+2:
        raise ValueError('Unexpected output after resource evidence')
    events = {}
    for line in lines[3:index]:
        key, value = line.split()
        if key in events:
            raise ValueError('Repeated memory event')
        events[key] = int(value)
    if not {'low', 'high', 'max', 'oom', 'oom_kill'} <= events.keys() or any(events.values()) or int(lines[-1]) != 0 or not 0 < peak <= 536870912:
        raise ValueError('Memory limit/swap evidence failed')
    if report.get('schema') != 'yblod.renderer-output-comparison.v1' or not report.get('identical_source_layer_timestamps') or not report.get('identical_source_metadata'):
        raise ValueError('Source equality not proven')
    semantic = report.get('picture_and_payload_preservation') or {}
    if not semantic.get('picture_and_payload_preserved'):
        raise ValueError('Picture/payload equality not proven')
    if set(report['planes']) != {'I', 'P', 'T'} or any(p.get('max_absolute_codes') != 0 or p.get('exact_percent') != 100 for p in report['planes'].values()):
        raise ValueError('Nonexact picture planes')
    return report, dict(memory_peak_bytes=peak, memory_limit_bytes=536870912,
                        swap_limit_bytes=0, swap_current_bytes=0, cpu_limit=1, memory_events=events)


def run(args):
    if args.before_planar not in (0, 1) or args.after_planar not in (0, 1) or args.before_packed not in (0, 1) or args.after_packed not in (0, 1) or args.qsv_mode not in (0, 1, 2):
        raise ValueError('Invalid requested routes')
    if not math.isfinite(args.seek_seconds) or args.seek_seconds < 0:
        raise ValueError('Invalid seek')
    stage = canonical(args.expected_stage_root)
    if stage.parent != STAGE_PARENT or not stage.name.startswith('yblod-'):
        raise ValueError('Unexpected bounded stage root')
    wrapper = canonical(args.wrapper)
    if wrapper.parent != stage or not wrapper.is_file():
        raise ValueError('Wrapper outside expected stage')
    output = canonical(args.output)
    if output.parent != stage or output.exists() or not re.fullmatch(r'[A-Za-z0-9_-]+', output.name):
        raise ValueError('Expected fresh bounded output directory')
    report_paths = [canonical(value) for value in (args.before_report, args.after_report)]
    if any(path.parent != stage for path in report_paths):
        raise ValueError('Report outside expected stage')
    reports = [read_json(path) for path in report_paths]
    pairs = [check_report(report, sha, args.movie_id, args.expected_title, args.seek_seconds, planar, packed, args.qsv_mode)
             for report,sha,planar,packed in zip(reports, (args.before_binary_sha256,args.after_binary_sha256), (args.before_planar,args.after_planar), (args.before_packed,args.after_packed))]
    if len(pairs[0]) != len(pairs[1]):
        raise ValueError('Different frame counts')
    for before, after in zip(*pairs):
        if before['pts'] != after['pts'] or before['el_pts'] != after['el_pts']:
            raise ValueError('Different paired timestamps')
    # All associations are checked before launching any comparator.
    output.mkdir()
    results = []
    for index,(before,after) in enumerate(zip(*pairs)):
        command = ['systemd-run', '--quiet', '--pipe', '--wait', '--collect',
                   '-p', 'MemoryMax=512M', '-p', 'MemorySwapMax=0', '-p', 'CPUQuota=100%',
                   'sh', str(wrapper), before['directory'], after['directory']]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
        (output/f'comparison-{index:02d}.stdout.txt').write_text(completed.stdout)
        (output/f'comparison-{index:02d}.stderr.txt').write_text(completed.stderr)
        if completed.returncode:
            raise RuntimeError('Comparator failed; inspect private VM output')
        report, resources = parse_output(completed.stdout)
        for actual, expected in ((report['before'],before),(report['after'],after)):
            if any(type(actual.get(key)) is not int or actual[key] != expected[key] for key in ('native','native_planar','direct_packed')):
                raise ValueError('Comparator route/report mismatch')
        (output/f'comparison-{index:02d}.json').write_text(json.dumps(report, indent=2, allow_nan=False))
        results.append(dict(index=index, pts=before['pts'], el_pts=before['el_pts'], comparison=report, resources=resources))
    aggregate = dict(schema='yblod.vm-capture-comparison-run.v1', complete=True,
        executable_sha256=dict(before=args.before_binary_sha256,after=args.after_binary_sha256),
        process_identity_stable=True, movie=dict(id=args.movie_id,title=args.expected_title,seek_seconds=args.seek_seconds),
        frames=results, raw_media_exported=False, private_media_hashes_exported=False,
        scope='Exact captured tunnel picture/payload preservation; not physical HDMI or Dolby conformance.')
    (output/'comparison-summary.json').write_text(json.dumps(aggregate, indent=2, allow_nan=False))
    print(json.dumps(aggregate, indent=2, allow_nan=False))
    return aggregate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('before-report','after-report','before-binary-sha256','after-binary-sha256','expected-title','expected-stage-root','wrapper','output'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--movie-id', required=True, type=int)
    parser.add_argument('--seek-seconds', required=True, type=float)
    parser.add_argument('--before-planar', type=int, default=0)
    parser.add_argument('--after-planar', type=int, default=1)
    parser.add_argument('--before-packed', type=int, default=1)
    parser.add_argument('--after-packed', type=int, default=1)
    parser.add_argument('--qsv-mode', type=int, required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
