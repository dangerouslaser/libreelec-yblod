"""Independent decoder and renderer operation gates, not paired/native equality."""
import re
from run_colour_import_matrix import fields


def counters(row, keys):
    if any(not re.fullmatch('[0-9]+', row.get(key, '')) for key in keys):
        raise ValueError('Missing or malformed EL-QSV operation counter')
    return {key: int(row[key]) for key in keys}


def progress(rows, keys, minimum=240):
    if len(rows) < 2:
        raise ValueError('Substantial steady operation interval required')
    values = [counters(row, keys) for row in rows]
    if any(b[key] < a[key] for a, b in zip(values, values[1:]) for key in keys):
        raise ValueError('Operation counters reset or regressed')
    delta = {key: values[-1][key]-values[0][key] for key in keys}
    return values, delta


def qualify_actual_el_use(lines, enabled):
    if type(enabled) is not int or enabled not in (0, 1):
        raise ValueError('Explicit EL decoder0/1 required')
    decoder = [fields(line) for line in lines if 'DV FEL decoder:' in line]
    if any(row.get('qsv_selected') != str(enabled) for row in decoder):
        raise ValueError('Actual EL decoder selection differs from request')
    decoded, decoder_delta = progress(decoder, ('qsv_mapped_frames', 'paired_frames'))
    if decoder_delta['paired_frames'] < 240:
        raise ValueError('Insufficient exact EL pairs')
    if enabled:
        if (decoder_delta['qsv_mapped_frames'] < 240 or
                any(row['qsv_mapped_frames'] < row['paired_frames'] for row in decoded)):
            raise ValueError('Successful QSV maps and exact pairs were not demonstrated')
    elif any(row['qsv_mapped_frames'] for row in decoded):
        raise ValueError('Unexpected QSV mapping in VAAPI control')
    renderer = [fields(line) for line in lines if 'DVBridge renderer summary:' in line]
    rendered, renderer_delta = progress(renderer, ('prepared', 'el_qsv_prepared', 'el_qsv_native_used'))
    if (renderer_delta['prepared'] < 240 or
            any(row['el_qsv_native_used'] > row['el_qsv_prepared'] or
                row['el_qsv_prepared'] > row['prepared'] for row in rendered)):
        raise ValueError('Invalid or insufficient current-frame native EL input operations')
    if (renderer_delta['el_qsv_prepared'] != enabled*renderer_delta['prepared'] or
            renderer_delta['el_qsv_native_used'] != enabled*renderer_delta['prepared'] or
            (not enabled and any(row['el_qsv_prepared'] or row['el_qsv_native_used'] for row in rendered))):
        raise ValueError('Current QSV EL input did not exclusively reach successful native preparation')
    return dict(selected_EL_decoder_qsv=enabled, actual_EL_use_verified=True,
                decoder_interval_deltas=decoder_delta, renderer_interval_deltas=renderer_delta,
                decoder_observations=len(decoder), renderer_observations=len(renderer),
                scope='Independent operation intervals: do not equate paired/native counts or call them HDMI frames. '
                      'Native-used means supplied current mapped EL; accuracy proof separately requires FEL residual metadata.')
