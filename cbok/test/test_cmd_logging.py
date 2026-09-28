import io
import logging
import unittest
from unittest import mock

from cbok.cmd import main as cmd_main


class CommandLoggingTest(unittest.TestCase):
    def capture_logs(self, debug=False, file_only=False):
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
            cmd_main.setup_logging_level(debug=debug, file_only=file_only)

        for level, message in ((logging.DEBUG, "debug"),
                               (logging.INFO, "info"),
                               (logging.ERROR, "error")):
            logger.log(level, message)
        return console_output.getvalue(), file_output.getvalue()

    def test_bypass_without_debug_writes_all_levels_only_to_file(self):
        console, file_output = self.capture_logs(file_only=True)
        self.assertEqual("", console)
        self.assertEqual("debug\ninfo\nerror\n", file_output)

    def test_bypass_with_debug_writes_all_levels_to_both(self):
        console, file_output = self.capture_logs(debug=True, file_only=True)
        self.assertEqual("debug\ninfo\nerror\n", console)
        self.assertEqual(console, file_output)

    def test_other_commands_keep_current_info_console_behavior(self):
        console, file_output = self.capture_logs()
        self.assertEqual("info\nerror\n", console)
        self.assertEqual(console, file_output)


if __name__ == "__main__":
    unittest.main()
