from pathlib import Path
import unittest
from unittest.mock import patch
import prepare_target_bl_closure as c

class Closure(unittest.TestCase):
    def test_notfound_even_with_other_rows(self):
        with self.assertRaises(AssertionError):c.resolved_rows('libx.so => not found\n',Path('/stage'),Path('/vpl'))
    def test_rejects_old_ffmpeg(self):
        with patch.object(Path,'resolve',lambda p,strict=True:p):
            with self.assertRaises(AssertionError):c.resolved_rows('libavcodec.so.63 => /vpl/libavcodec.so.63 (0x0)',Path('/stage'),Path('/vpl'))
    def test_overlay_and_system(self):
        with patch.object(Path,'resolve',lambda p,strict=True:p):
            self.assertEqual(len(c.resolved_rows('libavcodec.so.63 => /stage/libavcodec.so.63 (0x0)\nlibc.so.6 => /usr/lib/libc.so.6 (0x0)',Path('/stage'),Path('/vpl'))),2)
    def test_empty_or_external_rejected(self):
        with self.assertRaises(AssertionError):c.resolved_rows('',Path('/stage'),Path('/vpl'))
        with patch.object(Path,'resolve',lambda p,strict=True:p):
            with self.assertRaises(AssertionError):c.resolved_rows('libc.so.6 => /host/libc.so.6 (0x0)',Path('/stage'),Path('/vpl'))

if __name__=='__main__':unittest.main()
