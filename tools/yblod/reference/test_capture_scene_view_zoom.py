"""Mock view-mode restoration tests; no real playback or RPC calls."""
from unittest.mock import patch
import unittest

import capture_scene as module


def view(mode='custom',zoom=1.2):
    return dict(viewmode=mode,zoom=zoom,pixelratio=1.0,verticalshift=0.0,nonlinearstretch=False)


class ViewZoomTests(unittest.TestCase):
    def exercise(self,before,fail=False):
        current=before.copy();calls=[]
        def rpc(method,params=None):
            calls.append((method,params))
            if method=='Player.GetViewMode':return current.copy()
            if method=='Player.SetViewMode':
                value=params['viewmode']
                if isinstance(value,str):current.update(before)
                else:current.update(value);current['viewmode']='custom'
            return 'OK'
        with patch.object(module,'rpc',rpc),patch.object(module.time,'sleep'):
            if fail:
                with self.assertRaisesRegex(RuntimeError,'capture failed'):
                    with module.temporary_view_zoom(.9,7):raise RuntimeError('capture failed')
            else:
                with module.temporary_view_zoom(.9,7) as result:
                    self.assertEqual(current['zoom'],.9)
                self.assertEqual(result['before'],before)
                self.assertEqual(result['restored'],before)
        return calls

    def test_custom_numeric_restore(self):
        calls=self.exercise(view())
        sets=[params for method,params in calls if method=='Player.SetViewMode']
        self.assertEqual(sets[-1],{'viewmode':dict(zoom=1.2,pixelratio=1.0,verticalshift=0.0,nonlinearstretch=False)})

    def test_named_mode_string_restore(self):
        calls=self.exercise(view('normal',1.0))
        sets=[params for method,params in calls if method=='Player.SetViewMode']
        self.assertEqual(sets[-1],{'viewmode':'normal'})

    def test_capture_error_restore_before_stop(self):
        calls=self.exercise(view(),True)
        names=[name for name,_ in calls]
        self.assertEqual(names[-1],'Player.Stop')
        self.assertLess(max(i for i,name in enumerate(names) if name=='Player.SetViewMode'),names.index('Player.Stop'))

    def test_apply_error_still_restores_before_stop(self):
        calls=[]
        def rpc(method,params=None):
            calls.append((method,params))
            if method=='Player.GetViewMode':return view()
            if method=='Player.SetViewMode' and params['viewmode'].get('zoom')==.9:raise RuntimeError('apply failed')
            return 'OK'
        with patch.object(module,'rpc',rpc),patch.object(module.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'apply failed'):
                with module.temporary_view_zoom(.9,7):pass
        self.assertEqual(calls[-1][0],'Player.Stop')
        self.assertEqual(calls[-3][0],'Player.SetViewMode')

    def test_default_no_new_rpc(self):
        with patch.object(module,'rpc') as rpc:
            with module.temporary_view_zoom(None,7) as result:self.assertIsNone(result)
            rpc.assert_not_called()

    def test_only_agreed_zoom_allowed(self):
        args=module.parse_args(['--config','/tmp/config','--report','/tmp/report','--view-zoom','.9'])
        self.assertEqual(args.view_zoom,.9)
        with patch('sys.stderr'),self.assertRaises(SystemExit):
            module.parse_args(['--config','/tmp/config','--report','/tmp/report','--view-zoom','1.1'])


if __name__=='__main__':unittest.main()
