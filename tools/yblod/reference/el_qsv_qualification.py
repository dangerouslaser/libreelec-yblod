"""Fail-closed EL-only QSV accuracy gates. No tolerance or BL-QSV claim."""
import json
import re


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def route(info, enabled, planar, legacy=False):
    wanted = dict(native=1, direct_packed=1, native_planar=planar, qsv_mode=1,
                  batched_planes=0, immutable_instructions=0)
    if not legacy:
        wanted.update(el_decoder_qsv=enabled, el_qsv_native_used=enabled)
    if not isinstance(info, dict) or any(type(info.get(key)) is not int or
                                           info[key] != value for key, value in wanted.items()):
        raise ValueError('Actual matching native EL decoder route required')
    if not legacy:
        sequence = info.get('el_qsv_map_sequence')
        if (not integer(sequence) or sequence > 2**63-1 or
                (enabled and sequence == 0) or (not enabled and sequence != 0)):
            raise ValueError('Missing or unexpected genuinely mapped EL sequence')
    elif any(key in info and (type(info[key]) is not int or info[key] != 0)
             for key in ('el_decoder_qsv', 'el_qsv_native_used', 'el_qsv_map_sequence')):
        raise ValueError('Unexpected EL-QSV proof in the retained legacy control')


def raw_enhancement(record, pts):
    if not isinstance(record, dict) or any(record.get(key) is not True for key in
            ('source_identity_verified', 'target_identity_verified', 'active_geometry_equal', 'chroma_location_equal',
             'colour_properties_equal', 'original_timestamps_equal')):
        raise ValueError('Raw EL source/geometry/chroma/colour/PTS parity required')
    expected = dict(format='P010', code_bit_depth=10, active_width=1920, active_height=1080,
                    before_pts_microseconds=pts, after_pts_microseconds=pts)
    for key, value in expected.items():
        if record.get(key) != value or (type(value) is int and type(record.get(key)) is not int):
            raise ValueError('Raw EL must identify the same active ten-bit source frame')
    planes = record.get('planes')
    counts = dict(Y=1920*1080, U=960*540, V=960*540)
    if not isinstance(planes, dict) or set(planes) != set(counts):
        raise ValueError('All three raw EL planes required')
    for plane, count in counts.items():
        item = planes[plane]
        if not isinstance(item, dict) or item.get('p010_low_bits_zero') is not True or any(type(item.get(key)) is not int or item[key] != value
                for key, value in dict(sample_count=count, differing_samples=0,
                                      differing_storage_samples=0, maximum_absolute_sample_codes=0).items()):
            raise ValueError('No raw EL sample tolerance is accepted')


def frames(records, baseline_hash, candidate_hash, planar, qsv_compare):
    if not isinstance(records, list) or not 3 <= len(records) <= 16:
        raise ValueError('At least three separately matched source frames required')
    timestamps, sequences = [], []
    for frame in records:
        if not isinstance(frame, dict) or any(frame.get(key) is not True for key in
                ('source_identity_verified', 'source_timestamps_equal', 'source_metadata_equal',
                 'picture_and_payload_preserved', 'transport_crc_valid',
                 'only_transport_id_crc_variation', 'metadata_uses_enhancement_residual')):
            raise ValueError('Exact source/picture/payload/CRC and FEL metadata proof required')
        for key, expected in (('maximum_absolute_12bit_codes', 0), ('exact_picture_percent', 100)):
            planes = frame.get(key)
            if not isinstance(planes, dict) or set(planes) != {'I', 'P', 'T'} or any(
                    type(value) not in (int, float) or value != expected for value in planes.values()):
                raise ValueError('No reconstructed picture tolerance is accepted')
        times = []
        for phase in ('before', 'after'):
            item = frame.get(phase)
            expected_hash = candidate_hash if qsv_compare or phase == 'after' else baseline_hash
            if not isinstance(item, dict) or item.get('binary_sha256') != expected_hash:
                raise ValueError('Frame association has the wrong binary')
            enabled = int(qsv_compare and phase == 'after')
            route(item.get('route'), enabled, planar, legacy=not qsv_compare and phase == 'before')
            for key in ('pts_microseconds', 'el_pts_microseconds'):
                value = item.get(key)
                if not integer(value, 1200000001) or value > 1380000000:
                    raise ValueError('SPR matched source frame must be in the qualified scene')
                times.append(value)
            if qsv_compare and phase == 'after':
                sequences.append(item['route']['el_qsv_map_sequence'])
        if len(set(times)) != 1:
            raise ValueError('BL/EL source association is not exact')
        timestamps.append(times[0])
        if qsv_compare:
            raw_enhancement(frame.get('raw_enhancement'), times[0])
    if timestamps != sorted(set(timestamps)) or (qsv_compare and sequences != sorted(set(sequences))):
        raise ValueError('Distinct increasing frame times and mapped sequences required')
    return timestamps


def qualify_document(report, baseline_hash, candidate_hash, planar):
    if (any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value)
            for value in (baseline_hash, candidate_hash)) or baseline_hash == candidate_hash or
            type(planar) is not int or planar not in (0, 1)):
        raise ValueError('Distinct retained/candidate binaries and explicit planar flag required')
    expected = dict(schema='yblod.el-qsv-frame-qualification.v1',
                    baseline_binary_sha256=baseline_hash, candidate_binary_sha256=candidate_hash,
                    movie_id=3391, content='Saving Private Ryan', seek_seconds=1200,
                    planar_flag=planar)
    if not isinstance(report, dict) or any(report.get(key) != value or
            (type(value) is int and type(report.get(key)) is not int) for key, value in expected.items()):
        raise ValueError('Qualification must match binaries, route and SPR scene')
    if report.get('same_candidate_runtime_verified') is not True:
        raise ValueError('Same candidate runtime must be verified for the API comparison')
    if report.get('target_identity_verified') is not True:
        raise ValueError('Actual capture host/GPU and raw probe target identity required')
    old_times = frames(report.get('retained_to_new_runtime_qsv_off'), baseline_hash,
                       candidate_hash, planar, False)
    qsv_times = frames(report.get('same_candidate_qsv_off_to_on'), baseline_hash,
                       candidate_hash, planar, True)
    if old_times != qsv_times:
        raise ValueError('Runtime-preservation and API tests must use the same source frames')
    return dict(candidate_binary_sha256=candidate_hash, baseline_binary_sha256=baseline_hash,
                frame_count=len(qsv_times), retained_runtime_output_preserved=True,
                same_candidate_qsv_output_preserved=True, raw_active_EL_samples_equal=True,
                actual_native_EL_route_verified=True, planar_flag=planar,
                metadata_enables_FEL_residual=True,
                scope='Profile7 SPR EL-only; BL remains existing VAAPI/native HEVC decoder. '
                      'Hardware QSV depth1, not standalone FFmpeg depth4. No pixel tolerance.')


def qualify_report(path, baseline_hash, candidate_hash, planar):
    return qualify_document(json.loads(path.read_text()), baseline_hash, candidate_hash, planar)
