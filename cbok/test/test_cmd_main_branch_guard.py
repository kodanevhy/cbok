import io
import os
import subprocess
import sys
import textwrap
import unittest

from cbok.cmd import main as cmd_main


class SourceBranchGuardTest(unittest.TestCase):
    def test_cmd_main_import_does_not_require_requests(self):
        script = textwrap.dedent(
            """
            import importlib.abc
            import sys

            class BlockRequests(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "requests" or fullname.startswith("requests."):
                        raise ImportError("blocked requests")
                    return None

            sys.meta_path.insert(0, BlockRequests())
            import cbok.cmd.main
            """
        )
        env = os.environ.copy()
        cwd = os.getcwd()
        env["PYTHONPATH"] = cwd + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=cwd,
        )

        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)

    def completed(self, stdout="", stderr="", returncode=0):
        return subprocess.CompletedProcess(
            args=["git", "branch", "--show-current"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def test_master_source_branch_is_allowed(self):
        def runner(cmd, **_kwargs):
            if cmd[-2:] == ["branch", "--show-current"]:
                return self.completed(stdout="master\n")
            if cmd[-2:] == ["rev-parse", "HEAD"]:
                return self.completed(stdout="abc123\n")
            if cmd[-4:] == ["ls-remote", "--exit-code", "origin", "refs/heads/master"]:
                return self.completed(stdout="abc123\trefs/heads/master\n")
            self.fail("unexpected command: %s" % cmd)

        err = io.StringIO()

        cmd_main._ensure_source_branch_is_master(
            project_root="/repo/cbok",
            runner=runner,
            stderr=err,
        )

        self.assertEqual("", err.getvalue())

    def test_master_source_branch_behind_remote_exits_with_manual_rebase_command(self):
        def runner(cmd, **_kwargs):
            if cmd[-2:] == ["branch", "--show-current"]:
                return self.completed(stdout="master\n")
            if cmd[-2:] == ["rev-parse", "HEAD"]:
                return self.completed(stdout="abc123\n")
            if cmd[-4:] == ["ls-remote", "--exit-code", "origin", "refs/heads/master"]:
                return self.completed(stdout="def456\trefs/heads/master\n")
            self.fail("unexpected command: %s" % cmd)

        err = io.StringIO()

        with self.assertRaises(SystemExit) as ctx:
            cmd_main._ensure_source_branch_is_master(
                project_root="/repo/cbok",
                runner=runner,
                stderr=err,
            )

        self.assertEqual(1, ctx.exception.code)
        message = err.getvalue()
        self.assertIn("not synced with origin/master", message)
        self.assertIn("local master: abc123", message)
        self.assertIn("remote master: def456", message)
        self.assertIn("git status --short --branch", message)
        self.assertIn("git fetch origin", message)
        self.assertIn("git rebase origin/master", message)

    def test_master_source_branch_remote_check_failure_exits_with_git_error(self):
        def runner(cmd, **_kwargs):
            if cmd[-2:] == ["branch", "--show-current"]:
                return self.completed(stdout="master\n")
            if cmd[-2:] == ["rev-parse", "HEAD"]:
                return self.completed(stdout="abc123\n")
            if cmd[-4:] == ["ls-remote", "--exit-code", "origin", "refs/heads/master"]:
                return self.completed(stderr="network unavailable\n", returncode=128)
            self.fail("unexpected command: %s" % cmd)

        err = io.StringIO()

        with self.assertRaises(SystemExit) as ctx:
            cmd_main._ensure_source_branch_is_master(
                project_root="/repo/cbok",
                runner=runner,
                stderr=err,
            )

        self.assertEqual(1, ctx.exception.code)
        message = err.getvalue()
        self.assertIn("not synced with origin/master", message)
        self.assertIn("local master: abc123", message)
        self.assertIn("remote master: unknown", message)
        self.assertIn("git error: network unavailable", message)

    def test_non_master_source_branch_exits_with_manual_checkout_and_rebase_commands(self):
        def runner(*_args, **_kwargs):
            return self.completed(stdout="codex/feature-work\n")

        err = io.StringIO()

        with self.assertRaises(SystemExit) as ctx:
            cmd_main._ensure_source_branch_is_master(
                project_root="/repo/cbok",
                runner=runner,
                stderr=err,
            )

        self.assertEqual(1, ctx.exception.code)
        message = err.getvalue()
        self.assertIn("codex/feature-work", message)
        self.assertIn("expected branch: master", message)
        self.assertIn("cd /repo/cbok", message)
        self.assertIn("git status --short --branch", message)
        self.assertIn("git checkout master", message)
        self.assertIn("git fetch origin", message)
        self.assertIn("git rebase origin/master", message)


if __name__ == "__main__":
    unittest.main()
