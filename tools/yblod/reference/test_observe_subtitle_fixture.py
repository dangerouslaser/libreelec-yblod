"""Generated RPC mocks only; no player, GPU or network execution."""
from pathlib import Path
import unittest
from unittest.mock import patch

import observe_subtitle_fixture as fixture
import run_colour_import_matrix as controller


class MockPlayer:
    def __init__(self,enabled=True,index=0):
        self.enabled=enabled;self.index=index;self.calls=[];self.player=1;self.movie=3391
    def rpc(self,method,params=None):
        self.calls.append((method,params))
        if method=='Player.GetActivePlayers':return [dict(type='video',playerid=self.player)]
        if method=='Player.GetItem':return dict(item=dict(id=self.movie,type='movie'))
        if method=='Player.GetProperties':return dict(subtitleenabled=self.enabled,currentsubtitle={} if self.index is None else dict(index=self.index))
        if method=='Player.SetSubtitle':
            value=params['subtitle']
            if value=='off':self.enabled=False
            elif value=='on':self.enabled=True
            else:self.index=value;self.enabled=self.enabled or params.get('enable',False)
            return 'OK'
        raise AssertionError(method)


class SubtitleFixtureTests(unittest.TestCase):
    def test_disable_and_restore_same_enabled_stream_before_stop(self):
        player=MockPlayer()
        with fixture.subtitles_off_fixture(True,player.rpc,lambda _:None,3391) as record:
            self.assertFalse(player.enabled);self.assertEqual(player.index,0)
        fixture.validate_fixture(record,3391)
        player.calls.append(('Player.Stop',dict(playerid=1)))
        self.assertTrue(player.enabled)
        sets=[params for method,params in player.calls if method=='Player.SetSubtitle']
        self.assertEqual(sets[-2:], [dict(playerid=1,subtitle=0,enable=False),dict(playerid=1,subtitle='on')])
        self.assertEqual(player.calls[-1][0],'Player.Stop')

    def test_originally_disabled_restored_disabled(self):
        player=MockPlayer(False,2)
        with fixture.subtitles_off_fixture(True,player.rpc,lambda _:None,3391) as record:pass
        fixture.validate_fixture(record,3391)
        self.assertFalse(player.enabled);self.assertEqual(player.index,2)

    def test_no_subtitle_stream_never_selects_invalid_index(self):
        player=MockPlayer(False,None)
        with fixture.subtitles_off_fixture(True,player.rpc,lambda _:None,3391) as record:pass
        fixture.validate_fixture(record,3391)
        self.assertFalse(any(type(params['subtitle']) is int for method,params in player.calls if method=='Player.SetSubtitle'))

    def test_observation_error_restores_without_stopping(self):
        player=MockPlayer()
        with self.assertRaisesRegex(RuntimeError,'measurement failed'):
            with fixture.subtitles_off_fixture(True,player.rpc,lambda _:None,3391):raise RuntimeError('measurement failed')
        self.assertTrue(player.enabled)
        self.assertFalse(any(method=='Player.Stop' for method,_ in player.calls))

    def test_changed_stream_restored_and_measurement_rejected(self):
        player=MockPlayer()
        with self.assertRaisesRegex(RuntimeError,'changed during measurement'):
            with fixture.subtitles_off_fixture(True,player.rpc,lambda _:None,3391):player.index=2
        self.assertEqual(player.index,0);self.assertTrue(player.enabled)

    def test_changed_player_not_mutated(self):
        player=MockPlayer()
        with self.assertRaisesRegex(RuntimeError,'player changed'):
            with fixture.subtitles_off_fixture(True,player.rpc,lambda _:None,3391):player.player=2
        self.assertEqual(len([1 for method,_ in player.calls if method=='Player.SetSubtitle']),1)

    def test_changed_movie_not_mutated(self):
        player=MockPlayer()
        with self.assertRaisesRegex(RuntimeError,'Movie identity changed'):
            with fixture.subtitles_off_fixture(True,player.rpc,lambda _:None,3391):player.movie=999
        self.assertEqual(len([1 for method,_ in player.calls if method=='Player.SetSubtitle']),1)

    def test_movie_change_between_restore_calls_blocks_visibility_mutation(self):
        player=MockPlayer()
        def rpc(method,params=None):
            result=player.rpc(method,params)
            if method=='Player.SetSubtitle' and type(params['subtitle']) is int:
                player.movie=999
            return result
        with self.assertRaisesRegex(RuntimeError,'Movie identity changed'):
            with fixture.subtitles_off_fixture(True,rpc,lambda _:None,3391):pass
        sets=[params['subtitle'] for method,params in player.calls if method=='Player.SetSubtitle']
        self.assertEqual(sets,['off',0])

    def test_malformed_fixture_records_rejected(self):
        base=dict(movie_id=1,player_id=1,before=dict(enabled=True,index=0),
                  requested_enabled=False,disabled=dict(enabled=False,index=0),
                  disabled_at_end=dict(enabled=False,index=0),restored=dict(enabled=True,index=0))
        for field,value in (('before',[]),('before',dict(enabled=True,index=None)),('movie_id',True),('player_id',True)):
            changed=base.copy();changed[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):fixture.validate_fixture(changed,1)

    def test_default_no_rpc(self):
        with patch.object(fixture,'subtitle_state') as state:
            with fixture.subtitles_off_fixture(False,lambda *_:self.fail('new RPC'),lambda _:None,3391) as record:self.assertIsNone(record)
            state.assert_not_called()

    def test_controller_flag_optional_and_fixture_proof_strict(self):
        required=['--binary-sha256','a'*64,'--root','/tmp/root','--observer','/tmp/observer','--movie-id','3391','--expected-title','Saving Private Ryan']
        self.assertFalse(controller.parser().parse_args(required).subtitles_off)
        self.assertTrue(controller.parser().parse_args(required+['--subtitles-off']).subtitles_off)
        with self.assertRaises(ValueError):fixture.validate_fixture(None,3391)

    def test_observer_restore_scope_precedes_stop_source_contract(self):
        source=(Path(__file__).parent/'observe_native_movie.py').read_text()
        self.assertLess(source.index('with subtitles_off_fixture('),source.index("if args.stop_on_complete"))
        self.assertIn("report['subtitle_fixture'] = subtitle_fixture",source)
        controller_source=(Path(__file__).parent/'run_colour_import_matrix.py').read_text()
        self.assertIn("observer.append('--subtitles-off')",controller_source)


if __name__=='__main__':unittest.main()
