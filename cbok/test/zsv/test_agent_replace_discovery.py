import os
import shutil
import tempfile
import unittest

from cbok.bbx.zsv import agent_replace


class AgentReplaceDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.repo)

    def touch(self, path):
        full_path = os.path.join(self.repo, *path.split("/"))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as fd:
            fd.write("# test\n")

    def test_maps_runtime_package_changes(self):
        self.touch("kvmagent/kvmagent/plugins/vm_plugin.py")
        self.touch("zstacklib/zstacklib/utils/linux.py")

        files = agent_replace.validate_changed_files(
            self.repo,
            [
                "kvmagent/kvmagent/plugins/vm_plugin.py",
                "zstacklib/zstacklib/utils/linux.py",
            ],
        )

        self.assertEqual("kvmagent/plugins/vm_plugin.py", files[0].remote_path)
        self.assertEqual("kvmagent", files[0].package_name)
        self.assertEqual("zstacklib/utils/linux.py", files[1].remote_path)
        self.assertEqual("zstacklib", files[1].package_name)

    def test_rejects_changes_outside_runtime_packages(self):
        self.touch("kvmagent/ansible/kvm.py")

        with self.assertRaises(agent_replace.AgentReplaceError) as ctx:
            agent_replace.validate_changed_files(
                self.repo,
                ["kvmagent/ansible/kvm.py"],
            )

        self.assertIn("outside kvmagent/zstacklib runtime scope", str(ctx.exception))

    def test_rejects_deleted_runtime_file(self):
        with self.assertRaises(agent_replace.AgentReplaceError) as ctx:
            agent_replace.validate_changed_files(
                self.repo,
                ["kvmagent/kvmagent/plugins/deleted.py"],
            )

        self.assertIn("does not exist", str(ctx.exception))

    def test_discovers_top_commit_worktree_index_and_untracked_changes(self):
        calls = []
        outputs = {
            ("git", "diff", "--name-only", "--diff-filter=ACMRTD", "HEAD^", "HEAD"): "kvmagent/kvmagent/a.py\n",
            ("git", "diff", "--name-only", "--diff-filter=ACMRTD"): "zstacklib/zstacklib/b.py\n",
            ("git", "diff", "--name-only", "--cached", "--diff-filter=ACMRTD"): "kvmagent/kvmagent/a.py\n",
            ("git", "ls-files", "--others", "--exclude-standard"): "zstacklib/zstacklib/c.py\n",
        }

        def runner(cmd, cwd=None):
            calls.append(tuple(cmd))
            return outputs.get(tuple(cmd), "")

        result = agent_replace.discover_changed_files(
            self.repo,
            command_runner=runner,
        )

        self.assertEqual(
            [
                "kvmagent/kvmagent/a.py",
                "zstacklib/zstacklib/b.py",
                "zstacklib/zstacklib/c.py",
            ],
            result.paths,
        )
        self.assertEqual("HEAD^..HEAD", result.change_scope)
        self.assertIn(("git", "ls-files", "--others", "--exclude-standard"), calls)

    def test_parse_nodes_deduplicates_comma_and_whitespace_values(self):
        nodes = agent_replace.parse_nodes("172.26.53.17, 172.26.53.18\n172.26.53.17")

        self.assertEqual(["172.26.53.17", "172.26.53.18"], nodes)
