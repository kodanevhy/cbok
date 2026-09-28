import contextlib
import io
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
        log.error.assert_called_once_with("%s", "bypass failed")
        self.assertEqual("bypass failed\n", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
