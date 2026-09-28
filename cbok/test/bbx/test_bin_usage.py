import contextlib
import io
import unittest
from unittest import mock

from cbok.cmd import bbx


class BinUsageTest(unittest.TestCase):
    def run_usage(self, python_versions, current_python, go_path, go_version):
        command = bbx.BinCommands()
        stdout = io.StringIO()
        paths = {"python": current_python, "go": go_path}

        with mock.patch.object(command, "_find_all_pythons", return_value=python_versions), \
                mock.patch.object(command, "_find_go", return_value=(go_path, go_version)), \
                mock.patch.object(bbx.shutil, "which", side_effect=paths.get), \
                contextlib.redirect_stdout(stdout):
            result = command.usage()

        rows = [
            [cell.strip() for cell in line.strip("|").split("|")]
            for line in stdout.getvalue().splitlines()
            if line.startswith("|")
        ]
        return result, rows, stdout.getvalue()

    def test_usage_prints_one_table_for_python_and_go(self):
        result, rows, text = self.run_usage(
            {
                "/usr/local/bin/python3": "Python 3.12.1",
                "/usr/bin/python": "Python 3.9.6",
            },
            "/usr/bin/python",
            "/opt/go/bin/go",
            "go version go1.22.0 darwin/arm64",
        )

        self.assertEqual(0, result)
        self.assertEqual([
            ["Runtime", "Path", "Version", "Default"],
            ["Python", "/usr/bin/python", "Python 3.9.6", "Yes"],
            ["Python", "/usr/local/bin/python3", "Python 3.12.1", "No"],
            ["Go", "/opt/go/bin/go", "go version go1.22.0 darwin/arm64", "Yes"],
        ], rows)
        self.assertNotIn("Python versions found:", text)
        self.assertNotIn("Go version:", text)

    def test_usage_shows_missing_runtimes_in_the_table(self):
        result, rows, text = self.run_usage({}, None, None, "not found")

        self.assertEqual(0, result)
        self.assertEqual([
            ["Runtime", "Path", "Version", "Default"],
            ["Python", "-", "Not found", "No"],
            ["Go", "-", "Not found", "No"],
        ], rows)
        self.assertNotIn("No Python found", text)


if __name__ == "__main__":
    unittest.main()
