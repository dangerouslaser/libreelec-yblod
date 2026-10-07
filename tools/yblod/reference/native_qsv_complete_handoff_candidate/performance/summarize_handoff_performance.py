"""Emit only scalar metrics from the four owned short-scene reports."""
import json
import re
from pathlib import Path
ROOT=Path('/storage/yblod-qsv-el-aff416-runtime')
reports=ROOT/'candidate-handoff-performance1-reports-private'
result=json.loads((ROOT/'candidate-handoff-performance1-private.json').read_text())
assert result.get('pass') is True and result.get('restored_idle') is True
cases=[]
for order,flag in enumerate((0,1,1,0),1):
    label=f'el-qsv-canonical-planar1-{order}-flag{flag}'
    report=json.loads((reports/(label+'.json')).read_text())
    qual=json.loads((reports/(label+'.qualification.json')).read_text())
    intervals=[row for row in report['gpu_intervals'] if 'unavailable' not in row]
    elapsed=sum(row['elapsed_seconds'] for row in intervals)
    engines=set.intersection(*(set(row['engine_busy_percent']) for row in intervals))
    gpu={name:sum(row['elapsed_seconds']*row['engine_busy_percent'][name] for row in intervals)/elapsed for name in sorted(engines)}
    memory=[]
    for row in report['memory_samples']:
        fields=dict(line.split('=',1) for line in row['service'].splitlines() if '=' in line)
        memory.append(int(fields['MemoryCurrent']))
    health=[dict(re.findall(r'([A-Za-z_][A-Za-z_0-9]*)=([^\s]+)',line))
        for line in report['selected_log_lines'] if 'DVBridge playback health:' in line]
    cases.append({'order':order,'bl_qsv':flag,'cpu_percent_one_core':qual['whole_process_cpu']['average_percent_of_one_cpu'],
        'gpu_percent_capacity_normalized':gpu,'gpu_covered_seconds':elapsed,
        'maximum_sampled_kodi_memory_bytes':max(memory),'health':health,
        'BL_route':qual['BL_QSV'],'EL_route':qual['EL_decoder'],
        'failure_marker':report['failure_marker']})
print(json.dumps({'pass':True,'cases':cases,'scope':'Four matched 90-second scenes; not full-film/display conformance'},sort_keys=True))
