import subprocess
import unittest
from unittest import mock

from cbok.cmd import base
from cbok.cmd.base import DefaultCommands


class FakeRunner:
    def __init__(self, responses=None, returncodes=None):
        self.commands = []
        self.kwargs = []
        self.responses = list(responses or [])
        self.returncodes = list(returncodes or [])

    def run_command(self, cmd, **kwargs):
        self.commands.append(cmd)
        self.kwargs.append(kwargs)
        if self.responses:
            response = self.responses.pop(0)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=response.get("returncode", 0),
                stdout=response.get("stdout", ""),
                stderr=response.get("stderr", ""),
            )
        returncode = self.returncodes.pop(0) if self.returncodes else 0
        return subprocess.CompletedProcess(args=cmd, returncode=returncode, stdout="", stderr="")


class DefaultCommandsTest(unittest.TestCase):
    def test_rebase_checks_out_master_fetches_origin_and_rebases(self):
        command = DefaultCommands(project_root="/repo/cbok")
        runner = FakeRunner()
        command.p_runner = runner

        result = command.rebase()

        self.assertEqual(0, result)
        self.assertEqual(
            [
                ["git", "-C", "/repo/cbok", "status", "--porcelain"],
                ["git", "-C", "/repo/cbok", "checkout", "master"],
                ["git", "-C", "/repo/cbok", "fetch", "origin"],
                ["git", "-C", "/repo/cbok", "rebase", "origin/master"],
            ],
            runner.commands,
        )
        self.assertEqual(False, runner.kwargs[0]["log_output"])

    def test_rebase_stops_on_first_failed_git_command(self):
        command = DefaultCommands(project_root="/repo/cbok")
        runner = FakeRunner(responses=[
            {"stdout": ""},
            {"returncode": 1},
        ])
        command.p_runner = runner

        result = command.rebase()

        self.assertEqual(1, result)
        self.assertEqual(
            [
                ["git", "-C", "/repo/cbok", "status", "--porcelain"],
                ["git", "-C", "/repo/cbok", "checkout", "master"],
            ],
            runner.commands,
        )

    def test_rebase_reports_unexpected_dirty_checkout_before_checkout(self):
        command = DefaultCommands(project_root="/repo/cbok")
        runner = FakeRunner(responses=[
            {"stdout": " M cbok/cmd/zsv.py\n?? scratch.py\n"},
        ])
        command.p_runner = runner

        with self.assertLogs("cbok.cmd.base", level="ERROR") as logs:
            result = command.rebase()

        self.assertEqual(1, result)
        self.assertEqual(
            [["git", "-C", "/repo/cbok", "status", "--porcelain"]],
            runner.commands,
        )
        self.assertEqual(False, runner.kwargs[0]["log_output"])
        message = "\n".join(logs.output)
        self.assertIn("Unexpected dirty CBoK source checkout before rebase", message)
        self.assertNotIn("cbok/cmd/zsv.py", message)
        self.assertNotIn("scratch.py", message)
        self.assertNotIn("Please commit your changes", message)

    def test_rebase_force_abort_discards_changes_before_rebase(self):
        command = DefaultCommands(project_root="/repo/cbok")
        runner = FakeRunner(responses=[
            {"returncode": 1, "stderr": "fatal: No rebase in progress?\n"},
            {},
            {},
            {},
            {},
            {},
        ])
        command.p_runner = runner

        with mock.patch("builtins.input", return_value="yes") as prompt:
            result = command.rebase(force_abort=True)

        self.assertEqual(0, result)
        self.assertEqual(base.FORCE_ABORT_PROMPT, prompt.call_args[0][0])
        self.assertEqual(
            [
                ["git", "-C", "/repo/cbok", "rebase", "--abort"],
                ["git", "-C", "/repo/cbok", "reset", "--hard"],
                ["git", "-C", "/repo/cbok", "clean", "-fd"],
                ["git", "-C", "/repo/cbok", "checkout", "master"],
                ["git", "-C", "/repo/cbok", "fetch", "origin"],
                ["git", "-C", "/repo/cbok", "rebase", "origin/master"],
            ],
            runner.commands,
        )
        self.assertEqual(
            {"cmd_purge_output": False, "log_output": False, "log_failed_status": False},
            runner.kwargs[0],
        )

    def test_rebase_force_abort_stops_when_user_declines(self):
        command = DefaultCommands(project_root="/repo/cbok")
        runner = FakeRunner()
        command.p_runner = runner

        with mock.patch("builtins.input", return_value="no") as prompt:
            with self.assertLogs("cbok.cmd.base", level="ERROR") as logs:
                result = command.rebase(force_abort=True)

        self.assertEqual(1, result)
        self.assertEqual([], runner.commands)
        self.assertEqual(base.FORCE_ABORT_PROMPT, prompt.call_args[0][0])
        self.assertIn("Force abort cancelled", "\n".join(logs.output))

    def test_rebase_force_abort_stops_when_confirmation_is_unavailable(self):
        command = DefaultCommands(project_root="/repo/cbok")
        runner = FakeRunner()
        command.p_runner = runner

        with mock.patch("builtins.input", side_effect=EOFError):
            with self.assertLogs("cbok.cmd.base", level="ERROR") as logs:
                result = command.rebase(force_abort=True)

        self.assertEqual(1, result)
        self.assertEqual([], runner.commands)
        self.assertIn("Force abort requires interactive confirmation", "\n".join(logs.output))

    def test_rebase_force_abort_stops_when_reset_fails(self):
        command = DefaultCommands(project_root="/repo/cbok")
        runner = FakeRunner(responses=[
            {"returncode": 1},
            {"returncode": 2},
        ])
        command.p_runner = runner

        with mock.patch("builtins.input", return_value="yes"):
            result = command.rebase(force_abort=True)

        self.assertEqual(2, result)
        self.assertEqual(
            [
                ["git", "-C", "/repo/cbok", "rebase", "--abort"],
                ["git", "-C", "/repo/cbok", "reset", "--hard"],
            ],
            runner.commands,
        )


if __name__ == "__main__":
    unittest.main()
