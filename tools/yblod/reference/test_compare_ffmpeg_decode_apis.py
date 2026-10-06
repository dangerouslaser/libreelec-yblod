import unittest
from pathlib import Path

from compare_ffmpeg_decode_apis import command, gpu_metrics


class Tests(unittest.TestCase):
    def test_progress_pipe_is_explicit_build_dependency(self):
        recipe = Path(__file__).with_name('Dockerfile.ffmpeg9-decode-apis').read_text()
        self.assertIn('--enable-protocol=file,pipe', recipe)
        self.assertNotIn('--disable-x86asm', recipe)

    def test_same_source_settings_resident_frames_no_encode_transfer(self):
        for api in ('vaapi', 'qsv'):
            args = command(api, 180, 1200)
            self.assertEqual(args[args.index('-hwaccel_output_format')+1], api)
            self.assertEqual(args[args.index('-i')+1], '/input/source.mkv')
            self.assertEqual(args[args.index('-ss')+1], '1200')
            self.assertEqual(args[args.index('-t')+1], '180')
            self.assertIn('wrapped_avframe', args)
            self.assertIn('passthrough', args)
            self.assertNotIn('hwdownload', args)
            self.assertNotIn('hwupload', args)
            self.assertNotIn('-re', args)
        qsv = command('qsv', 180, 1200)
        self.assertIn('qsv=qs@va', qsv)
        self.assertEqual(qsv[qsv.index('-async_depth')+1], '4')

    def test_deduplicated_client_time_and_observation_scope(self):
        samples = [(index*1_000_000_000, {'gpu/1': {'drm-engine-video': index*100_000_000,
                                                 'drm-engine-render': index*10_000_000}})
                   for index in range(3)]
        result = gpu_metrics(samples)
        self.assertEqual(result['covered_seconds'], 2)
        self.assertEqual(result['engine_activity_percent']['video'], 10)
        self.assertEqual(result['sampled_engine_seconds']['video'], .2)

    def test_insufficient_no_video_reset_or_client_change_rejected(self):
        fixtures = (
            [(0, {}), (3_000_000_000, {})],
            [(i*1_000_000_000, {'gpu/1': {'drm-engine-render': i*100}}) for i in range(3)],
            [(0, {'gpu/1': {'drm-engine-video': 100}}),
             (1_000_000_000, {'gpu/1': {'drm-engine-video': 99}})],
            [(i*1_000_000_000, {f'gpu/{i}': {'drm-engine-video': i*100}}) for i in range(3)],
        )
        for samples in fixtures:
            with self.assertRaises(RuntimeError):
                gpu_metrics(samples)


if __name__ == '__main__':
    unittest.main()
