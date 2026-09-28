import io
import logging
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from unittest import mock

from cbok.cmd import main as cmd_main


class CommandLoggingTest(unittest.TestCase):
    def capture_logs(self, debug=False):
        logger = logging.Logger("cbok-test")
        console_output = io.StringIO()
        file_output = io.StringIO()
        console = logging.StreamHandler(console_output)
        console.name = "console"
        file_handler = logging.StreamHandler(file_output)
        file_handler.name = "file"
        logger.addHandler(console)
        logger.addHandler(file_handler)

        with mock.patch.object(cmd_main.logging, "getLogger", return_value=logger):
            cmd_main.setup_logging_level(debug=debug)

        for level, message in ((logging.DEBUG, "debug"),
                               (logging.INFO, "info"),
                               (logging.ERROR, "error")):
            logger.log(level, message)
        return console_output.getvalue(), file_output.getvalue()

    def test_all_commands_without_debug_write_all_levels_only_to_file(self):
        console, file_output = self.capture_logs()
        self.assertEqual("", console)
        self.assertEqual("debug\ninfo\nerror\n", file_output)

    def test_debug_writes_all_levels_to_both(self):
        console, file_output = self.capture_logs(debug=True)
        self.assertEqual("debug\ninfo\nerror\n", console)
        self.assertEqual(console, file_output)

    def run_cli(self, command, debug=False):
        root = logging.getLogger()
        stderr = io.StringIO()
        file_output = io.StringIO()
        console = logging.StreamHandler(stderr)
        console.name = "console"
        file_handler = logging.StreamHandler(file_output)
        file_handler.name = "file"
        argv = ["cbok"] + (["--debug"] if debug else []) + ["sample"]
        groups = [("default", None, [("sample", command)])]

        with mock.patch.object(root, "handlers", [console, file_handler]), \
                mock.patch.object(root, "level", logging.WARNING), \
                mock.patch.object(cmd_main, "_ensure_source_branch_is_master"), \
                mock.patch.object(cmd_main, "_resolve_and_reexec_venv"), \
                mock.patch.object(cmd_main.django, "setup"), \
                mock.patch.object(cmd_main.os, "chdir"), \
                mock.patch("cbok.utils.assert_cbok_home", return_value=os.getcwd()), \
                mock.patch("cbok.utils.discover_command_groups", return_value=groups), \
                mock.patch.object(sys, "argv", argv), \
                redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as exited:
                cmd_main.main()
        return exited.exception.code, stderr.getvalue(), file_output.getvalue()

    def test_non_bypass_python_error_is_plain_text_without_debug(self):
        def fail():
            raise ValueError("invalid input")

        code, stderr, log = self.run_cli(fail)

        self.assertEqual(1, code)
        self.assertEqual("invalid input\n", stderr)
        self.assertIn("ValueError: invalid input", log)

    def test_nonzero_status_is_forwarded_without_fallback_message(self):
        def fail():
            logging.getLogger("cbok.test").error("remote command failed")
            return 7

        code, stderr, log = self.run_cli(fail)

        self.assertEqual(7, code)
        self.assertEqual("", stderr)
        self.assertIn("remote command failed", log)

    def test_subprocess_error_does_not_expose_command_or_output(self):
        def fail():
            raise subprocess.CalledProcessError(
                9, ["ssh", "private-host"], output="private remote output")

        code, stderr, log = self.run_cli(fail)

        self.assertEqual(9, code)
        self.assertIn("Shell command failed (exit code 9)", stderr)
        self.assertNotIn("private-host", stderr)
        self.assertNotIn("private remote output", stderr)
        self.assertIn("CalledProcessError", log)


if __name__ == "__main__":
    unittest.main()
