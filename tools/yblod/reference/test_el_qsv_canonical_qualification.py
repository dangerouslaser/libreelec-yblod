import copy
import json
from pathlib import Path
import unittest
import el_qsv_canonical_qualification as module


def fixture():
    root=Path(__file__).parent
    resident=json.loads((root/'EL_QSV_HEADER_KODI_ON_RESIDENT_RESULTS.json').read_text())
    return dict(schema='yblod.el-qsv-canonical-qualification.v1',candidate_binary_sha256='1'*64,
        movie_id=3391,content='Saving Private Ryan',seek_seconds=1200,planar_flag=1,
        batched_planes=0,immutable_instructions=0,target_identity_verified=True,
        same_candidate_runtime_verified=True,probe_and_captures_same_source_stat_identity_verified=True,
        raw_probe_helper_matches_candidate_helper=True,retained_runtime_output_preserved=True,
        residual_metadata_matches_canonical_capture_frames=True,
        canonical_comparison=dict(schema='yblod.canonical-tunnel-comparison.v1',candidate_binary_sha256='1'*64,
            method=module.METHOD,
            passed=True,source_timestamps_equal=True,source_metadata_fingerprints_equal=True,
            complete_canonical_rgb_fingerprints_equal=True,canonical_packet_fingerprints_equal=True,
            frame_count=3,literal_pairwise_byte_comparison=False),
        raw_target_enhancement=json.loads((root/'EL_QSV_PETUNIA_RAW_FRAME_RESULTS.json').read_text()),
        metadata_inspection=resident['metadata_inspection'])


class Tests(unittest.TestCase):
    def test_valid_synthetic_associations(self):
        self.assertTrue(module.qualify_document(fixture(),'1'*64)['same_candidate_qsv_output_preserved'])

    def test_association_gates_all_required(self):
        for key in ('target_identity_verified','same_candidate_runtime_verified',
                'probe_and_captures_same_source_stat_identity_verified','raw_probe_helper_matches_candidate_helper',
                'retained_runtime_output_preserved','residual_metadata_matches_canonical_capture_frames'):
            for value in (False,1,None):
                record=fixture();record[key]=value
                with self.assertRaises(ValueError):module.qualify_document(record,'1'*64)

    def test_route_scene_and_binary(self):
        for key,value in [('candidate_binary_sha256','2'*64),('movie_id',51),('seek_seconds',True),('batched_planes',1),('planar_flag',False)]:
            record=fixture();record[key]=value
            with self.assertRaises(ValueError):module.qualify_document(record,'1'*64)

    def test_no_picture_or_raw_tolerance(self):
        record=fixture();record['canonical_comparison']['complete_canonical_rgb_fingerprints_equal']=False
        with self.assertRaises(ValueError):module.qualify_document(record,'1'*64)
        for value in (1,True):
            record=fixture();record['raw_target_enhancement']['frames'][0]['differing_uint16_samples'][1]=value
            with self.assertRaises(ValueError):module.qualify_document(record,'1'*64)

    def test_raw_pts_properties_and_target(self):
        for key,value in [('pts_microseconds',1210000001),('all_frame_properties_equal',False),('p010_low_bits_zero',1)]:
            record=fixture();record['raw_target_enhancement']['frames'][0][key]=value
            with self.assertRaises(ValueError):module.qualify_document(record,'1'*64)
        record=fixture();record['raw_target_enhancement']['identity_and_route']['actual_probe_gpu_matches_verified_target']=False
        with self.assertRaises(ValueError):module.qualify_document(record,'1'*64)

    def test_actual_residual_and_resource_required(self):
        for key,value in [('all_three_metadata_use_enhancement_residual',False),('owned_unit_terminal',1),('swap_peak_bytes',1),('peak_memory_bytes',0)]:
            record=fixture();record['metadata_inspection'][key]=value
            with self.assertRaises(ValueError):module.qualify_document(record,'1'*64)

if __name__=='__main__':unittest.main()
