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

    def test_master_source_branch_is_allowed_without_remote_check(self):
        def runner(cmd, **_kwargs):
            if cmd[-2:] == ["branch", "--show-current"]:
                return self.completed(stdout="master\n")
            if cmd[-4:] == ["ls-remote", "--exit-code", "origin", "refs/heads/master"]:
                self.fail("source guard must not query remote on command startup")
            self.fail("unexpected command: %s" % cmd)

        err = io.StringIO()

        cmd_main._ensure_source_branch_is_master(
            project_root="/repo/cbok",
            runner=runner,
            stderr=err,
        )

        self.assertEqual("", err.getvalue())

    def test_rebase_command_is_allowed_to_fix_non_master_source_branch(self):
        def runner(*_args, **_kwargs):
            self.fail("rebase must bypass source branch guard")

        err = io.StringIO()

        cmd_main._ensure_source_branch_is_master(
            project_root="/repo/cbok",
            runner=runner,
            stderr=err,
            argv=["rebase"],
        )

        self.assertEqual("", err.getvalue())

    def test_debug_rebase_command_is_allowed_to_fix_non_master_source_branch(self):
        def runner(*_args, **_kwargs):
            self.fail("debug rebase must bypass source branch guard")

        err = io.StringIO()

        cmd_main._ensure_source_branch_is_master(
            project_root="/repo/cbok",
            runner=runner,
            stderr=err,
            argv=["--debug", "rebase"],
        )

        self.assertEqual("", err.getvalue())

    def test_non_master_source_branch_exits_with_rebase_command(self):
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
        self.assertIn("cbok rebase", message)
        self.assertNotIn("cd /repo/cbok", message)
        self.assertNotIn("git status --short --branch", message)
        self.assertNotIn("git checkout master", message)
        self.assertNotIn("git fetch origin", message)
        self.assertNotIn("git rebase origin/master", message)
        self.assertIn("Remember to rebase", message)


if __name__ == "__main__":
    unittest.main()
