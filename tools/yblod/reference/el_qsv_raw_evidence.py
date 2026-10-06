"""Translate measured raw EL scalars; never perform or invent identity checks.

identity must be supplied by a reviewed on-target controller which independently
checks actual executable/libraries, private input and physical DRM device before
and after probing. Arbitrary JSON assertions are not empirical verification.
"""


def translate(probe, identity, capture_pts):
    checks = ('target_host_matches_capture_host', 'physical_gpu_matches_capture_gpu',
              'probe_executable_identity_verified', 'candidate_runtime_identity_verified',
              'private_input_identity_verified', 'identities_unchanged_before_after',
              'resource_limits_verified')
    if not isinstance(identity, dict) or any(identity.get(k) is not True for k in checks):
        raise ValueError('Independent on-target identity/resource observations required')
    if (not isinstance(capture_pts, list) or len(capture_pts) != 3 or
            any(type(p) is not int or p <= 0 for p in capture_pts) or
            capture_pts != sorted(set(capture_pts))):
        raise ValueError('Three exact increasing capture timestamps required')
    required = ('pass', 'input_stat_identity_unchanged', 'expected_sdk_libvpl_loaded',
                'expected_sdk_implementation_loaded', 'expected_sdk_va_driver_loaded')
    if not isinstance(probe, dict) or any(probe.get(k) is not True for k in required):
        raise ValueError('Successful actual SDK probe required')
    mapped = probe.get('qsv_mapped_frames')
    records = probe.get('frames')
    if type(mapped) is not int or mapped < 3 or not isinstance(records, list) or len(records) != 3:
        raise ValueError('Actual mapped frames and three measured comparisons required')
    output = []
    counts = dict(Y=2073600, U=518400, V=518400)
    props = ('properties_equal', 'active_geometry_equal', 'chroma_location_equal',
             'colour_properties_equal', 'original_timestamps_equal')
    for frame, pts in zip(records, capture_pts):
        if not isinstance(frame, dict) or any(frame.get(k) is not True for k in props):
            raise ValueError('Actual frame property parity required')
        expected = dict(requested_pts_microseconds=pts, format='P010', code_bit_depth=10,
                        active_width=1920, active_height=1080)
        for key, value in expected.items():
            if frame.get(key) != value or (type(value) is int and type(frame.get(key)) is not int):
                raise ValueError('Raw probe must match the exact captured source frame')
        for phase in ('before', 'after'):
            item = frame.get(phase)
            if not isinstance(item, dict) or type(item.get('pts_microseconds')) is not int or item['pts_microseconds'] != pts:
                raise ValueError('Original output timestamps must match capture exactly')
        planes = frame.get('planes')
        if not isinstance(planes, list) or len(planes) != 3:
            raise ValueError('Three literal measured planes required')
        result = {}
        for item in planes:
            if not isinstance(item, dict) or item.get('plane') not in counts or item['plane'] in result:
                raise ValueError('Unique Y/U/V planes required')
            for key, value in dict(sample_count=counts[item['plane']], differing_samples=0,
                                   maximum_absolute_sample_codes=0).items():
                if type(item.get(key)) is not int or item[key] != value:
                    raise ValueError('No sample or storage tolerance accepted')
            if item.get('p010_low_bits_zero') is not True:
                raise ValueError('Exact P010 storage representation required')
            result[item['plane']] = {k: item[k] for k in
                ('sample_count', 'differing_samples', 'maximum_absolute_sample_codes', 'p010_low_bits_zero')}
            # Probe differing_samples counts literal uint16 differences, not a
            # normalized-code estimate: copy that actual measurement explicitly.
            result[item['plane']]['differing_storage_samples'] = item['differing_samples']
        output.append(dict(source_identity_verified=True, target_identity_verified=True,
            active_geometry_equal=True, chroma_location_equal=True, colour_properties_equal=True,
            original_timestamps_equal=True, format='P010', code_bit_depth=10,
            active_width=1920, active_height=1080, before_pts_microseconds=pts,
            after_pts_microseconds=pts, planes=result))
    return output
