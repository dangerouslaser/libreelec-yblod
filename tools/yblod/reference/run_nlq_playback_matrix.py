"""Opt-in LUT ABBA playback; shared lifecycle, no forced recovery."""
from run_colour_import_matrix import (fields, parser, validate_request,
    validate_report, run_configured_matrix)


def lut_summary(lines, flag):
    """Strict schema must match the candidate's actual runtime counters."""
    entries = [fields(line) for line in lines if 'DVBridge native composer:' in line]
    required = {'nlq_lut_enabled', 'accepted_lut', 'accepted_fp32', 'accepted_integer',
                'nlq_builds', 'nlq_uploads', 'nlq_cache_hits', 'nlq_shader_compiles',
                'shader_compile_failed', 'generate_failed', 'fp32_selected'}
    if not entries:
        raise ValueError('Missing actual NLQ lookup route evidence')
    previous = None
    for entry in entries:
        if not required.issubset(entry):
            raise ValueError('Incomplete lookup counter schema')
        counts = {k: int(entry[k]) for k in required}
        if any(v < 0 for v in counts.values()):
            raise ValueError('Negative lookup counter')
        if (counts['nlq_lut_enabled'] != flag or counts['fp32_selected'] != 1 or counts['accepted_integer']
                or counts['shader_compile_failed'] or counts['generate_failed']):
            raise ValueError('Wrong lookup route or failed FP32 work')
        if counts['nlq_builds'] != counts['nlq_uploads']:
            raise ValueError('Lookup build/upload mismatch')
        if flag:
            if (not counts['nlq_shader_compiles'] or not counts['nlq_builds']
                    or counts['accepted_lut'] != counts['accepted_fp32']):
                raise ValueError('Lookup enabled but never compiled/built/uploaded')
        elif any(counts[k] for k in ('nlq_builds','nlq_uploads','nlq_cache_hits','nlq_shader_compiles','accepted_lut')):
            raise ValueError('Lookup work occurred in the disabled control')
        if previous and any(counts[k] < previous[k] for k in required):
            raise ValueError('Lookup counters reset; context qualification required')
        previous = counts
    if len(entries) < 2 or previous['accepted_fp32'] < 240:
        raise ValueError('Insufficient actual lookup reconstruction evidence')
    if flag and previous['nlq_cache_hits'] < 120:
        raise ValueError('No substantial lookup cache reuse')
    return dict(requested_flag=flag, first={k:int(entries[0][k]) for k in required},
                last=previous, observations=len(entries),
                scope='Per-native-context cumulative counts, not unique HDMI frames.')


def validate_lut_report(report, stopped, flag, binary_hash):
    # Both conditions use FP32 and the already qualified metadata-only handoff.
    result = validate_report(report, stopped, 1, binary_hash)
    result['nlq_lut'] = lut_summary(report['selected_log_lines'], flag)
    result['timing_scope'] = ('Cumulative helper averages are not per-frame tails or '
                             'percentiles; GPU client busy is not exclusive kernel time.')
    return result


def validate_lut_args(args):
    validate_request(args)
    if args.seconds not in (180, 300):
        raise ValueError('Playback qualification must be 180 or 300 seconds')
    normalized=[]
    for flag in (0, 1):
        config=(args.config_dir/f'nlq-lut-{flag}.conf').read_text()
        marker=f'Environment=DVBRIDGE_NATIVE_NLQ_LUT={flag}'
        lines=config.splitlines()
        if lines.count(marker)!=1:
            raise ValueError('Missing or repeated LUT flag')
        for name in ('RECONSTRUCTION','DIAGNOSTICS','FP32','COLOUR_NO_REIMPORT'):
            if lines.count(f'Environment=DVBRIDGE_NATIVE_{name}=1')!=1:
                raise ValueError('Both cases require FP32, diagnostics and no reimport')
        normalized.append('\n'.join(line for line in lines if line!=marker))
    if normalized[0]!=normalized[1]:
        raise ValueError('Configs differ beyond the opt-in LUT flag')


def main():
    args=parser().parse_args()
    validate_lut_args(args)
    run_configured_matrix(args,[args.config_dir/f'nlq-lut-{f}.conf' for f in (0,1)],
        'nlq-playback',lambda flag:f'fp32=1 no_reimport=1 nlq_lut={flag}',validate_lut_report)


if __name__=='__main__':
    main()
