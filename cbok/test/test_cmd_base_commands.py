import subprocess
import unittest

from cbok.cmd.base import DefaultCommands


class FakeRunner:
    def __init__(self, returncodes=None):
        self.commands = []
        self.returncodes = list(returncodes or [])

    def run_command(self, cmd):
        self.commands.append(cmd)
        returncode = self.returncodes.pop(0) if self.returncodes else 0
        return subprocess.CompletedProcess(args=cmd, returncode=returncode)


class DefaultCommandsTest(unittest.TestCase):
    def test_rebase_checks_out_master_fetches_origin_and_rebases(self):
        command = DefaultCommands(project_root="/repo/cbok")
        runner = FakeRunner()
        command.p_runner = runner

        result = command.rebase()

        self.assertEqual(0, result)
        self.assertEqual(
            [
                ["git", "-C", "/repo/cbok", "checkout", "master"],
                ["git", "-C", "/repo/cbok", "fetch", "origin"],
                ["git", "-C", "/repo/cbok", "rebase", "origin/master"],
            ],
            runner.commands,
        )

    def test_rebase_stops_on_first_failed_git_command(self):
        command = DefaultCommands(project_root="/repo/cbok")
        runner = FakeRunner(returncodes=[1])
        command.p_runner = runner

        result = command.rebase()

        self.assertEqual(1, result)
        self.assertEqual(
            [["git", "-C", "/repo/cbok", "checkout", "master"]],
            runner.commands,
        )


if __name__ == "__main__":
    unittest.main()
