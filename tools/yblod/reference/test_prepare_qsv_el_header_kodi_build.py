from pathlib import Path
import unittest
from unittest.mock import patch
from contextlib import ExitStack
import prepare_qsv_el_header_kodi_build as tool


class HeaderBuildTests(unittest.TestCase):
    def execute(self,wrong_binary=False,wrong_helper=False,wrong_other=False,apply=False,wrong_patch=False,build_drift=False,apply_failure=False):
        kodi=Path('/sdk/kodi');source=Path('/backup/source')
        state={'isolated':False,'actual':False}
        def digest(path):
            if path==kodi/'.x86_64-libreelec-linux-gnu/kodi.bin':return 'wrong' if wrong_binary else 'a'*64
            if path==Path('/backup/build/kodi.bin'):return 'a'*64
            if path.name in tool.PATCH_SHA:return 'wrong' if wrong_patch else tool.PATCH_SHA[path.name]
            if build_drift and state['isolated'] and path==kodi/'.x86_64-libreelec-linux-gnu/build.ninja':return 'wrong'
            if path==source/tool.HELPER and state['isolated']:return 'wrong' if wrong_helper else tool.EXPECTED_HELPER_SHA
            if path==kodi/tool.HELPER and state['actual']:return tool.EXPECTED_HELPER_SHA
            if wrong_other and state['isolated'] and path==source/tool.NEW:return 'wrong'
            return 'b'*64
        def run(command,cwd,**unused):
            if '--dry-run' not in command and command[-1].endswith(tool.PATCHES[-1]):
                if cwd==kodi and apply_failure:raise RuntimeError('mock second apply failure')
                state['isolated' if cwd==source else 'actual']=True
        with ExitStack() as stack:
            validate=stack.enter_context(patch.object(tool,'validate_prepared'))
            stack.enter_context(patch.object(tool,'digest',side_effect=digest))
            stack.enter_context(patch.object(tool.tempfile,'mkdtemp',return_value='/backup'))
            stack.enter_context(patch.object(Path,'mkdir'))
            copied=stack.enter_context(patch.object(tool.shutil,'copy2'))
            commands=stack.enter_context(patch.object(tool.subprocess,'run',side_effect=run))
            result=tool.prepare(kodi,Path('/recipe'),{'engine_sha256':{'engine':'c'*64}},'a'*64,Path('/parent'),apply)
            return result,validate.call_count,copied.call_count,[call.args[0] for call in commands.call_args_list]

    def test_default_isolated_only(self):
        result,validated,copied,commands=self.execute()
        self.assertFalse(result['source_applied']);self.assertFalse(result['build_started'])
        self.assertTrue(result['only_el_helper_changed'])
        self.assertEqual(validated,2);self.assertEqual(copied,11);self.assertEqual(len(commands),2)
        self.assertTrue(all('--fuzz=0' in command for command in commands))
        self.assertEqual(set(result['isolated_source_sha256']),set((*tool.FILES,tool.NEW)))

    def test_exact_baseline_binary_required(self):
        with self.assertRaises(ValueError):self.execute(wrong_binary=True)

    def test_exact_raw_qualified_helper_required(self):
        with self.assertRaises(ValueError):self.execute(wrong_helper=True)

    def test_non_helper_source_cannot_change(self):
        with self.assertRaises(ValueError):self.execute(wrong_other=True)

    def test_exact_patch_pins_required(self):
        with self.assertRaises(ValueError):self.execute(wrong_patch=True)

    def test_build_artifact_drift_rejected(self):
        with self.assertRaises(ValueError):self.execute(build_drift=True)

    def test_apply_success_matches_isolated_receipt(self):
        result,validated,copied,commands=self.execute(apply=True)
        self.assertTrue(result['source_applied']);self.assertEqual(validated,3)
        self.assertEqual(len(commands),6)

    def test_partial_apply_has_failure_receipt_not_success(self):
        with self.assertRaises(tool.PartialPreparationFailure) as caught:self.execute(apply=True,apply_failure=True)
        receipt=caught.exception.report
        self.assertFalse(receipt['source_applied']);self.assertFalse(receipt['build_started'])
        self.assertTrue(receipt['partial_source_application_possible'])
        self.assertEqual(receipt['backup_directory'],'/backup')


if __name__=='__main__':unittest.main()
