"""Matched retained release renderer versus current native FP32/LUT playback."""
from run_colour_import_matrix import (fields, identity, parser, process_cpu_summary,
    run_configured_matrix, validate_request)
from run_nlq_playback_matrix import validate_lut_report


def legacy_route(lines):
    if any('DVBridge native composer:' in line or
           'DVBridge native reconstruction:' in line for line in lines):
        raise ValueError('Native work occurred in the legacy control')
    if any('Quick Sync scaling unavailable' in line or 'DVBridge renderer: stage=' in line
           for line in lines):
        raise ValueError('Legacy scaling or rendering failed')
    if not any('DVBridge: Quick Sync on the Intel media engine: enhancement layer upscale' in line
               and 'base layer colour' not in line for line in lines):
        raise ValueError('Missing affirmative EL-only media-engine scaling')
    frames = [fields(line) for line in lines if 'DVBridge first frame:' in line]
    if not frames or any(frame.get('fel') not in ('true', '1') or
                         frame.get('enhancement') not in ('true', '1') or
                         frame.get('source') != '3840x2160' or
                         frame.get('output') != '3840x2160' for frame in frames):
        raise ValueError('Missing full-size FEL legacy route')
    summaries = [fields(line) for line in lines if 'DVBridge renderer summary:' in line]
    if not summaries or any(int(row['presentation_failures']) or int(row['stage_failures'])
                            for row in summaries) or int(summaries[-1]['presented']) < 240:
        raise ValueError('Insufficient successful legacy rendering')
    conversions = [fields(line) for line in lines if 'DVBridge conversion:' in line]
    if not conversions:
        raise ValueError('Missing actual colour/output route')
    return {'el_only_media_scaling': True, 'first_frames': frames,
            'last_renderer_summary': summaries[-1], 'conversions': conversions}


def validate_renderer_report(report, stopped, flag, binary_hash):
    if flag:
        return validate_lut_report(report, stopped, 1, binary_hash)
    if (report['failure_marker'] or report['log_rotated_or_truncated'] or
        report['kodi_before'] != report['kodi_after'] or stopped['active_players']):
        raise ValueError('Legacy observer/service/player-stop failure')
    for runtime in (report['runtime_before'], report['runtime_after'], stopped['runtime']):
        if runtime['binary_sha256'] != binary_hash or identity(runtime['service']) != identity(report['kodi_after']):
            raise ValueError('Legacy binary/service changed')
    return {'legacy_route': legacy_route(report['route_log_lines']),
            'whole_process_cpu': process_cpu_summary(report['gpu_samples']),
            'observer_and_player_stop_integrity_passed': True}


def main():
    args = parser().parse_args()
    validate_request(args)
    if args.seconds != 180:
        raise ValueError('Use matched 180-second windows')
    configs = [args.config_dir / f'renderer-{flag}.conf' for flag in (0, 1)]
    normalized = []
    for flag, path in enumerate(configs):
        lines = path.read_text().splitlines()
        marker = f'Environment=DVBRIDGE_NATIVE_RECONSTRUCTION={flag}'
        if lines.count(marker) != 1:
            raise ValueError('Wrong native flag')
        for name in ('DIAGNOSTICS', 'FP32', 'COLOUR_NO_REIMPORT', 'NLQ_LUT'):
            if lines.count(f'Environment=DVBRIDGE_NATIVE_{name}=1') != 1:
                raise ValueError('Missing fixed control')
        normalized.append([line for line in lines if line != marker])
    if normalized[0] != normalized[1]:
        raise ValueError('Configurations differ beyond native reconstruction')
    run_configured_matrix(args, configs, 'renderer',
        lambda flag: 'native-fp32-lut' if flag else 'retained-release-el-only-qsv',
        validate_renderer_report, lambda flag: 'fp32' if flag else 'legacy')


if __name__ == '__main__':
    main()
