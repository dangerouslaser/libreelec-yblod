"""Exact-frame-qualified 600-second planar ABBA; matched subtitles restored."""
import json
from pathlib import Path
import re

from observe_subtitle_fixture import validate_fixture
from run_colour_import_matrix import parser, run_configured_matrix, validate_request
from run_native_planar_matrix import validate_planar_report

MOVIES = {3391: ('Saving Private Ryan', 'yblod.native-planar-spr-frame-scalar-results.v1'),
          51: ('1917', 'yblod.native-planar-1917-frame-scalar-results.v1')}
COMPARISON = 'same_new_binary_planar_disabled_to_enabled'


def sustained_planar_preservation_report(path, binary_hash, movie_id, title):
    report = json.loads(path.read_text())
    expected = MOVIES.get(movie_id)
    if (not re.fullmatch(r'[a-f0-9]{64}',binary_hash) or not isinstance(report,dict) or
            expected is None or expected[0] != title or report.get('schema') != expected[1] or
            report.get('content') != title or report.get('candidate_binary_sha256') != binary_hash or
            type(report.get('seek_seconds')) is not int or report['seek_seconds'] != 1200):
        raise ValueError('Frame proof does not match candidate binary, movie and scene')
    comparisons = report.get('comparisons')
    if not isinstance(comparisons, list) or any(not isinstance(row, dict) for row in comparisons):
        raise ValueError('Malformed frame comparison groups')
    selected = [row for row in comparisons if row.get('comparison') == COMPARISON]
    if len(selected) != 1:
        raise ValueError('Exactly one same-candidate planar OFF/ON comparison required')
    frames = selected[0].get('frames')
    if not isinstance(frames, list) or not 3 <= len(frames) <= 16:
        raise ValueError('At least three qualified same-candidate frames required')
    labels = set()
    timestamps = []
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get('frame_label'), str) or not frame['frame_label'] or frame['frame_label'] in labels:
            raise ValueError('Invalid or duplicate frame label')
        labels.add(frame['frame_label'])
        if any(frame.get(key) is not True for key in ('source_metadata_equal', 'source_timestamps_equal', 'picture_and_payload_preserved')):
            raise ValueError('Frame source or picture/payload preservation failed')
        maximum = frame.get('maximum_absolute_12bit_codes')
        exact = frame.get('exact_picture_percent')
        if (not isinstance(maximum, dict) or set(maximum) != {'I','P','T'} or
                any(type(value) is not int or value != 0 for value in maximum.values()) or
                not isinstance(exact, dict) or set(exact) != {'I','P','T'} or
                any(type(value) not in (int,float) or value != 100 for value in exact.values())):
            raise ValueError('Picture code values changed or precision proof malformed')
        source_times = []
        for phase, planar in (('before', 0), ('after', 1)):
            value = frame.get(phase)
            route = value.get('route') if isinstance(value, dict) else None
            if not isinstance(route, dict) or any(type(route.get(key)) is not int or route[key] != wanted
                    for key,wanted in (('native',1),('direct_packed',1),('native_planar',planar),('qsv_mode',1))):
                raise ValueError('Actual native packed planar route proof failed')
            for key in ('pts_microseconds','el_pts_microseconds'):
                timestamp = value.get(key)
                if type(timestamp) is not int or timestamp <= 1200*1000000:
                    raise ValueError('Invalid source timestamp')
                source_times.append(timestamp)
        if len(set(source_times)) != 1:
            raise ValueError('Paired source timestamps differ')
        timestamps.append(source_times[0])
    if timestamps != sorted(set(timestamps)):
        raise ValueError('Frame proof timestamps must be distinct and increasing')
    return dict(candidate_binary_sha256=binary_hash, content=title, movie_id=movie_id,
                comparison=COMPARISON, frame_count=len(frames),
                source_metadata_and_timestamps_equal=True, picture_and_payload_preserved=True,
                maximum_absolute_12bit_codes={'I':0,'P':0,'T':0},
                native_planar_before=0,native_planar_after=1,direct_packed_both=1,
                scope='Published matched-frame scalar proof, not whole-media identity or Dolby conformance.')


def validate_long_planar_args(args):
    validate_request(args)
    if (args.seconds != 600 or args.seek_seconds != 1200 or
            MOVIES.get(args.movie_id, (None,))[0] != args.expected_title or
            getattr(args, 'subtitles_off', False) is not True):
        raise ValueError('Use matched subtitle-free 600-second SPR or 1917 windows at20minutes')
    normalized = []
    for flag in (0,1):
        lines = (args.config_dir/f'native-planar-{flag}.conf').read_text().splitlines()
        marker = f'Environment=DVBRIDGE_NATIVE_PLANAR_OUTPUT={flag}'
        if lines.count(marker) != 1 or sum(line.startswith('Environment=DVBRIDGE_NATIVE_PLANAR_OUTPUT=') for line in lines) != 1:
            raise ValueError('Wrong native planar flag')
        for name in ('RECONSTRUCTION','DIAGNOSTICS','FP32','COLOUR_NO_REIMPORT','NLQ_LUT','PACKED_OUTPUT'):
            prefix = f'Environment=DVBRIDGE_NATIVE_{name}='
            if lines.count(prefix+'1') != 1 or sum(line.startswith(prefix) for line in lines) != 1:
                raise ValueError('Both cases require native FP32/LUT/handoff and packed output')
        for name in ('OUTPUTS','PAIRS'):
            prefix = f'Environment=DVBRIDGE_CAPTURE_{name}='
            if lines.count(prefix+'0') != 1 or sum(line.startswith(prefix) for line in lines) != 1:
                raise ValueError('Capture must be disabled during performance measurements')
        normalized.append([line for line in lines if line != marker])
    if normalized[0] != normalized[1]:
        raise ValueError('Configurations differ beyond the native planar flag')
    if not args.preservation_report:
        raise ValueError('Candidate- and movie-associated frame proof required')
    return [sustained_planar_preservation_report(path,args.binary_sha256,args.movie_id,args.expected_title)
            for path in args.preservation_report]


def make_long_planar_validator(movie_id):
    original = None
    def validate(report, stopped, flag, binary_hash):
        nonlocal original
        fixture = report.get('subtitle_fixture')
        validate_fixture(fixture,movie_id)
        if original is not None and fixture['before'] != original:
            raise ValueError('Original subtitle state differs between matched cases')
        result = validate_planar_report(report,stopped,flag,binary_hash)
        original = dict(fixture['before'])
        return result
    return validate


def argument_parser():
    result = parser()
    result.set_defaults(seconds=600,seek_seconds=1200)
    result.add_argument('--preservation-report',action='append',type=Path,required=True,
                        help='Published per-film planar frame scalar JSON associated with this binary.')
    return result


def main():
    args = argument_parser().parse_args()
    qualified = validate_long_planar_args(args)
    print(json.dumps(dict(output_preservation_qualified=qualified,subtitles_off=True)),flush=True)
    run_configured_matrix(args,[args.config_dir/f'native-planar-{flag}.conf' for flag in (0,1)],
        f'native-planar-long-movie{args.movie_id}',
        lambda flag:f'native-fp32-lut release-rgb packed_output=1 native_planar={flag}',
        make_long_planar_validator(args.movie_id))


if __name__ == '__main__': main()
