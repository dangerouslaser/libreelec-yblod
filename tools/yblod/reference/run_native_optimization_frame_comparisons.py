"""Bounded private capture comparison with sanitized public scalar output only."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from native_optimization_qualification import OPTIONS, qualify_frames
from observe_subtitle_fixture import validate_fixture
import run_vm_capture_comparisons as base

ROUTES = ('native', 'direct_packed', 'native_planar', 'qsv_mode', *OPTIONS)
EVENTS = {'low', 'high', 'max', 'oom', 'oom_kill', 'oom_group_kill', 'sock_throttled'}


def timestamp(value):
    if type(value) not in (int, float) or not 1200000000 < value <= 86400000000 or int(value) != value:
        raise ValueError('Exact integral source timestamp after requested seek required')
    return int(value)


def check_frames(report, binary_hash, option, enabled, legacy=False):
    frames = base.check_report(report, binary_hash, 3391, 'Saving Private Ryan', 1200, 1, 1, 1)
    validate_fixture(report.get('subtitle_fixture'), 3391)
    if len(frames) != 3:
        raise ValueError('Exactly three matched scene frames required')
    stamps = []
    for frame in frames:
        for key in OPTIONS:
            expected = enabled if key == option else 0
            if legacy and key not in frame:
                continue
            if type(frame.get(key)) is not int or frame[key] != expected:
                raise ValueError('Wrong actual isolated optimization capture route')
        stamp = timestamp(frame['pts'])
        if timestamp(frame['el_pts']) != stamp:
            raise ValueError('Source layer timestamps differ')
        stamps.append(stamp)
    if stamps != sorted(set(stamps)):
        raise ValueError('Distinct increasing source frames required')
    return frames


def exact_comparison(stdout, before, after):
    report, resources = base.parse_output(stdout)
    if any(report.get(key) is not True for key in ('identical_source_metadata', 'identical_source_layer_timestamps')):
        raise ValueError('Strict source equality evidence required')
    if report['picture_and_payload_preservation'].get('picture_and_payload_preserved') is not True:
        raise ValueError('Strict payload preservation evidence required')
    for plane in report['planes'].values():
        if type(plane['max_absolute_codes']) is not int or plane['max_absolute_codes'] != 0 or \
           type(plane['exact_percent']) not in (int, float) or plane['exact_percent'] != 100:
            raise ValueError('Zero-tolerance picture evidence required')
    events = resources['memory_events']
    if not set(events) <= EVENTS:
        raise ValueError('Unexpected memory event fields')
    for phase, frame in (('before', before), ('after', after)):
        for key in ('native', 'direct_packed', 'native_planar', *OPTIONS):
            if key not in frame:
                if key in report[phase]:
                    raise ValueError('Comparator invented an absent legacy option')
                continue
            if type(report[phase].get(key)) is not int or report[phase][key] != frame[key]:
                raise ValueError('Comparator actual route differs from validated capture')
    return dict(source_timestamps_equal=True, source_metadata_equal=True,
                picture_and_payload_preserved=True,
                maximum_absolute_12bit_codes={key: 0 for key in ('I', 'P', 'T')},
                exact_picture_percent={key: 100 for key in ('I', 'P', 'T')},
                resources=resources,
                **{phase: dict(pts_microseconds=timestamp(frame['pts']),
                   el_pts_microseconds=timestamp(frame['el_pts']),
                   route={key: frame[key] for key in ROUTES if key in frame})
                   for phase, frame in (('before', before), ('after', after))})


def run(args):
    if not base.SHA.fullmatch(args.binary_sha256):
        raise ValueError('Invalid expected candidate binary hash')
    legacy = args.baseline_binary_sha256 is not None
    if legacy:
        if args.optimization is not None or not base.SHA.fullmatch(args.baseline_binary_sha256) or args.baseline_binary_sha256 == args.binary_sha256:
            raise ValueError('Distinct retained baseline and candidate OFF required')
    elif args.optimization not in OPTIONS:
        raise ValueError('Choose exactly one isolated optimization')
    stage = base.canonical(args.expected_stage_root)
    if stage.parent != base.STAGE_PARENT or not stage.name.startswith('yblod-'):
        raise ValueError('Unexpected bounded stage root')
    wrapper = base.canonical(args.wrapper)
    output = base.canonical(args.output)
    if wrapper.parent != stage or not wrapper.is_file() or output.parent != stage or output.exists() or not re.fullmatch(r'[A-Za-z0-9_-]+', output.name):
        raise ValueError('Expected trusted stage wrapper and fresh private output directory')
    paths = [base.canonical(value) for value in (args.before_report, args.after_report)]
    if any(path.parent != stage for path in paths):
        raise ValueError('Capture report outside expected stage')
    reports = [base.read_json(path) for path in paths]
    frames = [check_frames(report, binary_hash, args.optimization, enabled, old)
              for report, binary_hash, enabled, old in zip(reports,
                 (args.baseline_binary_sha256 if legacy else args.binary_sha256, args.binary_sha256),
                 (0, 0 if legacy else 1), (legacy, False))]
    if any(before['pts'] != after['pts'] or before['el_pts'] != after['el_pts'] for before, after in zip(*frames)):
        raise ValueError('Before/after source timestamps differ')
    output.mkdir()
    scalars = []
    for index, (before, after) in enumerate(zip(*frames)):
        command = ['systemd-run', '--quiet', '--pipe', '--wait', '--collect',
                   '-p', 'MemoryMax=512M', '-p', 'MemorySwapMax=0', '-p', 'CPUQuota=100%',
                   'sh', str(wrapper), before['directory'], after['directory']]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
        (output/f'comparison-{index:02d}.stdout.txt').write_text(completed.stdout)
        (output/f'comparison-{index:02d}.stderr.txt').write_text(completed.stderr)
        if completed.returncode:
            raise RuntimeError('Comparator failed; inspect private output')
        scalars.append(dict(index=index, **exact_comparison(completed.stdout, before, after)))
    scalar = dict(schema='yblod.native-optimization-baseline-preservation-results.v1' if legacy else 'yblod.native-optimization-frame-results.v1',
                  binary_sha256=args.binary_sha256, content='Saving Private Ryan', movie_id=3391,
                  seek_seconds=1200, frames=scalars, source_identity_verified=True,
                  subtitles_disabled_and_restored_both=True,
                  scope='Exact captured native packed planar tunnel picture/payload preservation; not playback performance, physical HDMI, or Dolby conformance.')
    if legacy:
        scalar['baseline_binary_sha256'] = args.baseline_binary_sha256
        scalar['legacy_missing_optimization_fields_not_inferred'] = True
    else:
        scalar['optimization'] = args.optimization
    summary = output/'comparison-summary.json'
    summary.write_text(json.dumps(scalar, indent=2, allow_nan=False))
    if not legacy:
        qualify_frames(summary, args.binary_sha256, args.optimization)
    print(json.dumps(scalar, indent=2, allow_nan=False))
    return scalar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('before-report', 'after-report', 'binary-sha256', 'expected-stage-root', 'wrapper', 'output'):
        parser.add_argument('--'+name, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--optimization', choices=OPTIONS)
    mode.add_argument('--baseline-binary-sha256')
    run(parser.parse_args())


if __name__ == '__main__':
    main()
