import contextlib
import io
import subprocess
import unittest
from unittest import mock

from cbok.cmd import zsv


class ZsvStatusOutputTest(unittest.TestCase):
    def run_status(self, remote_output, returncode=0):
        command = zsv.ZSphereCommands()
        command.p_runner = mock.Mock()
        command.p_runner.run_command.return_value = subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=remote_output, stderr="")
        stdout = io.StringIO()

        with mock.patch.object(command, "ensure_remote_scriptlet", return_value=None), \
                mock.patch.object(zsv, "discover_management_nodes", return_value=[
                    "192.0.2.10", "192.0.2.11"]), \
                contextlib.redirect_stdout(stdout):
            result = command.status(primary_node="192.0.2.10")

        rows = [
            [cell.strip() for cell in line.strip("|").split("|")]
            for line in stdout.getvalue().splitlines()
            if line.startswith("|")
        ]
        return result, rows, stdout.getvalue(), command.p_runner

    def test_status_prints_node_fields_in_one_table(self):
        result, rows, text, runner = self.run_status(
            "== ZSphere node 192.0.2.10 ==\n"
            "time: 2026-09-28T10:00:00+08:00\n"
            "hostname: mn-1\n"
            "-- zstack-ctl status --\n"
            "Version: 5.0.2 (ZStack-ZSphere 5.0.2.54)\n"
            "MN status: \x1b[32mRunning\x1b[0m [PID:42]\n"
            "UI status: \x1b[32mRunning\x1b[0m https://192.0.2.10:443\n"
            "== ZSphere node 192.0.2.11 ==\n"
            "hostname: storage-1\n"
            "zstack-ctl: missing\n"
        )

        self.assertEqual(0, result)
        self.assertEqual([
            ["Node", "Field", "Value"],
            ["192.0.2.10", "time", "2026-09-28T10:00:00+08:00"],
            ["192.0.2.10", "hostname", "mn-1"],
            ["192.0.2.10", "Version", "5.0.2 (ZStack-ZSphere 5.0.2.54)"],
            ["192.0.2.10", "MN status", "Running [PID:42]"],
            ["192.0.2.10", "UI status", "Running https://192.0.2.10:443"],
            ["192.0.2.11", "hostname", "storage-1"],
            ["192.0.2.11", "zstack-ctl", "missing"],
        ], rows)
        self.assertNotIn("\x1b[", text)
        self.assertNotIn("== ZSphere node", text)
        self.assertIn("zsv_nodes_status 192.0.2.10 192.0.2.11",
                      runner.run_command.call_args.args[0][2])

    def test_status_reports_shell_failures_without_partial_table(self):
        for stage, ensure_code, status_code in (
                ("ensure_remote_scriptlet", 255, 0),
                ("zsv_nodes_status", 0, 23)):
            with self.subTest(stage=stage):
                command = zsv.ZSphereCommands()
                command.p_runner = mock.Mock()
                command.p_runner.run_command.return_value = subprocess.CompletedProcess(
                    args=[], returncode=status_code,
                    stdout="== ZSphere node 192.0.2.10 ==\nhostname: mn-1\n", stderr="")
                ensure_result = subprocess.CompletedProcess(
                    args=[], returncode=ensure_code, stdout="", stderr="")
                stdout = io.StringIO()
                stderr = io.StringIO()

                with mock.patch.object(command, "ensure_remote_scriptlet",
                                       return_value=ensure_result), \
                        mock.patch.object(zsv, "discover_management_nodes",
                                          return_value=["192.0.2.10"]) as discover, \
                        mock.patch.object(zsv.output, "LOG") as log, \
                        contextlib.redirect_stdout(stdout), \
                        contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as failure:
                        command.status(primary_node="192.0.2.10")

                exit_code = ensure_code or status_code
                message = f"Shell command failed (exit code {exit_code})."
                self.assertEqual(exit_code, failure.exception.code)
                self.assertEqual(message + "\n", stderr.getvalue())
                self.assertEqual("", stdout.getvalue())
                log.error.assert_called_once_with("%s", message, exc_info=False)
                if ensure_code:
                    discover.assert_not_called()
                    command.p_runner.run_command.assert_not_called()

    def test_status_rejects_empty_success_output(self):
        stderr = io.StringIO()
        with self.assertLogs("cbok.cmd.output", level="ERROR"), \
                contextlib.redirect_stderr(stderr), \
                self.assertRaises(SystemExit) as failure:
            self.run_status("ssh banner without status data\n")

        self.assertEqual(1, failure.exception.code)
        self.assertIn("No ZSphere node status data returned.", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
