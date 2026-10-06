import ast
import copy
from pathlib import Path
import tempfile
import unittest

from run_colour_import_matrix import (IMPORTS, SCOPE, colour_handoff_summary, parser,
                                      process_cpu_summary, validate_args, validate_report)


def log_lines(flag=0):
    imports = IMPORTS[flag]
    lines = []
    for count, wall, cpu in ((120, 1.0, 0.2), (240, 1.5, 0.4)):
        lines.extend([
            f'DVBridge native reconstruction: presented={count} colour=inherited-release colour_imports={imports}',
            f'DVBridge native composer: released_frames={count} fp32_selected=1 accepted_fp32={count} accepted_integer=0 shader_compile_failed=0 generate_failed=0',
            f'DVBridge native colour handoff: calls={count} valid=true imports={imports} wall_ms_per_call={wall:.3f} thread_cpu_ms_per_call={cpu:.3f} scope={SCOPE}',
        ])
    return lines


def cpu_samples():
    return [dict(pid=10, process_start_ticks=100, clock_ticks_per_second=100,
                 process_cpu_ticks=10, monotonic_ns=1_000_000_000),
            dict(pid=10, process_start_ticks=100, clock_ticks_per_second=100,
                 process_cpu_ticks=30, monotonic_ns=2_000_000_000)]


class ColourImportTests(unittest.TestCase):
    def test_weighted_wall_cpu_and_rounding(self):
        summary = colour_handoff_summary(log_lines(), 0)
        self.assertEqual(summary['weighted_window']['wall_ms_per_call'], 2.0)
        self.assertAlmostEqual(summary['weighted_window']['thread_cpu_ms_per_call'], 0.6)
        self.assertEqual(summary['worst_case_log_rounding_error_ms'], 0.0015)

    def test_both_actual_import_labels(self):
        for flag in (0, 1):
            self.assertEqual(colour_handoff_summary(log_lines(flag), flag)['imports'], IMPORTS[flag])

    def test_wrong_import_or_presented_route_rejected(self):
        with self.assertRaises(ValueError):
            colour_handoff_summary(log_lines(0), 1)
        lines = log_lines(1)
        lines[0] = lines[0].replace('metadata-only', 'original-bl-el-reimport')
        with self.assertRaises(ValueError):
            colour_handoff_summary(lines, 1)

    def test_invalid_missing_or_reset_handoff_rejected(self):
        for edit in (
            lambda line: line.replace('valid=true', 'valid=false'),
            lambda line: line.replace('scope=' + SCOPE, 'scope=wrong'),
            lambda line: line.replace('calls=240', 'calls=120'),
            lambda line: line.replace('wall_ms_per_call=1.500', 'wall_ms_per_call=nan'),
        ):
            with self.assertRaises(ValueError):
                colour_handoff_summary([edit(line) for line in log_lines()], 0)

    def test_integer_fallback_and_missing_accepted_work_rejected(self):
        for edit in (lambda line: line.replace('accepted_integer=0', 'accepted_integer=1'),
                     lambda line: line.replace('accepted_fp32=240', 'accepted_fp32=0')):
            with self.assertRaises(ValueError):
                colour_handoff_summary([edit(line) for line in log_lines()], 0)

    def test_process_cpu_is_whole_process_not_gpu(self):
        summary = process_cpu_summary(cpu_samples())
        self.assertEqual(summary['process_cpu_seconds'], 0.2)
        self.assertEqual(summary['average_percent_of_one_cpu'], 20.0)

    def test_cpu_pid_reuse_or_regression_rejected(self):
        for key, value in (('pid', 11), ('process_start_ticks', 101),
                           ('process_cpu_ticks', 0), ('monotonic_ns', 0)):
            samples = cpu_samples()
            samples[-1][key] = value
            with self.assertRaises(ValueError):
                process_cpu_summary(samples)

    def test_report_stop_identity_and_native_fallback_gates(self):
        service = 'MainPID=1\nActiveEnterTimestampMonotonic=100\n'
        runtime = {'binary_sha256': '0' * 64, 'service': service}
        report = {'failure_marker': False, 'log_rotated_or_truncated': False,
                  'kodi_before': service, 'kodi_after': service, 'runtime_before': runtime,
                  'runtime_after': runtime, 'selected_log_lines': log_lines(),
                  'gpu_samples': cpu_samples()}
        stop = {'active_players': [], 'runtime': runtime}
        self.assertTrue(validate_report(report, stop, 0, '0' * 64)
                        ['observer_and_player_stop_integrity_passed'])
        bad_stop = copy.deepcopy(stop)
        bad_stop['runtime']['service'] = 'MainPID=2\nActiveEnterTimestampMonotonic=200\n'
        with self.assertRaises(ValueError):
            validate_report(report, bad_stop, 0, '0' * 64)
        report['selected_log_lines'].append('DVBridge native reconstruction: fallback=release')
        with self.assertRaises(ValueError):
            validate_report(report, stop, 0, '0' * 64)

    def test_argument_bounds_and_flag_only_configs(self):
        with tempfile.TemporaryDirectory() as temp:
            base = ['--binary-sha256', '0' * 64, '--root', temp, '--observer',
                    str(Path(__file__).with_name('observe_native_movie.py')),
                    '--movie-id', '51', '--expected-title', '1917']
            args = parser().parse_args(base)
            validate_args(args)
            for key, value in (('seconds', 74), ('seconds', 901), ('startup_settle_seconds', 19),
                               ('startup_settle_seconds', 61), ('movie_id', 0), ('seek_seconds', -1)):
                bad = copy.copy(args)
                setattr(bad, key, value)
                with self.assertRaises(ValueError):
                    validate_args(bad)

    def test_abba_flags_and_finally_no_start_stop_or_kill(self):
        tree = ast.parse(Path(__file__).with_name('run_colour_import_matrix.py').read_text())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        loop = next(node for node in ast.walk(main) if isinstance(node, ast.For))
        self.assertEqual(ast.literal_eval(loop.iter.args[0]), (0, 1, 1, 0))
        final = next(node.finalbody for node in ast.walk(main) if isinstance(node, ast.Try))
        command_calls = [node for item in final for node in ast.walk(item)
                         if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                         and node.func.id == 'command']
        self.assertEqual([[arg.value for arg in call.args] for call in command_calls],
                         [['systemctl', 'daemon-reload']])

    def test_startup_settle_and_journal_boundary_precede_playback(self):
        tree = ast.parse(Path(__file__).with_name('run_colour_import_matrix.py').read_text())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        loop = next(node for node in ast.walk(main) if isinstance(node, ast.For))
        boundary = next(i for i, node in enumerate(loop.body) if isinstance(node, ast.Assign)
                        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'journal_start')
        start = next(i for i, node in enumerate(loop.body) if isinstance(node, ast.Expr)
                     and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                     and node.value.func.id == 'command'
                     and [arg.value for arg in node.value.args] == ['systemctl', 'start', 'kodi'])
        settle = next(i for i, node in enumerate(loop.body) if isinstance(node, ast.Expr)
                      and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                      and node.value.func.attr == 'sleep')
        observe = next(i for i, node in enumerate(loop.body) if isinstance(node, ast.Assign)
                       and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'observer')
        self.assertLess(boundary, start)
        self.assertLess(start, settle)
        self.assertLess(settle, observe)


if __name__ == '__main__':
    unittest.main()
