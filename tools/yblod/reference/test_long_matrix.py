import ast
import contextlib
import io
from pathlib import Path
import unittest
from run_long_matrix import argument_parser, identity, playback_cases


class MatrixArgumentsTests(unittest.TestCase):
    def test_full_case_order(self):
        self.assertEqual(playback_cases(0), [
            (51, '1917', 0, 'integer'), (51, '1917', 0, 'fp32'),
            (51, '1917', 1200, 'fp32'), (51, '1917', 1200, 'integer'),
            (3391, 'Saving Private Ryan', 0, 'integer'),
            (3391, 'Saving Private Ryan', 0, 'fp32'),
            (3391, 'Saving Private Ryan', 1200, 'fp32'),
            (3391, 'Saving Private Ryan', 1200, 'integer'),
        ])

    def test_explicit_resume_runs_exact_remaining_six(self):
        self.assertEqual(playback_cases(2), playback_cases(0)[2:])
        self.assertEqual(len(playback_cases(2)), 6)

    def test_invalid_resume_index_is_rejected(self):
        for value in (-1, 1, 3, 7, 8):
            with self.assertRaises(ValueError):
                playback_cases(value)

    def test_parser_defaults_and_explicit_resume(self):
        base = ['--binary-sha256', '0' * 64, '--root', '/private/tmp/fresh',
                '--observer', '/private/tmp/observer.py']
        self.assertEqual(argument_parser().parse_args(base).start_case_index, 0)
        self.assertEqual(argument_parser().parse_args(base + ['--start-case-index', '2'])
                         .start_case_index, 2)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                argument_parser().parse_args(base + ['--start-case-index', '1'])

    def test_service_identity_ignores_memory_but_detects_restart(self):
        first = 'MainPID=100\nActiveEnterTimestampMonotonic=123\nMemoryCurrent=500\n'
        same = 'MemoryCurrent=900\nMainPID=100\nActiveEnterTimestampMonotonic=123\n'
        restart = 'MainPID=101\nActiveEnterTimestampMonotonic=456\n'
        self.assertEqual(identity(first), identity(same))
        self.assertNotEqual(identity(first), identity(restart))

    def test_journal_boundary_precedes_service_start_and_rpc_wait(self):
        tree = ast.parse(Path(__file__).with_name('run_long_matrix.py').read_text())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'main')
        loop = next(node for node in ast.walk(main) if isinstance(node, ast.For)
                    and isinstance(node.target, ast.Tuple) and len(node.target.elts) == 4)
        boundary = next(index for index, node in enumerate(loop.body)
                        if isinstance(node, ast.Assign) and any(
                            isinstance(target, ast.Name) and target.id == 'run_started'
                            for target in node.targets))
        start = next(index for index, node in enumerate(loop.body)
                     if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                     and isinstance(node.value.func, ast.Name) and node.value.func.id == 'command'
                     and [arg.value for arg in node.value.args if isinstance(arg, ast.Constant)]
                     == ['systemctl', 'start', 'kodi'])
        rpc_wait = next(index for index, node in enumerate(loop.body)
                        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Name)
                        and node.value.func.id == 'wait_rpc')
        self.assertLess(boundary, start)
        self.assertLess(start, rpc_wait)


if __name__ == '__main__':
    unittest.main()
