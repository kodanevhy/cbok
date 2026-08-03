import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cbok.bbx.zsv import zstore_replace


class FakeRunner:
    def __init__(self):
        self.commands = []

    def run_command(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "", "")


class ZstoreReplaceTest(unittest.TestCase):
    def test_build_and_deploy_all_nodes(self):
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "src/image-store"))
            out = os.path.join(root, "build/out/zstore")
            os.makedirs(out)
            for name in ("zstore", "zstcli"):
                with open(os.path.join(out, name), "wb") as stream:
                    stream.write(name.encode())

            with patch.object(zstore_replace, "_build", return_value=0):
                rc = zstore_replace.run_zstore_replace_flow(
                    root, ["192.0.2.1", "192.0.2.2"], runner)

        self.assertEqual(0, rc)
        commands = "\n".join(" ".join(cmd) for cmd, _ in runner.commands)
        self.assertIn("192.0.2.1", commands)
        self.assertIn("192.0.2.2", commands)

    def test_rejects_invalid_root(self):
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as root:
            rc = zstore_replace.run_zstore_replace_flow(root, ["192.0.2.1"], runner)
        self.assertEqual(1, rc)
        self.assertEqual([], runner.commands)
