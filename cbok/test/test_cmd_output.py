import contextlib
import io
import unittest

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


if __name__ == "__main__":
    unittest.main()
