import ast,copy,json
from pathlib import Path
import unittest
root=Path(__file__).resolve().parent
def functions(path,names,namespace):
 tree=ast.parse(path.read_text())
 exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),str(path),'exec'),namespace)
base={}
functions(root/'observe_picture_transport_qsv_bl_probe.py',{'validate_raw','validate_three_frame_raw'},base)
ns={'validate_picture_window':base['validate_raw']}
functions(root/'observe_picture_lifecycle_qsv_bl_probe.py',{'validate_raw'},ns)
validate=ns['validate_raw']
PTS=[1210000000,1220010000,1230020000]
fixture_ns={'PTS':PTS}
functions(root/'test_observe_picture_transport_qsv_bl_probe.py',{'fixture','good'},fixture_ns)
def good():
 r=fixture_ns['good']();r.pop('controlled_packet_window')
 e=dict(accepted_aus=[3,3],returned_frames=[3,3],paired_instructions=3,receive_eof=[True,True],target_pictures_equal=True,retained_owner_readback_equal=True,without_rpu=0,new_rpu=2,previous_rpu=1,event_count=3,pending_unpaired_snapshots=0,positive_duration_packets=3,unknown_duration_packets=0,transport_pkt_dts=copy.deepcopy(r['transport_pkt_dts']))
 r['controlled_packet_window_lifecycle']=dict(full_film_eof=False,epochs_completed=3,mapped_owners_retained=1,private_packet_digest_sequence_equal=True,epochs=[dict(copy.deepcopy(e),epoch=i) for i in range(3)])
 return r
class Contracts(unittest.TestCase):
 def test_valid(self):validate(good(),PTS)
 def test_ownership(self):
  for k,v in [('epochs_completed',2),('mapped_owners_retained',0),('private_packet_digest_sequence_equal',False),('full_film_eof',True)]:
   r=good();r['controlled_packet_window_lifecycle'][k]=v
   with self.assertRaises(ValueError):validate(r,PTS)
 def test_every_epoch(self):
  for i in range(3):
   for k,v in [('epoch',True),('accepted_aus',[3,2]),('returned_frames',[3,2]),('paired_instructions',2),('receive_eof',[True,False]),('target_pictures_equal',False),('retained_owner_readback_equal',False),('event_count',0),('pending_unpaired_snapshots',1),('positive_duration_packets',0),('unknown_duration_packets',1)]:
    r=good();r['controlled_packet_window_lifecycle']['epochs'][i][k]=v
    with self.assertRaises(ValueError):validate(r,PTS)
 def test_each_transport(self):
  for i in range(3):
   for k,v in [('observed_pairs',2),('equal_pairs',1),('different_pairs',4),('known_pairs',4),('reference_unknown',4),('candidate_unknown',4),('both_unknown',4)]:
    r=good();r['controlled_packet_window_lifecycle']['epochs'][i]['transport_pkt_dts'][k]=v
    with self.assertRaises(ValueError):validate(r,PTS)
 def test_final_counts(self):
  for block,k,v in [('decoded_pair_coverage','new_rpu',1),('decoded_pair_coverage','without_rpu',1),('decoded_pair_coverage','previous_rpu',0),('decoded_pair_coverage','pending_unpaired_snapshots',1),('source_packet_duration','positive_packets',2),('source_packet_duration','unknown_zero_packets',1),('transport_pkt_dts','observed_pairs',2)]:
   r=good();r[block][k]=v
   with self.assertRaises(ValueError):validate(r,PTS)
 def test_missing_snapshot_or_pixel(self):
  for block,key,val in [('frame','picture_properties_equal',False),('frame','resolved_dolby_metadata_equal',False),('frame','raw_rpu_presence_and_bytes_equal',False),('plane','differing_uint16_samples',1)]:
   r=good();dest=r['frames'][0] if block=='frame' else r['frames'][0]['planes'][0];dest[key]=val
   with self.assertRaises(ValueError):validate(r,PTS)
 def test_duration_binding(self):
  r=good();r['source_packet_duration']['returned_frames_bound_to_au_duration']=False
  with self.assertRaises(ValueError):validate(r,PTS)
if __name__=='__main__':
 cg=Path('/sys/fs/cgroup')
 assert int((cg/'memory.max').read_text())==536870912 and int((cg/'memory.swap.max').read_text())==0
 q,p=(cg/'cpu.max').read_text().split();assert q!='max' and 0<int(q)<=int(p)
 result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Contracts))
 events={k:int(v) for k,v in (l.split() for l in (cg/'memory.events').read_text().splitlines())}
 assert not any(events.values()) and int((cg/'memory.swap.peak').read_text())==0
 print(json.dumps(dict(mock_tests=result.testsRun,all_passed=result.wasSuccessful(),memory_peak_bytes=int((cg/'memory.peak').read_text()),memory_events=events,swap_peak_bytes=0)))
 raise SystemExit(0 if result.wasSuccessful() else 1)
