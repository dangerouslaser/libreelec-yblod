"""Compare private fingerprints; emit no content fingerprints or private paths."""
import re

PTS = (1210000000, 1220010000, 1230020000)
METHOD = 'SHA256 equality of complete oriented RGB after validated transport-ID/CRC normalization'


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def validate(record, enabled, binary, code_hashes):
    require(record.get('pass') is True, 'Successful owned fingerprint run required')
    require(record.get('expected_binary_sha256') == binary, 'Wrong capture binary')
    require(type(record.get('expected_el_qsv')) is int and record['expected_el_qsv'] == enabled,
            'Wrong decoder selection')
    for key in ('code_closure_verified', 'capture_binary_and_frame_association_verified'):
        require(record.get(key) is True, 'Source/code association missing')
    hashes = record.get('code_sha256')
    require(isinstance(hashes, list) and len(hashes) == 4 and
            all(sha(x) for x in hashes) and sorted(hashes) == sorted(code_hashes),
            'Wrong exact code closure')
    r = record.get('resources', {})
    for key, value in (('memory_limit_bytes', 536870912), ('swap_limit_bytes', 0),
                       ('swap_current_bytes', 0), ('swap_peak_bytes', 0)):
        require(type(r.get(key)) is int and r[key] == value, 'Resource limit/evidence differs')
    require(type(r.get('peak_memory_bytes')) is int and 0 < r['peak_memory_bytes'] <= 536870912,
            'Measured bounded peak required')
    require(type(r.get('cpu_limit')) in (int, float) and 0 < r['cpu_limit'] <= 1,
            'Bounded CPU required')
    events = r.get('memory_events')
    require(isinstance(events, dict) and {'low', 'high', 'max', 'oom', 'oom_kill'} <= set(events)
            and all(type(x) is int and x == 0 for x in events.values()), 'Memory events must be zero')
    frames = record.get('frames')
    require(isinstance(frames, list) and len(frames) == 3, 'Three frame records required')
    previous = 0
    for frame, pts in zip(frames, PTS):
        require(frame.get('schema') == 'yblod.canonical-tunnel-fingerprint.v1', 'Wrong fingerprint schema')
        for key in ('pts', 'el_pts'):
            require(type(frame.get(key)) is int and frame[key] == pts, 'Exact source timestamp required')
        for key in ('crc_and_repetitions_valid', 'orientation_unambiguous', 'capture_stat_identity_unchanged'):
            require(frame.get(key) is True, 'Valid immutable oriented capture required')
        for key in ('source_metadata_sha256', 'canonical_rgb_sha256', 'canonical_packets_sha256'):
            require(sha(frame.get(key)), 'Missing full fingerprint')
        require(type(frame.get('packet_count')) is int and 1 <= frame['packet_count'] <= 4,
                'Invalid packet count')
        route = frame.get('route', {})
        for key, value in dict(native=1, native_planar=1, direct_packed=1, batched_planes=0,
                               immutable_instructions=0, el_decoder_qsv=enabled,
                               el_qsv_native_used=enabled).items():
            require(type(route.get(key)) is int and route[key] == value, 'Wrong actual capture route')
        sequence = route.get('el_qsv_map_sequence')
        require(type(sequence) is int and (previous < sequence < 2**63 if enabled else sequence == 0),
                'Invalid mapped frame sequence')
        previous = sequence
    return frames


def compare(before, after, binary_sha256, code_hashes):
    require(sha(binary_sha256), 'Explicit candidate binary required')
    require(len(code_hashes) == 4 and len(set(code_hashes)) == 4 and all(sha(x) for x in code_hashes),
            'Four independently pinned source hashes required')
    old = validate(before, 0, binary_sha256, code_hashes)
    new = validate(after, 1, binary_sha256, code_hashes)
    for a, b in zip(old, new):
        for key in ('source_metadata_sha256', 'canonical_rgb_sha256', 'canonical_packets_sha256', 'packet_count'):
            require(a[key] == b[key], 'Source metadata, complete picture or payload differs')
    return dict(schema='yblod.canonical-tunnel-comparison.v1', passed=True,
                candidate_binary_sha256=binary_sha256, frame_count=3,
                source_timestamps_equal=True, source_metadata_fingerprints_equal=True,
                complete_canonical_rgb_fingerprints_equal=True, canonical_packet_fingerprints_equal=True,
                method=METHOD, literal_pairwise_byte_comparison=False,
                scope='Three batch0 EL-only frames. No numeric error estimate, BL-QSV, display or performance claim.')
