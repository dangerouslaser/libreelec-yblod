"""Strict same-candidate, same-planar-route qualification for isolated options."""
import json
import re

OPTIONS = ('batched_planes', 'immutable_instructions')


def qualify_frames(path, binary_hash, option):
    report = json.loads(path.read_text())
    if (option not in OPTIONS or not re.fullmatch(r'[a-f0-9]{64}', binary_hash) or
            report.get('schema') != 'yblod.native-optimization-frame-results.v1' or
            report.get('binary_sha256') != binary_hash or report.get('optimization') != option or
            report.get('content') != 'Saving Private Ryan' or
            type(report.get('movie_id')) is not int or report['movie_id'] != 3391 or
            type(report.get('seek_seconds')) is not int or report['seek_seconds'] != 1200):
        raise ValueError('Frame proof must match candidate, isolated option and SPR scene')
    frames = report.get('frames')
    if not isinstance(frames, list) or not 3 <= len(frames) <= 16:
        raise ValueError('At least three exact matched frames required')
    times = []
    for frame in frames:
        if (not isinstance(frame, dict) or
                any(frame.get(key) is not True for key in
                    ('source_timestamps_equal', 'source_metadata_equal', 'picture_and_payload_preserved'))):
            raise ValueError('Identical source and exact picture/payload preservation required')
        for key, value in (('maximum_absolute_12bit_codes', 0), ('exact_picture_percent', 100)):
            planes = frame.get(key)
            if (not isinstance(planes, dict) or set(planes) != {'I', 'P', 'T'} or
                    any(type(item) not in (int, float) or item != value for item in planes.values())):
                raise ValueError('No picture tolerance is accepted')
        source_times = []
        for phase, enabled in (('before', 0), ('after', 1)):
            record = frame.get(phase)
            route = record.get('route') if isinstance(record, dict) else None
            wanted = dict(native=1, direct_packed=1, native_planar=1, qsv_mode=1,
                          batched_planes=0, immutable_instructions=0)
            wanted[option] = enabled
            if not isinstance(route, dict) or any(type(route.get(key)) is not int or
                    route[key] != value for key, value in wanted.items()):
                raise ValueError('Actual isolated-option native packed planar route is required')
            for key in ('pts_microseconds', 'el_pts_microseconds'):
                timestamp = record.get(key)
                if type(timestamp) is not int or timestamp <= 1200*1000000:
                    raise ValueError('Invalid source timestamp')
                source_times.append(timestamp)
        if len(set(source_times)) != 1:
            raise ValueError('Source layers or comparison timestamps differ')
        times.append(source_times[0])
    if times != sorted(set(times)):
        raise ValueError('Distinct increasing matched source frames required')
    return dict(binary_sha256=binary_hash, optimization=option, frame_count=len(frames),
                picture_and_payload_preserved=True, source_metadata_and_timestamps_equal=True,
                maximum_absolute_12bit_codes={'I': 0, 'P': 0, 'T': 0},
                native_packed_planar_both=True, other_optimization_disabled=True)
