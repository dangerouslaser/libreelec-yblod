import ast
import copy
import json
from pathlib import Path
import unittest

root=Path(__file__).resolve().parent
tree=ast.parse((root/'observe_picture_transport_qsv_bl_probe.py').read_text())
namespace={}
exec(compile(ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in ('validate_raw','validate_three_frame_raw')],type_ignores=[]),str(root/'observe_picture_transport_qsv_bl_probe.py'),'exec'),namespace)
validate=namespace['validate_raw']
PTS=[1210000000,1220010000,1230020000]
def fixture():
 frames=[]
 for pts in PTS:
  frames.append(dict(pts_microseconds=pts,picture_properties_equal=True,legacy_all_properties_equal=False,transport_pkt_dts_equal=False,resolved_dolby_metadata_equal=True,
                     raw_rpu_presence_and_bytes_equal=True,sample_comparison_completed=True,
                     reference_raw_rpu_present=True,candidate_raw_rpu_present=True,
                     planes=[dict(plane=n,sample_count=c,differing_uint16_samples=0,
                                  maximum_absolute_sample_codes=0,p010_low_bits_zero=True)
                             for n,c in zip('YUV',(3840*2160,1920*1080,1920*1080))]))
 return dict(scope='three raw BL frames and independent native HEVC Dolby metadata only; not Kodi or performance',
             pass_=True,packet_clone_identity_verified=True,submitted_packets_equal=True,frames=frames,
             controlled_packet_window=dict(full_film_eof=False,accepted_aus=[3,3],returned_frames=[3,3],event_count=3,receive_eof=[True,True],complete_event_pairs=True),
             decoded_pair_coverage=dict(paired_frames=3,without_rpu=0,new_rpu=2,previous_rpu=1,multiple_rpu_aus=0,pending_unpaired_snapshots=0,previous_reference_validity_scope='independent native decoder resolution, not header classifier'),
             source_packet_duration=dict(positive_packets=3,unknown_zero_packets=0,returned_frames_bound_to_au_duration=True))
def good():
 v=fixture();v['pass']=v.pop('pass_')
 v['comparison_contract']='picture-association.v2'
 v['transport_pkt_dts']=dict(qualifies_picture=False,observed_pairs=3,equal_pairs=0,different_pairs=3,reference_unknown=0,candidate_unknown=0,both_unknown=0,known_pairs=3,max_absolute_route_delta_us=41000,max_absolute_reference_minus_pts_us=82000,max_absolute_candidate_minus_pts_us=41000)
 return v
class Contracts(unittest.TestCase):
 def test_valid(self):validate(good(),PTS)
 def test_transport(self):
  for key,value in [('observed_pairs',2),('equal_pairs',1),('different_pairs',True),('qualifies_picture',True),('reference_unknown',4),('known_pairs',2),('both_unknown',1),('max_absolute_route_delta_us',-1)]:
   v=good();v['transport_pkt_dts'][key]=value
   with self.assertRaises(ValueError):validate(v,PTS)
 def test_legacy_property_honesty(self):
  v=good();v['frames'][0]['legacy_all_properties_equal']=True
  with self.assertRaises(ValueError):validate(v,PTS)
 def test_legacy_contract_rejected(self):
  v=good();v['comparison_contract']='old'
  with self.assertRaises(ValueError):validate(v,PTS)
 def test_unknown_transport(self):
  v=good();d=v['transport_pkt_dts'];d.update(reference_unknown=3,candidate_unknown=3,both_unknown=3,known_pairs=0,equal_pairs=3,different_pairs=0,max_absolute_route_delta_us=0,max_absolute_reference_minus_pts_us=0,max_absolute_candidate_minus_pts_us=0)
  for f in v['frames']:f.update(legacy_all_properties_equal=True,transport_pkt_dts_equal=True)
  validate(v,PTS)
 def test_window(self):
  for key,val in [('full_film_eof',True),('accepted_aus',[3,2]),('returned_frames',[3,2]),('event_count',True),('event_count',0),('receive_eof',[True,1]),('complete_event_pairs',False)]:
   with self.subTest(key=key,val=val):
    v=good();v['controlled_packet_window'][key]=val
    with self.assertRaises(ValueError):validate(v,PTS)
 def test_pair(self):
  for key,val in [('paired_frames',2),('pending_unpaired_snapshots',1),('new_rpu',True),('without_rpu',1),('previous_reference_validity_scope','header only')]:
   v=good();v['decoded_pair_coverage'][key]=val
   with self.assertRaises(ValueError):validate(v,PTS)
 def test_duration(self):
  for key,val in [('positive_packets',0),('positive_packets',True),('unknown_zero_packets',1),('returned_frames_bound_to_au_duration',False)]:
   v=good();v['source_packet_duration'][key]=val
   with self.assertRaises(ValueError):validate(v,PTS)
 def test_no_schema_waiver(self):
  for block in ('controlled_packet_window','decoded_pair_coverage','source_packet_duration'):
   v=good();v[block]['unexpected']=0
   with self.assertRaises(ValueError):validate(v,PTS)
 def test_pixels(self):
  v=good();v['frames'][1]['planes'][2]['differing_uint16_samples']=1
  with self.assertRaises(ValueError):validate(v,PTS)
 def test_metadata(self):
  v=good();v['frames'][0]['resolved_dolby_metadata_equal']=False
  with self.assertRaises(ValueError):validate(v,PTS)
 def test_wrong_pts(self):
  v=good();v['frames'][1]['pts_microseconds']+=1
  with self.assertRaises(ValueError):validate(v,PTS)
if __name__=='__main__':
 cg=Path('/sys/fs/cgroup');assert (cg/'memory.max').read_text().strip()=='536870912' and (cg/'memory.swap.max').read_text().strip()=='0'
 q,p=(cg/'cpu.max').read_text().split();assert q!='max' and 0<int(q)<=int(p)
 result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Contracts))
 events={k:int(v) for k,v in (x.split() for x in (cg/'memory.events').read_text().splitlines())};peak=int((cg/'memory.peak').read_text())
 assert 0<peak<=536870912 and not any(events.values()) and int((cg/'memory.swap.current').read_text())==int((cg/'memory.swap.peak').read_text())==0
 print(json.dumps(dict(mock_tests=result.testsRun,all_passed=result.wasSuccessful(),memory_peak_bytes=peak,memory_events=events,swap_peak_bytes=0)))
 raise SystemExit(0 if result.wasSuccessful() else 1)
