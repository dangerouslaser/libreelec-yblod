"""Actual successful-use gates; requested environment is not execution proof."""
from native_optimization_qualification import OPTIONS
from run_colour_import_matrix import fields

COUNTERS = ('accepted_fp32', 'batched_plane_imports', 'batched_plane_releases',
            'immutable_accepted_frames', 'immutable_metadata_uploads',
            'immutable_range_bindings', 'immutable_dispatches')


def qualify_actual_use(lines, option, enabled):
    if option not in OPTIONS or type(enabled) is not int or enabled not in (0, 1):
        raise ValueError('Invalid isolated optimization request')
    rows = [fields(line) for line in lines if 'DVBridge native composer:' in line]
    if len(rows) < 2:
        raise ValueError('Substantial actual optimization-use evidence required')
    counts = []
    for row in rows:
        wanted = dict(optimization_stats_valid=1, batched_planes_selected=0,
                      immutable_instructions_selected=0)
        wanted[option+'_selected'] = enabled
        if any(row.get(key) != str(value) for key, value in wanted.items()):
            raise ValueError('Invalid or unexpected actual selected optimization')
        if any(key not in row or not str(row[key]).isdigit() for key in COUNTERS):
            raise ValueError('Missing or invalid actual-use counter')
        value = {key: int(row[key]) for key in COUNTERS}
        if counts and any(value[key] < counts[-1][key] for key in COUNTERS):
            raise ValueError('Actual-use counters reset or regressed')
        counts.append(value)
    delta = {key: counts[-1][key]-counts[0][key] for key in COUNTERS}
    accepted = delta['accepted_fp32']
    if accepted < 240 or delta['immutable_accepted_frames'] != accepted:
        raise ValueError('Insufficient or inconsistent actual FP32 operations')
    batch = enabled if option == 'batched_planes' else 0
    immutable = enabled if option == 'immutable_instructions' else 0
    if (delta['batched_plane_imports'] != batch*accepted or
            delta['batched_plane_releases'] != batch*accepted or
            (not batch and any(row['batched_plane_imports'] or row['batched_plane_releases'] for row in counts))):
        raise ValueError('Successful batched import/release operations did not match selection')
    if (delta['immutable_metadata_uploads'] != (1 if immutable else 3)*accepted or
            delta['immutable_range_bindings'] != 3*immutable*accepted or
            delta['immutable_dispatches'] != 3*accepted or
            (not immutable and any(row['immutable_range_bindings'] for row in counts))):
        raise ValueError('Actual instruction uploads/bindings/dispatches did not match selection')
    return dict(optimization=option, selected=enabled, other_optimization_selected=0,
                successful_operation_deltas=delta, observations=len(rows),
                actual_use_verified=True,
                scope='Successful frame operations between composer summaries, not unique HDMI frames.')
