"""Short same-build BL VAAPI/QSV ABBA; EL QSV fixed and picture-qualified."""
import hashlib
import json
import math
import re
from pathlib import Path
from run_colour_import_matrix import validate_request
from run_el_qsv_matrix import config_paths, validate_configs
from run_native_planar_matrix import validate_planar_report
from el_qsv_telemetry import qualify_actual_el_use
from native_optimization_telemetry import qualify_actual_use
from observe_subtitle_fixture import validate_fixture

ROOT=Path('/storage/yblod-qsv-el-aff416-runtime')
CANDIDATE='db2ada4e0646f845c3bfa2dd96fab3f73dbc161fdfc0944691084753e30f104b'

def pinned_json(path,digest):
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Qualification changed')
    return json.loads(raw)

def validate_args(args):
    validate_request(args)
    if (args.seconds!=90 or args.movie_id!=3391 or args.expected_title!='Saving Private Ryan'
        or args.seek_seconds!=1200 or args.subtitles_off is not True or args.planar_flag!=1
        or args.binary_sha256!=CANDIDATE):raise ValueError('Wrong short matched scene/candidate')
    normalized=[]
    for flag,path in enumerate(config_paths(args)):
        validate_configs([path],1,selected_flags=(1,))
        lines=path.read_text().splitlines();marker=f'Environment=DVBRIDGE_BASE_QSV={flag}'
        if lines.count(marker)!=1 or sum(line.startswith('Environment=DVBRIDGE_BASE_QSV=') for line in lines)!=1:
            raise ValueError('Wrong BL route selection')
        normalized.append([line for line in lines if line!=marker])
    if normalized[0]!=normalized[1]:raise ValueError('More than BL selection differs')
    capture=pinned_json(ROOT/'candidate-handoff-qsv-on-one1-capture-private.json',
        '2de96c7a0fdc4c40e6953be13556d0a2b4fdbc1673ae0b027d5ce2e9a181f66c')
    if capture['identity_before']['binary_sha256']!=CANDIDATE or capture['identity_before']!=capture['identity_after']:
        raise ValueError('Candidate capture identity mismatch')
    proof=pinned_json(ROOT/'candidate-handoff-on-compare1-private.json',
        '4436577d539fdcda6e019c8182473272d03387859dac707d61ec1e041b2b5382')
    for key in ('pass','source_timestamps_equal','source_metadata_equal','canonical_whole_rgb_equal',
        'canonical_payload_equal','crc_and_repetitions_valid','capture_and_report_unchanged',
        'reference_matches_existing_qualified_canonical_record'):
        if proof.get(key) is not True:raise ValueError('Picture qualification incomplete')
    return {'method':proof['method'],'scope':'One matched frame, not full-film conformance'}

def make_validator(planar):
    original=None
    def validate(report,stopped,enabled,binary_hash):
        nonlocal original
        if any(report.get(key)!=value for key,value in dict(movie_id=3391,media='Saving Private Ryan',
            requested_seconds=90,seek_seconds=1200,expected_route='fp32').items()):
            raise ValueError('Wrong source scene/duration')
        validate_fixture(report.get('subtitle_fixture'),3391)
        state=report['subtitle_fixture']['before']
        if original is not None and state!=original:raise ValueError('Subtitle state changed between cases')
        result=validate_planar_report(report,stopped,planar,binary_hash)
        result['EL_decoder']=qualify_actual_el_use(report['selected_log_lines'],1)
        result['other_native_optimizations']=qualify_actual_use(report['selected_log_lines'],'batched_planes',0)
        cpu=result['whole_process_cpu']['elapsed_seconds']
        if report['elapsed_seconds']<90 or not math.isfinite(cpu) or cpu<75:raise ValueError('Short CPU interval')
        covered=sum(row['elapsed_seconds'] for row in report['gpu_intervals'] if 'unavailable' not in row)
        if covered<75:raise ValueError('Short GPU coverage')
        for row in report['gpu_intervals']:
            if 'unavailable' in row:continue
            if not row['engine_busy_percent'] or any(not math.isfinite(x) or x<0 for x in row['engine_busy_percent'].values()):
                raise ValueError('Invalid GPU counters')
        rows=[tuple(map(int,m)) for line in report['selected_log_lines']
            for m in re.findall(r'DVBridge BL QSV: decoder=hevc_qsv metadata=1 mapped=(\d+) generation=(\d+)',line)]
        if enabled and (len(rows)<2 or any(min(row)<=0 for row in rows)
            or len({row[1] for row in rows})!=1 or rows[-1][0]-rows[0][0]<240):
            raise ValueError('Missing sustained mapped BL QSV evidence')
        if not enabled and any('DVBridge BL QSV:' in line for line in report['route_log_lines']+report['selected_log_lines']):
            raise ValueError('QSV BL work occurred in control')
        result['BL_QSV']={'enabled':enabled,'mapped_interval':rows[-1][0]-rows[0][0] if rows else 0}
        original=dict(state)
        return result
    return validate
