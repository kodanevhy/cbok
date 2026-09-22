import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cbok.bbx.zsv import base_ref, zstore_replace


class FakeRunner:
    def __init__(self):
        self.commands = []

    def run_command(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "", "")


class ZstoreReplaceTest(unittest.TestCase):
    def setUp(self):
        rebase_patch = patch.object(base_ref, "rebase_worktree", return_value=True)
        self.rebase_worktree = rebase_patch.start()
        self.addCleanup(rebase_patch.stop)

    def test_build_and_deploy_all_nodes(self):
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "src/image-store"))
            out = os.path.join(root, "build/out/zstore")
            os.makedirs(out)
            for name in ("zstore", "zstcli"):
                with open(os.path.join(out, name), "wb") as stream:
                    stream.write(name.encode())

            def build(build_root, build_runner, image):
                self.rebase_worktree.assert_called_once_with(os.path.realpath(root))
                self.assertEqual(os.path.realpath(root), str(build_root))
                return 0

            with patch.object(zstore_replace, "_build", side_effect=build):
                rc = zstore_replace.run_zstore_replace_flow(
                    root, ["192.0.2.1", "192.0.2.2"], runner)

        self.assertEqual(0, rc)
        commands = "\n".join(" ".join(cmd) for cmd, _ in runner.commands)
        self.assertIn("192.0.2.1", commands)
        self.assertIn("192.0.2.2", commands)

    def test_rebase_failure_stops_before_build_or_deploy(self):
        runner = FakeRunner()
        self.rebase_worktree.return_value = False
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "src/image-store"))
            with patch.object(zstore_replace, "_build") as build, \
                    patch.object(zstore_replace, "_deploy_node") as deploy:
                rc = zstore_replace.run_zstore_replace_flow(root, ["192.0.2.1"], runner)
            self.rebase_worktree.assert_called_once_with(os.path.realpath(root))

        self.assertEqual(1, rc)
        build.assert_not_called()
        deploy.assert_not_called()
        self.assertEqual([], runner.commands)

    def test_rejects_invalid_root(self):
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as root:
            rc = zstore_replace.run_zstore_replace_flow(root, ["192.0.2.1"], runner)
        self.assertEqual(1, rc)
        self.assertEqual([], runner.commands)
        self.rebase_worktree.assert_not_called()
