import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cbok.bbx.zsv import base_ref


class RebaseWorktreeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cbok git ")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.origin = root / "origin.git"
        self.upstream = root / "upstream"
        self.source = root / "source worktree"
        self.git(root, "init", "--bare", "--initial-branch=main", str(self.origin))
        self.git(root, "clone", str(self.origin), str(self.upstream))
        self.configure(self.upstream)
        self.commit(self.upstream, "shared.txt", "base\n")
        self.commit(self.upstream, "notes.txt", "original\n")
        self.git(self.upstream, "push", "origin", "main")
        self.git(root, "clone", str(self.origin), str(self.source))
        self.configure(self.source)
        self.git(self.source, "checkout", "-b", "feature")
        config = patch.object(base_ref, "zsv_base_ref", return_value="origin/main")
        config.start()
        self.addCleanup(config.stop)

    def git(self, root, *args, check=True):
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_TERMINAL_PROMPT="0", GIT_EDITOR="true")
        return subprocess.run(["git", "-C", str(root), *args], env=env,
                              text=True, capture_output=True, check=check)

    def configure(self, root):
        self.git(root, "config", "user.name", "CBoK Test")
        self.git(root, "config", "user.email", "cbok-test@example.invalid")

    def commit(self, root, name, content):
        (root / name).write_text(content)
        self.git(root, "add", name)
        self.git(root, "commit", "-m", name)

    def advance_upstream(self, name="upstream.txt", content="new upstream\n"):
        self.commit(self.upstream, name, content)
        self.git(self.upstream, "push", "origin", "main")

    def prepare(self):
        return base_ref.rebase_worktree(str(self.source))

    def test_rebases_patch_onto_fresh_upstream_before_build(self):
        self.commit(self.source, "patch.txt", "feature patch\n")
        self.advance_upstream()
        self.assertTrue(self.prepare())
        self.assertEqual(0, self.git(self.source, "merge-base", "--is-ancestor",
                                     "origin/main", "HEAD", check=False).returncode)
        self.assertEqual("feature", self.git(self.source, "branch", "--show-current").stdout.strip())
        self.assertEqual("feature patch\n", (self.source / "patch.txt").read_text())
        self.assertTrue((self.source / "upstream.txt").exists())

    def assert_dirty_rejected_without_fetch(self):
        before_head = self.git(self.source, "rev-parse", "HEAD").stdout
        before_status = self.git(self.source, "status", "--porcelain").stdout
        before_index = self.git(self.source, "show", ":notes.txt").stdout
        before_content = (self.source / "notes.txt").read_text()
        with patch.object(base_ref, "sync_base_ref", wraps=base_ref.sync_base_ref) as fetch:
            self.assertFalse(self.prepare())
            fetch.assert_not_called()
        self.assertEqual(before_head, self.git(self.source, "rev-parse", "HEAD").stdout)
        self.assertEqual(before_status, self.git(self.source, "status", "--porcelain").stdout)
        self.assertEqual(before_index, self.git(self.source, "show", ":notes.txt").stdout)
        self.assertEqual(before_content, (self.source / "notes.txt").read_text())
        self.assertEqual("", self.git(self.source, "stash", "list").stdout)

    def test_rejects_unstaged_edits_before_fetch_even_when_base_is_current(self):
        (self.source / "notes.txt").write_text("local changes\n")
        self.assert_dirty_rejected_without_fetch()

    def test_rejects_staged_edits_without_losing_distinct_index_content(self):
        (self.source / "notes.txt").write_text("staged important content\n")
        self.git(self.source, "add", "notes.txt")
        (self.source / "notes.txt").write_text("original\n")
        self.advance_upstream()
        self.assert_dirty_rejected_without_fetch()

    def test_rejects_untracked_files_before_fetch(self):
        (self.source / "untracked.txt").write_text("local test\n")
        self.assert_dirty_rejected_without_fetch()
        self.assertEqual("local test\n", (self.source / "untracked.txt").read_text())

    def test_conflict_aborts_rebase_and_restores_original_head(self):
        self.commit(self.source, "shared.txt", "feature\n")
        previous_head = self.git(self.source, "rev-parse", "HEAD").stdout
        self.advance_upstream("shared.txt", "upstream\n")
        self.assertFalse(self.prepare())
        self.assertEqual(previous_head, self.git(self.source, "rev-parse", "HEAD").stdout)
        self.assertEqual("feature\n", (self.source / "shared.txt").read_text())
        self.assertEqual("", self.git(self.source, "status", "--porcelain").stdout)
        self.assertFalse((self.source / ".git/rebase-merge").exists())

    def test_existing_rebase_is_not_aborted_or_overwritten(self):
        self.commit(self.source, "shared.txt", "feature\n")
        self.advance_upstream("shared.txt", "upstream\n")
        self.git(self.source, "fetch", "origin")
        self.git(self.source, "rebase", "origin/main", check=False)
        self.assertTrue((self.source / ".git/rebase-merge").exists())
        self.assertFalse(self.prepare())
        self.assertTrue((self.source / ".git/rebase-merge").exists())

    def test_fetch_failure_does_not_change_head(self):
        previous_head = self.git(self.source, "rev-parse", "HEAD").stdout
        self.git(self.source, "remote", "set-url", "origin", str(self.origin) + "-missing")
        self.assertFalse(self.prepare())
        self.assertEqual(previous_head, self.git(self.source, "rev-parse", "HEAD").stdout)

    def test_requires_configured_base_ref(self):
        with patch.object(base_ref, "zsv_base_ref", return_value=""):
            self.assertFalse(self.prepare())
