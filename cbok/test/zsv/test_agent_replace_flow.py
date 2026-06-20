import os
import shutil
import subprocess
import tempfile
import unittest

from cbok.bbx.zsv import agent_replace


class FakeRunner:
    def __init__(self):
        self.commands = []

    def run_command(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


class AgentReplaceFlowTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.repo)

    def touch(self, path):
        full_path = os.path.join(self.repo, *path.split("/"))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as fd:
            fd.write("# test\n")

    def test_dry_run_validates_scope_without_remote_commands(self):
        self.touch("kvmagent/kvmagent/plugins/vm_plugin.py")

        runner = FakeRunner()
        rc = agent_replace.run_agent_replace_flow(
            utility_root=self.repo,
            nodes="172.26.53.17,172.26.53.18",
            dry_run=True,
            no_restart=False,
            runner=runner,
            changed_paths=["kvmagent/kvmagent/plugins/vm_plugin.py"],
        )

        self.assertEqual(0, rc)
        self.assertEqual([], runner.commands)

    def test_rejects_out_of_scope_change_before_remote_commands(self):
        self.touch("kvmagent/ansible/kvm.py")

        runner = FakeRunner()
        rc = agent_replace.run_agent_replace_flow(
            utility_root=self.repo,
            nodes="172.26.53.17",
            dry_run=False,
            no_restart=False,
            runner=runner,
            changed_paths=["kvmagent/ansible/kvm.py"],
        )

        self.assertEqual(1, rc)
        self.assertEqual([], runner.commands)

    def test_executes_stage_and_apply_for_each_node(self):
        self.touch("zstacklib/zstacklib/utils/linux.py")

        ensured = []
        runner = FakeRunner()
        rc = agent_replace.run_agent_replace_flow(
            utility_root=self.repo,
            nodes="172.26.53.17,172.26.53.18",
            dry_run=False,
            no_restart=True,
            runner=runner,
            ensure_remote_scriptlet=lambda node: ensured.append(node),
            changed_paths=["zstacklib/zstacklib/utils/linux.py"],
        )

        self.assertEqual(0, rc)
        self.assertEqual(["172.26.53.17", "172.26.53.18"], ensured)
        joined = "\n".join(" ".join(cmd) for cmd, _ in runner.commands)
        self.assertIn("zsv_agent_stage_archive", joined)
        self.assertIn("zsv_agent_apply_staging", joined)
