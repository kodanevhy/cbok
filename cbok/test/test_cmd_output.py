import contextlib
import io
import logging
import unittest
from unittest import mock

from cbok.cmd import output


class CommandOutputTest(unittest.TestCase):
    def test_print_list_renders_named_columns_and_rows(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            output.print_list(
                [("Office Wi-Fi", "*.local"), ("Office Wi-Fi", "localhost")],
                ("Service", "Domain"),
            )

        text = stream.getvalue()
        self.assertIn("| Service", text)
        self.assertIn("| Domain", text)
        self.assertIn("| Office Wi-Fi | *.local", text)
        self.assertIn("| Office Wi-Fi | localhost", text)

    def test_print_list_marks_missing_values(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            output.print_list([(None,)], ("Value",))

        self.assertIn("| -", stream.getvalue())

    def test_fail_logs_and_prints_plain_error_then_exits(self):
        stderr = io.StringIO()
        with mock.patch.object(output, "LOG") as log:
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exited:
                    output.fail("bypass failed")

        self.assertEqual(1, exited.exception.code)
        log.error.assert_called_once_with("%s", "bypass failed", exc_info=False)
        self.assertEqual("bypass failed\n", stderr.getvalue())

    def test_fail_preserves_requested_exit_code_and_exception_in_log(self):
        stderr = io.StringIO()
        log_output = io.StringIO()
        handler = logging.StreamHandler(log_output)
        logger = output.LOG

        with mock.patch.object(logger, "handlers", [handler]), \
                mock.patch.object(logger, "propagate", False), \
                mock.patch.object(logger, "level", logging.DEBUG), \
                contextlib.redirect_stderr(stderr):
            try:
                raise RuntimeError("failed on remote host")
            except RuntimeError:
                with self.assertRaises(SystemExit) as exited:
                    output.fail("Shell command failed", exit_code=9, exc_info=True)

        self.assertEqual(9, exited.exception.code)
        self.assertEqual("Shell command failed\n", stderr.getvalue())
        self.assertIn("RuntimeError: failed on remote host", log_output.getvalue())


if __name__ == "__main__":
    unittest.main()
