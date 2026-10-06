import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import el_qsv_observer_fixture as module


class Tests(unittest.TestCase):
    def api(self,method,params=None):
        params=params or {}
        if method=='Player.GetActivePlayers':return [{'type':'video','playerid':1}]
        if method=='Player.GetItem':return {'item':{'id':3391,'type':'movie'}}
        if method=='Player.GetProperties':return {'subtitleenabled':self.state['enabled'],'currentsubtitle':{'index':self.state['index']}}
        if method=='Player.SetSubtitle':
            if not self.path.exists():raise AssertionError('Snapshot missing before mutation')
            subtitle=params['subtitle']
            if type(subtitle) is int:self.state['index']=subtitle
            else:self.state['enabled']=subtitle=='on'
            return 'OK'
        raise AssertionError(method)

    def setup(self,directory):
        self.path=Path(directory).resolve()/'recovery.json';self.state=dict(enabled=True,index=0)
        return patch.dict(os.environ,YB_EL_SUBTITLE_RECOVERY=str(self.path))

    def test_normal_restore_and_original_persisted(self):
        with tempfile.TemporaryDirectory() as directory,self.setup(directory):
            with module.subtitles_off_fixture(True,self.api,lambda _:None,3391):
                self.assertFalse(self.state['enabled'])
                self.assertEqual(json.loads(self.path.read_text())['before'],{'enabled':True,'index':0})
            self.assertTrue(self.state['enabled']);self.assertTrue(json.loads(self.path.read_text())['restored'])

    def test_interruption_raises_through_fixture_finally(self):
        with tempfile.TemporaryDirectory() as directory,self.setup(directory),patch.object(module.signal,'signal'):
            with self.assertRaises(RuntimeError):
                with module.subtitles_off_fixture(True,self.api,lambda _:None,3391):module.interrupted()
            self.assertTrue(self.state['enabled']);self.assertTrue(json.loads(self.path.read_text())['restored'])

    def test_parent_recovery_on_matching_player(self):
        with tempfile.TemporaryDirectory() as directory,self.setup(directory):
            module.write_record(self.path,dict(movie_id=3391,player_id=1,before=dict(self.state),restored=False))
            self.state['enabled']=False
            module.recover(self.path,self.api,lambda _:None,3391)
            self.assertTrue(self.state['enabled'])

    def test_parent_refuses_different_player(self):
        with tempfile.TemporaryDirectory() as directory,self.setup(directory):
            module.write_record(self.path,dict(movie_id=3391,player_id=9,before=dict(self.state),restored=False))
            with self.assertRaises(RuntimeError):module.recover(self.path,self.api,lambda _:None,3391)

    def test_preexisting_record_refused_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory,self.setup(directory):
            self.path.write_text('{}')
            with self.assertRaises(RuntimeError):
                with module.subtitles_off_fixture(True,self.api,lambda _:None,3391):pass
            self.assertTrue(self.state['enabled'])

if __name__=='__main__':unittest.main()
