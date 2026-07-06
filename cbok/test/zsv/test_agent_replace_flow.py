import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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

    def discovery_runner(self, paths):
        outputs = {
            ("git", "diff", "--name-only", "--diff-filter=ACMRTD", "HEAD^", "HEAD"): "\n".join(paths),
            ("git", "diff", "--name-only", "--diff-filter=ACMRTD"): "",
            ("git", "diff", "--name-only", "--cached", "--diff-filter=ACMRTD"): "",
            ("git", "ls-files", "--others", "--exclude-standard"): "",
        }

        def runner(cmd, cwd=None):
            return outputs.get(tuple(cmd), "")

        return runner

    def capture_archive_files(self, captured):
        def create(files):
            captured.extend(file.repo_path for file in files)
            fd, archive_path = tempfile.mkstemp(prefix="cbok-test-agent-", suffix=".tar.gz")
            os.close(fd)
            return archive_path

        return create

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

    def test_executes_ceph_primary_files_on_ceph_nodes_only(self):
        self.touch("cephprimarystorage/cephprimarystorage/cephagent.py")

        ensured = []
        runner = FakeRunner()
        rc = agent_replace.run_agent_replace_flow(
            utility_root=self.repo,
            nodes="172.26.53.17",
            ceph_primary_nodes="172.24.190.50",
            dry_run=False,
            no_restart=True,
            runner=runner,
            ensure_remote_scriptlet=lambda node: ensured.append(node),
            changed_paths=["cephprimarystorage/cephprimarystorage/cephagent.py"],
        )

        self.assertEqual(0, rc)
        self.assertEqual(["172.24.190.50"], ensured)
        joined = "\n".join(" ".join(cmd) for cmd, _ in runner.commands)
        self.assertIn("zstack-ceph-primarystorage", joined)
        self.assertNotIn("172.26.53.17", joined)

    def test_executes_zbs_primary_files_on_zbs_nodes_only(self):
        self.touch("zbsprimarystorage/zbsprimarystorage/zbsagent.py")

        ensured = []
        runner = FakeRunner()
        rc = agent_replace.run_agent_replace_flow(
            utility_root=self.repo,
            nodes="172.26.53.17",
            zbs_primary_nodes="172.24.241.203",
            dry_run=False,
            no_restart=True,
            runner=runner,
            ensure_remote_scriptlet=lambda node: ensured.append(node),
            changed_paths=["zbsprimarystorage/zbsprimarystorage/zbsagent.py"],
        )

        self.assertEqual(0, rc)
        self.assertEqual(["172.24.241.203"], ensured)
        joined = "\n".join(" ".join(cmd) for cmd, _ in runner.commands)
        self.assertIn("zstack-zbs-primarystorage", joined)
        self.assertNotIn("172.26.53.17", joined)

    def test_auto_discovery_replays_previous_deployed_files_removed_from_current_diff(self):
        current_path = "kvmagent/kvmagent/plugins/current.py"
        previous_path = "kvmagent/kvmagent/plugins/previous.py"
        self.touch(current_path)
        self.touch(previous_path)
        state_store = agent_replace.InMemoryAgentReplaceStateStore()
        worktree_key = agent_replace.agent_replace_worktree_key(self.repo)
        state_store.save_paths(worktree_key, self.repo, [previous_path])

        captured = []
        runner = FakeRunner()
        with patch.object(agent_replace, "create_agent_archive", side_effect=self.capture_archive_files(captured)):
            rc = agent_replace.run_agent_replace_flow(
                utility_root=self.repo,
                nodes="172.26.53.17",
                dry_run=False,
                no_restart=True,
                runner=runner,
                command_runner=self.discovery_runner([current_path]),
                state_store=state_store,
            )

        self.assertEqual(0, rc)
        self.assertEqual([current_path, previous_path], captured)
        self.assertEqual([current_path], state_store.load_paths(worktree_key))

    def test_auto_discovery_replays_previous_files_when_current_diff_is_empty(self):
        previous_path = "kvmagent/kvmagent/plugins/previous.py"
        self.touch(previous_path)
        state_store = agent_replace.InMemoryAgentReplaceStateStore()
        worktree_key = agent_replace.agent_replace_worktree_key(self.repo)
        state_store.save_paths(worktree_key, self.repo, [previous_path])

        captured = []
        runner = FakeRunner()
        with patch.object(agent_replace, "create_agent_archive", side_effect=self.capture_archive_files(captured)):
            rc = agent_replace.run_agent_replace_flow(
                utility_root=self.repo,
                nodes="172.26.53.17",
                dry_run=False,
                no_restart=True,
                runner=runner,
                command_runner=self.discovery_runner([]),
                state_store=state_store,
            )

        self.assertEqual(0, rc)
        self.assertEqual([previous_path], captured)
        self.assertEqual([], state_store.load_paths(worktree_key))
