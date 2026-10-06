import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import target_el_qsv_live_handshake as live


class LiveHandshakeTests(unittest.TestCase):
    def attempt(self,change=None):
        with tempfile.TemporaryDirectory() as temp:
            ready,ack=Path(temp)/'ready',Path(temp)/'ack'
            ready.write_text(json.dumps({'pid':42,'nonce':'a'*64}));ready.chmod(0o600)
            parent=dict(pid=7,ppid=1,start_ticks=99,executable='wrapper',argv=[])
            child=dict(pid=42,ppid=7,start_ticks=100,executable='/loader',argv=['/loader','probe'])
            rows=[child];calls={7:0,42:1}  # child was observed by unit_children
            def record(pid):
                calls[pid]+=1
                value=dict(parent if pid==7 else child)
                if change=='generation' and pid==42 and calls[pid]>1:value['start_ticks']+=1
                return value
            if change=='extra':rows.append(dict(child,pid=43))
            if change=='pid':ready.write_text(json.dumps({'pid':43,'nonce':'a'*64}))
            if change=='permissions':ready.chmod(0o644)
            if change=='argv':child['argv']=['wrong']
            with patch.object(live,'process_record',side_effect=record),patch.object(live,'unit_children',return_value=rows),patch.object(live,'mapped_probe',return_value=change!='probe-map'),patch.object(live,'process_gpu_client',return_value=[] if change=='gpu-client' else [{'drm-client-id':'1'}]),patch.object(live,'mapped_libraries',return_value=False if change=='library-map' else True),patch.object(Path,'resolve',lambda p,strict=False:p):
                call=lambda:live.acknowledge_unit_child(ready,ack,'a'*64,7,99,'/loader','probe','b'*64,['/loader','probe'],'node',{},'driver')
                if change:
                    with self.assertRaises(ValueError):call()
                    self.assertFalse(ack.exists())
                else:
                    result=call()
                    self.assertTrue(result['live_child_association_verified'])
                    self.assertEqual(ack.read_bytes(),b'a'*64)
                    self.assertEqual(ack.stat().st_mode&0o777,0o600)
    def test_live_exact_child_ack(self):self.attempt()
    def test_changed_generation_rejected(self):self.attempt('generation')
    def test_extra_child_rejected(self):self.attempt('extra')
    def test_wrong_checkpoint_pid_rejected(self):self.attempt('pid')
    def test_public_checkpoint_rejected(self):self.attempt('permissions')
    def test_wrong_private_argv_rejected(self):self.attempt('argv')
    def test_missing_probe_mapping_rejected(self):self.attempt('probe-map')
    def test_missing_gpu_client_rejected(self):self.attempt('gpu-client')
    def test_wrong_library_mapping_rejected(self):self.attempt('library-map')

if __name__=='__main__':unittest.main()
