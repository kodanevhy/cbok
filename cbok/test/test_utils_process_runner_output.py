import contextlib
import inspect
import io
import sys
import unittest

from cbok.utils import UnifiedProcessRunner


class ProcessRunnerOutputTest(unittest.TestCase):
    def test_runner_has_no_output_purge_parameter(self):
        self.assertNotIn("cmd_purge_output", inspect.signature(UnifiedProcessRunner.run_command).parameters)
        self.assertNotIn("cmd_purge_output", inspect.signature(UnifiedProcessRunner.run_shell_script).parameters)

    def test_output_uses_log_prefix_instead_of_raw_stdout(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertLogs("cbok.utils", level="INFO") as logs:
                result = UnifiedProcessRunner().run_command(
                    [sys.executable, "-c", "print('result line')"],
                )

        self.assertEqual(0, result.returncode)
        self.assertEqual("result line", result.stdout)
        self.assertEqual("", stdout.getvalue())
        self.assertTrue(any("print('result line')" in line for line in logs.output))
        self.assertIn("INFO:cbok.utils:[SHELL] result line", logs.output)
