#!/usr/bin/env python3
"""Finite-window BL AU/duration diagnostic; not Kodi/performance qualification."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import time

from observe_live_el_qsv_probe_1536 import observe, resources, stop_owned_child
from target_el_qsv_live_handshake import acknowledge_unit_child, process_record
from run_target_el_qsv_probe import handshake_environment

SCOPE = 'Picture-association.v2: three raw BL frames plus finite-window AU/duration/native metadata; triggering-packet DTS is separately observed, not required equal; not full-film EOF, Kodi, display or performance qualification.'

def validate_three_frame_raw(raw, pts):
    if raw.get('scope') != 'three raw BL frames and independent native HEVC Dolby metadata only; not Kodi or performance':
        raise ValueError('Expected baseline diagnostic schema required')
    if raw.get('pass') is not True or raw.get('packet_clone_identity_verified') is not True or raw.get('submitted_packets_equal') is not True:
        raise ValueError('Literal packet and sample proof required')
    frames = raw.get('frames')
    if not isinstance(frames, list) or len(frames) != 3:
        raise ValueError('Three frames required')
    for frame, expected in zip(frames, pts):
        if type(frame.get('pts_microseconds')) is not int or frame['pts_microseconds'] != expected:
            raise ValueError('Exact source timestamp required')
        for key in ('picture_properties_equal', 'resolved_dolby_metadata_equal', 'raw_rpu_presence_and_bytes_equal', 'sample_comparison_completed'):
            if frame.get(key) is not True:
                raise ValueError('Exact picture and metadata proof required')
        for key in ('reference_raw_rpu_present', 'candidate_raw_rpu_present','legacy_all_properties_equal','transport_pkt_dts_equal'):
            if type(frame.get(key)) is not bool:
                raise ValueError('Typed raw RPU observation required')
        if frame['legacy_all_properties_equal'] != frame['transport_pkt_dts_equal']:
            raise ValueError('Legacy property equality must honestly include transport DTS')
        if frame['reference_raw_rpu_present'] != frame['candidate_raw_rpu_present']:
            raise ValueError('Raw RPU presence must agree')
        planes = frame.get('planes')
        if not isinstance(planes, list) or len(planes) != 3:
            raise ValueError('Three planes required')
        for plane, name, count in zip(planes, 'YUV', (3840*2160, 1920*1080, 1920*1080)):
            if plane.get('plane') != name or type(plane.get('sample_count')) is not int or plane['sample_count'] != count:
                raise ValueError('Exact full-resolution sample extent required')
            for key in ('differing_uint16_samples', 'maximum_absolute_sample_codes'):
                if type(plane.get(key)) is not int or plane[key] != 0:
                    raise ValueError('No sample tolerance allowed')
            if plane.get('p010_low_bits_zero') is not True:
                raise ValueError('P010 sample layout required')

def validate_raw(raw, pts):
    validate_three_frame_raw(raw, pts)
    if set(raw) != {'scope','pass','packet_clone_identity_verified','submitted_packets_equal','frames','decoded_pair_coverage','source_packet_duration','controlled_packet_window','comparison_contract','transport_pkt_dts'}:
        raise ValueError('Exact duration/window-OFF schema required')
    if raw['comparison_contract']!='picture-association.v2':
        raise ValueError('Explicit picture/transport contract required')
    window=raw['controlled_packet_window']; coverage=raw['decoded_pair_coverage']; duration=raw['source_packet_duration']
    if not isinstance(window,dict) or set(window)!={'full_film_eof','accepted_aus','returned_frames','event_count','receive_eof','complete_event_pairs'}:
        raise ValueError('Exact finite window fields required')
    if window['full_film_eof'] is not False or window['complete_event_pairs'] is not True:
        raise ValueError('Finite complete window required')
    count=window['event_count']
    if type(count) is not int or not 3<=count<=4096:
        raise ValueError('Nonvacuous bounded AU events required')
    for key in ('accepted_aus','returned_frames'):
        if not isinstance(window[key],list) or len(window[key])!=2 or any(type(n) is not int or n!=count for n in window[key]):
            raise ValueError('Every admitted AU must return once on both routes')
    if not isinstance(window['receive_eof'],list) or len(window['receive_eof'])!=2 or any(x is not True for x in window['receive_eof']):
        raise ValueError('Both finite windows must reach decoder EOF')
    if not isinstance(coverage,dict) or set(coverage)!={'paired_frames','without_rpu','new_rpu','previous_rpu','multiple_rpu_aus','pending_unpaired_snapshots','previous_reference_validity_scope'}:
        raise ValueError('Exact actual paired instruction coverage required')
    for key in ('paired_frames','without_rpu','new_rpu','previous_rpu','multiple_rpu_aus','pending_unpaired_snapshots'):
        if type(coverage[key]) is not int or not 0<=coverage[key]<=count:
            raise ValueError('Typed bounded instruction counts required')
    if coverage['paired_frames']!=count or coverage['pending_unpaired_snapshots']!=0 or sum(coverage[k] for k in ('without_rpu','new_rpu','previous_rpu'))!=count:
        raise ValueError('All returned instructions must pair; no unresolved snapshot')
    if coverage['previous_reference_validity_scope']!='independent native decoder resolution, not header classifier':
        raise ValueError('Native semantic reference proof required')
    if not isinstance(duration,dict) or set(duration)!={'positive_packets','unknown_zero_packets','returned_frames_bound_to_au_duration'}:
        raise ValueError('Exact source duration coverage required')
    if type(duration['positive_packets']) is not int or not 0<duration['positive_packets']<=count or type(duration['unknown_zero_packets']) is not int or not 0<=duration['unknown_zero_packets']<=count:
        raise ValueError('Actual positive duration observations required')
    if duration['positive_packets']+duration['unknown_zero_packets']!=count or duration['returned_frames_bound_to_au_duration'] is not True:
        raise ValueError('Every AU duration must bind both returned frames')
    d=raw['transport_pkt_dts']
    fields={'qualifies_picture','observed_pairs','equal_pairs','different_pairs','reference_unknown','candidate_unknown','both_unknown','known_pairs','max_absolute_route_delta_us','max_absolute_reference_minus_pts_us','max_absolute_candidate_minus_pts_us'}
    if not isinstance(d,dict) or set(d)!=fields or d['qualifies_picture'] is not False:
        raise ValueError('Explicit nonqualifying transport observations required')
    for key in fields-{'qualifies_picture'}:
        limit=(1<<64)-1 if key.startswith('max_absolute') else count
        if type(d[key]) is not int or not 0<=d[key]<=limit:
            raise ValueError('Typed bounded DTS observations required')
    if d['observed_pairs']!=count or d['equal_pairs']+d['different_pairs']!=count:
        raise ValueError('Every picture must have a transport observation')
    if d['both_unknown']>min(d['reference_unknown'],d['candidate_unknown'],d['equal_pairs']) or d['known_pairs']!=count-d['reference_unknown']-d['candidate_unknown']+d['both_unknown']:
        raise ValueError('Unknown DTS counts must conserve pairs')
    if not d['known_pairs'] and d['max_absolute_route_delta_us']:
        raise ValueError('Unknown timestamps have no numeric route delta')
    if d['equal_pairs']>d['known_pairs']+d['both_unknown'] or d['different_pairs']<d['reference_unknown']+d['candidate_unknown']-2*d['both_unknown']:
        raise ValueError('Unknown timestamp equality must be possible')
    if (d['reference_unknown']==count and d['max_absolute_reference_minus_pts_us']) or (d['candidate_unknown']==count and d['max_absolute_candidate_minus_pts_us']):
        raise ValueError('All-unknown route has no numeric timestamp delta')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'loader', 'runtime', 'driver', 'source', 'node', 'runtime-identity', 'private-prefix'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--driver-sha256', required=True)
    parser.add_argument('--seek-us', type=int, required=True)
    parser.add_argument('--pts-us', type=int, action='append', required=True)
    parser.add_argument('--extra-library-dir', type=Path, action='append', default=[])
    args = parser.parse_args()
    os.umask(0o077)
    result = {'scope': SCOPE, 'pass': False}
    child = None
    started = time.monotonic()
    def interrupted(*unused):
        raise RuntimeError('Owned diagnostic interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    stage = 'preflight'
    try:
        caps = resources()
        if caps['memory_limit_bytes'] != 1610612736 or caps['swap_limit_bytes'] != 0 or not 0 < caps['cpu_limit'] <= 1:
            raise ValueError('Bounded cgroup required')
        if args.seek_us != 1200000000 or len(args.pts_us) != 3 or args.pts_us != sorted(set(args.pts_us)) or any(not args.seek_us < p <= 1380000000 for p in args.pts_us):
            raise ValueError('Exact private frame targets required')
        paths = {name: Path(str(args.private_prefix)+suffix) for name, suffix in
                 (('ready','.ready'),('ack','.ack'),('stdout','.stdout-private.json'),('stderr','.stderr-private.log'),('proof','.live-proof-private.json'))}
        if not args.private_prefix.is_absolute() or any(p.exists() or p.is_symlink() for p in paths.values()):
            raise ValueError('Fresh private files required')
        manifest = json.loads(args.runtime_identity.read_text())
        if set(manifest) != {'files'} or not manifest['files']:
            raise ValueError('Exact closure required')
        closure = {name: Path(item['path']).resolve(strict=True) for name, item in manifest['files'].items()}
        before = observe(args, closure)
        if before['binary'][1] != args.binary_sha256 or before['driver'][1] != args.driver_sha256 or any(before['runtime'][name][1] != manifest['files'][name]['sha256'] for name in closure):
            raise ValueError('Code identity differs')
        loader = args.loader.resolve(strict=True)
        binary = args.binary.resolve(strict=True)
        runtime = args.runtime.resolve(strict=True)
        if loader not in closure.values() or not runtime.is_dir():
            raise ValueError('Loader closure required')
        directories = [runtime] + [p.resolve(strict=True) for p in args.extra_library_dir]
        if any(not p.is_dir() for p in directories):
            raise ValueError('Explicit library paths required')
        library_path = ':'.join(map(str, directories))
        argv = [str(loader), '--library-path', library_path, str(binary), str(args.source.resolve(strict=True)), str(args.node.resolve(strict=True)), str(args.seek_us), *(str(p) for p in args.pts_us)]
        nonce = secrets.token_hex(32)
        env = dict(os.environ, LD_LIBRARY_PATH=library_path, ONEVPL_PRIORITY_PATH=str(directories[1]),
                   LIBVA_DRIVER_NAME='iHD', LIBVA_DRIVERS_PATH=str(args.driver.resolve(strict=True).parent))
        env.update(handshake_environment(paths['ready'], paths['ack'], nonce))
        env['YB_BL_PROBE_LIFECYCLE']='0'
        parent = process_record(os.getpid())
        proof = None
        with paths['stdout'].open('xb') as stdout, paths['stderr'].open('xb') as stderr:
            stage = 'decode'
            child = subprocess.Popen(argv, env=env, stdout=stdout, stderr=stderr)
            deadline = time.monotonic()+170
            while child.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Probe deadline')
                if paths['ready'].exists() and proof is None:
                    stage = 'live_identity'
                    proof = acknowledge_unit_child(paths['ready'], paths['ack'], nonce, parent['pid'], parent['start_ticks'], loader, binary, args.binary_sha256, argv, args.node, closure, args.driver)
                    if proof['probe_pid'] != child.pid:
                        raise ValueError('Actual child mismatch')
                    stage = 'remaining_samples'
                time.sleep(.05)
        stage = 'postflight'
        after = observe(args, closure)
        if before != after or proof is None or child.returncode != 0 or not 0 < paths['stdout'].stat().st_size <= 1048576:
            raise ValueError('Complete stable proof required')
        raw = json.loads(paths['stdout'].read_text())
        validate_raw(raw, args.pts_us)
        paths['proof'].write_text(json.dumps({'before':before, 'after':after, 'live':proof, 'raw':raw}))
        result.update(pass_=True, live_child_identity_verified=True, actual_gpu_client_verified=True,
                      actual_mapped_code_closure_verified=True, matched_frames=3, literal_sample_differences=0,
                      metadata_and_picture_properties_equal=True, code_driver_and_source_stat_unchanged=True,
                      source_identity_scope='local stat identity only; no content immutability claim')
        result.update(controlled_packet_window=raw['controlled_packet_window'],
                      decoded_pair_coverage=raw['decoded_pair_coverage'],
                      source_packet_duration=raw['source_packet_duration'],lifecycle_enabled=False,
                      comparison_contract=raw['comparison_contract'],transport_pkt_dts=raw['transport_pkt_dts'],
                      selected_property_observations=[{key:f[key] for key in ('legacy_all_properties_equal','picture_properties_equal','transport_pkt_dts_equal')} for f in raw['frames']])
    except BaseException as error:
        result.update(error_type=type(error).__name__, failure_stage=stage)
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            stop_owned_child(child)
        except BaseException:
            result.update(pass_=False, child_cleanup_failed=True)
        if child is not None:
            result['probe_exit_code'] = child.returncode
        try:
            caps = resources()
            result['resources'] = caps
            if not 0 < caps['peak_memory_bytes'] <= caps['memory_limit_bytes'] or any(caps['memory_events'].values()) or caps['swap_current_bytes'] or caps['swap_peak_bytes']:
                result['pass_'] = False
        except BaseException:
            result.update(pass_=False, resource_evidence_missing=True)
        result['elapsed_seconds'] = time.monotonic()-started
        result['pass'] = result.pop('pass_', False)
        print(json.dumps(result))
    return 0 if result['pass'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
