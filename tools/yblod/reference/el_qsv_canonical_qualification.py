"""Additive cryptographic preservation gate; historical literal gates unchanged."""
import hashlib
import json
import re
import math
from compare_canonical_renderer_records import METHOD

PTS=(1210000000,1220010000,1230020000)


def require(condition,message):
    if not condition:raise ValueError(message)


def qualify_document(record,candidate):
    require(isinstance(candidate,str) and re.fullmatch('[a-f0-9]{64}',candidate),'Candidate hash required')
    require(isinstance(record,dict) and record.get('schema')=='yblod.el-qsv-canonical-qualification.v1','Explicit additive schema required')
    for key,value in dict(candidate_binary_sha256=candidate,movie_id=3391,content='Saving Private Ryan',seek_seconds=1200,planar_flag=1,batched_planes=0,immutable_instructions=0).items():
        require(record.get(key)==value and type(record.get(key)) is type(value),'Matched candidate/scene/route required')
    for key in ('target_identity_verified','same_candidate_runtime_verified','probe_and_captures_same_source_stat_identity_verified','raw_probe_helper_matches_candidate_helper','retained_runtime_output_preserved'):
        require(record.get(key) is True,'Independent source/runtime/target/helper association required')
    canonical=record.get('canonical_comparison',{})
    require(canonical.get('schema')=='yblod.canonical-tunnel-comparison.v1' and canonical.get('candidate_binary_sha256')==candidate,'Actual canonical comparison required')
    for key in ('passed','source_timestamps_equal','source_metadata_fingerprints_equal','complete_canonical_rgb_fingerprints_equal','canonical_packet_fingerprints_equal'):
        require(canonical.get(key) is True,'No canonical picture or payload difference accepted')
    require(type(canonical.get('frame_count')) is int and canonical['frame_count']==3 and canonical.get('literal_pairwise_byte_comparison') is False,'Cryptographic method must remain explicit')
    require(canonical.get('method')==METHOD,'Exact reviewed canonical method required')
    raw=record.get('raw_target_enhancement',{})
    require(raw.get('schema')=='yblod-el-qsv-petunia-raw-frames-v1' and raw.get('pass') is True,'Actual target raw-EL proof required')
    contract=raw.get('sample_contract',{})
    for key,value in dict(format='P010',bit_depth=10,active_width=1920,active_height=1080,plane_order=['Y','U','V'],active_sample_counts=[2073600,518400,518400]).items():
        require(contract.get(key)==value and type(contract.get(key)) is type(value),'Exact active raw-EL contract required')
    require(all(type(x) is int for x in contract['active_sample_counts']),'Integer active sample counts required')
    identity=raw.get('identity_and_route',{})
    for key in ('capture_target_host_gpu_independently_verified','actual_probe_gpu_matches_verified_target','live_probe_child_generation_and_mapping_verified','exact_mapped_code_closure_verified','expected_libvpl_implementation_and_existing_driver_loaded','code_driver_source_stat_identity_unchanged'):
        require(identity.get(key) is True,'Actual live target identity required')
    require(type(identity.get('deleted_code_mappings')) is int and identity['deleted_code_mappings']==0 and
        type(identity.get('actual_i915_client_count')) is int and identity['actual_i915_client_count']==1 and
        type(identity.get('successful_qsv_direct_mapped_frames')) is int and identity['successful_qsv_direct_mapped_frames']>=3,'Actual mapped frame/device counters required')
    for resource in (raw.get('resources',{}),record.get('metadata_inspection',{})):
        require(type(resource.get('memory_limit_bytes')) is int and resource['memory_limit_bytes']==536870912 and
            resource.get('memory_events_all_zero') is True,'Bounded successful diagnostic resources required')
        peak=resource.get('memory_peak_bytes',resource.get('peak_memory_bytes'))
        require(type(peak) is int and 0<peak<=536870912,'Measured diagnostic peak required')
        for key in ('swap_current_bytes','swap_peak_bytes'):
            require(type(resource.get(key)) is int and resource[key]==0,'No diagnostic swap accepted')
        cpu=resource.get('cpu_limit')
        require(type(cpu) in (int,float) and math.isfinite(cpu) and 0<cpu<=1,'Bounded diagnostic CPU required')
    rows=raw.get('frames');require(isinstance(rows,list) and len(rows)==3,'Three raw frames required')
    for row,pts in zip(rows,PTS):
        require(type(row.get('pts_microseconds')) is int and row['pts_microseconds']==pts,'Exact raw PTS required')
        for key in ('differing_uint16_samples','maximum_absolute_10bit_code_delta'):
            value=row.get(key);require(isinstance(value,list) and len(value)==3 and all(type(x) is int and x==0 for x in value),'Literal raw samples must match')
        require(row.get('p010_low_bits_zero') is True and row.get('all_frame_properties_equal') is True,'Raw properties/lowbits required')
    residual=record.get('metadata_inspection',{})
    for key in ('pass','all_three_actual_map_color_valid','all_three_metadata_use_enhancement_residual','captured_metadata_unchanged','system_loader_and_libplacebo_unchanged','loader_and_relocations_verified','owned_unit_terminal'):
        require(residual.get(key) is True,'Actual captured residual-active metadata required')
    require(record.get('residual_metadata_matches_canonical_capture_frames') is True,'Residual inspection must identify these same captures')
    return dict(candidate_binary_sha256=candidate,frame_count=3,planar_flag=1,batched_planes=0,
        same_candidate_qsv_output_preserved=True,raw_active_EL_samples_equal=True,
        metadata_enables_FEL_residual=True,method='Cryptographic canonical complete RGB and packet equality; literal raw EL equality',
        scope='Profile7 SPR EL-only/depth1/batch0; no BL-QSV or display conformance claim.')


def qualify_report(path,candidate,expected_sha256):
    data=path.read_bytes()
    require(hashlib.sha256(data).hexdigest()==expected_sha256,'Reviewed qualification document changed')
    return qualify_document(json.loads(data),candidate)
