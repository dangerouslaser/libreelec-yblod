"""Read finalized four-case EL API reports; emit scalar-only weighted results."""
import argparse
import json
import math
from pathlib import Path
from observe_el_qsv_active_movie import verify_measured_generation
from observe_subtitle_fixture import validate_fixture
from run_el_qsv_matrix import make_validator
from run_colour_import_matrix import CRASH, NATIVE_FAILURE
from summarize_long_playback import summarize
from summarize_native_packed_matrix import SHUTDOWN, pool, qualify_stage_window, raw_health_summary


def gpu_schema(report,expected=None):
    shape=None;valid=0
    for row in report['gpu_intervals']:
        if 'engine_busy_percent' not in row:continue
        busy=row['engine_busy_percent'];capacity=row.get('capacity')
        elapsed=row.get('elapsed_seconds')
        if not isinstance(busy,dict) or not busy or not isinstance(capacity,dict) or set(busy)!=set(capacity):raise ValueError('Missing engine/capacity')
        if isinstance(elapsed,bool) or not isinstance(elapsed,(int,float)) or not math.isfinite(elapsed) or elapsed<=0:raise ValueError('Invalid GPU duration')
        if any(type(value) is not int or value<=0 for value in capacity.values()):raise ValueError('Invalid GPU capacity')
        if any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 for value in busy.values()):raise ValueError('Invalid GPU busy')
        if shape is None:shape=capacity
        if capacity!=shape or (expected is not None and capacity!=expected):raise ValueError('GPU schema changed')
        valid+=1
    if valid<2:raise ValueError('Missing GPU intervals')
    return shape


def case_admission(raw,saved,stem):
    if raw.get('label')!=stem or saved.get('actual_isolated_runtime_verified') is not True:
        raise ValueError('Wrong case or missing actual runtime admission')


def aggregate(root, binary):
    cases=[];original=None;engine_schema=None;validate=make_validator(1)
    for order,flag in enumerate((0,1,1,0),1):
        stem=f'el-qsv-canonical-planar1-{order}-flag{flag}'
        raw=json.loads((root/(stem+'.json')).read_text())
        if (raw['label']!=stem or raw['movie_id']!=3391 or raw['media']!='Saving Private Ryan' or
                raw['seek_seconds']!=1200 or raw['requested_seconds']!=180 or raw['elapsed_seconds']<180):
            raise ValueError('Incomplete or wrong source observation')
        verify_measured_generation(raw,binary)
        fixture=raw['subtitle_fixture'];validate_fixture(fixture,3391)
        state={key:fixture['before'].get(key) for key in ('enabled','index')}
        if original is None:original=state
        if original!=state:raise ValueError('Original subtitle state differs')
        stopped=json.loads((root/(stem+'.json.stop.json')).read_text())
        qualified=validate(raw,stopped,flag,binary)
        saved=json.loads((root/(stem+'.qualification.json')).read_text())
        case_admission(raw,saved,stem)
        shutdown=json.loads((root/(stem+'.shutdown.json')).read_text())
        journal=(root/(stem+'.journal.log')).read_text();kodi=(root/(stem+'.kodi.log')).read_text()
        if shutdown!=SHUTDOWN or 'Deactivated successfully' not in journal or CRASH.search(journal) or NATIVE_FAILURE.search(kodi):
            raise ValueError('Failed process lifecycle')
        if 'DVBridge output capture:' in kodi or 'DVBridge capture pair:' in kodi:raise ValueError('Readback during measurement')
        engine_schema=gpu_schema(raw,engine_schema)
        summary=summarize(raw);gpu=summary['gpu_counter_intervals'];health=summary['health']
        if qualified['whole_process_cpu']['elapsed_seconds']<150 or gpu['duration_seconds']<150 or not health or not health['counter_window_valid'] or health['source_seconds']<150:
            raise ValueError('Insufficient measurement')
        memory=summary['memory_snapshots']
        peaks=[value['MemoryPeak'] for value in memory.values() if 'MemoryPeak' in value]
        for sample in raw.get('memory_samples',[]):
            service=dict(line.split('=',1) for line in sample['service'].splitlines() if '=' in line)
            if service.get('MemoryPeak','').isdigit():peaks.append(int(service['MemoryPeak']))
        if not peaks:raise ValueError('Missing whole-service RAM')
        cases.append(dict(order=order,packed_output_flag=flag,el_qsv_flag=flag,qualification=qualified,
            gpu=gpu,health=health,raw_health=raw_health_summary(raw),stage=qualify_stage_window(raw,summary),
            whole_kodi_service_peak_bytes=max(peaks),gpu_engine_capacities=dict(engine_schema),
            process_generation_preserved=True,shutdown=shutdown,
            display_restore_failure_observed='output restoration failed; retaining scanout state' in kodi))
    pooled={flag:pool(cases,flag) for flag in (0,1)}
    for flag in (0,1):
        pooled[flag]['whole_kodi_service_peak_bytes']=max(row['whole_kodi_service_peak_bytes'] for row in cases if row['el_qsv_flag']==flag)
    return dict(schema='yblod.el-qsv-canonical-playback-results.v1',binary_sha256=binary,
        matrix=[0,1,1,0],seconds_per_case=180,movie_id=3391,seek_seconds=1200,
        batched_planes=0,immutable_instructions=0,native_planar=1,capture_outputs=False,
        before=pooled[0],after=pooled[1],cases=[{key:value for key,value in row.items() if key!='packed_output_flag'} for row in cases],original_subtitle_state=original,
        scope='Same candidate and shared runtime; EL decoder API alone differs. Batch0 benchmark is not the retained batch1 configuration. CPU covers every Kodi thread and is normalized to one core; GPU uses client counter intervals and explicit engine capacities. Service RAM is not controller RAM. Normal process exit is not successful DV display restoration.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--binary-sha256',required=True)
    args=parser.parse_args();print(json.dumps(aggregate(args.root,args.binary_sha256),allow_nan=False,indent=2))
