import configparser
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cbok import settings
from cbok import workspace
from cbok.bbx.zsv import config as zsv_config
from cbok.bbx.zsv import repo_sync
from cbok.bbx.zsv.repo_sync import RepositorySyncError
from cbok.bbx.zsv.repo_sync import sync_repositories
from cbok.cmd.zsv import ZSphereCommands


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
        text=True,
    )


def commit_file(root: Path, content: str, filename: str = "content.txt") -> str:
    (root / filename).write_text(content, encoding="utf-8")
    git(root, "add", filename)
    git(
        root,
        "-c",
        "user.name=CBoK Test",
        "-c",
        "user.email=cbok@example.test",
        "commit",
        "-m",
        content,
    )
    return git(root, "rev-parse", "HEAD").stdout.strip()


def create_repository(root: Path, name: str) -> tuple[Path, Path]:
    upstream = root / f"{name}-upstream.git"
    seed = root / f"{name}-seed"
    checkout = root / "zstack-workspace" / name

    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(upstream)],
        capture_output=True,
        check=True,
        text=True,
    )
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(seed)],
        capture_output=True,
        check=True,
        text=True,
    )
    commit_file(seed, "initial")
    git(seed, "remote", "add", "upstream", str(upstream))
    git(seed, "push", "upstream", "main")

    checkout.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--origin", "upstream", str(upstream), str(checkout)],
        capture_output=True,
        check=True,
        text=True,
    )
    git(checkout, "remote", "add", "origin", str(root / "missing-personal-fork.git"))
    return checkout, seed


class ZsvRepoSyncTest(unittest.TestCase):
    def setUp(self):
        self._original_workspace = settings.Workspace
        self._original_conf = zsv_config.settings.CONF

    def tearDown(self):
        settings.Workspace = self._original_workspace
        zsv_config.settings.CONF = self._original_conf

    def test_sync_repositories_fast_forwards_from_upstream_without_origin(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            before = git(checkout, "rev-parse", "HEAD").stdout.strip()
            upstream_head = commit_file(seed, "upstream change")
            git(seed, "push", "upstream", "main")

            results = sync_repositories(
                root / "zstack-workspace",
                ("zsvirt",),
            )

            self.assertNotEqual(before, upstream_head)
            self.assertEqual(upstream_head, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual([("zsvirt", upstream_head)], results)

    def test_dirty_repository_prevents_all_worktree_updates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first, first_seed = create_repository(root, "zsvirt")
            second, _second_seed = create_repository(root, "zsvirt-ee")
            first_before = git(first, "rev-parse", "HEAD").stdout.strip()
            commit_file(first_seed, "upstream change")
            git(first_seed, "push", "upstream", "main")
            (second / "dirty.txt").write_text("local work", encoding="utf-8")

            with self.assertRaisesRegex(RepositorySyncError, "zsvirt-ee.*uncommitted"):
                sync_repositories(
                    root / "zstack-workspace",
                    ("zsvirt", "zsvirt-ee"),
                )

            self.assertEqual(first_before, git(first, "rev-parse", "HEAD").stdout.strip())

    def test_local_commits_are_not_replaced_by_upstream(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, _seed = create_repository(root, "zsvirt")
            local_head = commit_file(checkout, "local change")

            with self.assertRaisesRegex(
                RepositorySyncError,
                "zsvirt.*local commits or diverged",
            ):
                sync_repositories(root / "zstack-workspace", ("zsvirt",))

            self.assertEqual(local_head, git(checkout, "rev-parse", "HEAD").stdout.strip())

    def test_diverged_repository_prevents_all_worktree_updates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first, first_seed = create_repository(root, "zsvirt")
            second, second_seed = create_repository(root, "zsvirt-ee")
            first_before = git(first, "rev-parse", "HEAD").stdout.strip()
            second_before = commit_file(second, "local change")
            for seed in (first_seed, second_seed):
                commit_file(seed, "upstream change")
                git(seed, "push", "upstream", "main")

            with self.assertRaisesRegex(RepositorySyncError, "zsvirt-ee.*diverged"):
                sync_repositories(root / "zstack-workspace", ("zsvirt", "zsvirt-ee"))

            self.assertEqual(first_before, git(first, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual(second_before, git(second, "rev-parse", "HEAD").stdout.strip())

    def test_unfinished_merge_with_clean_index_prevents_all_worktree_updates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first, first_seed = create_repository(root, "zsvirt")
            second, _second_seed = create_repository(root, "zsvirt-ee")
            first_before = git(first, "rev-parse", "HEAD").stdout.strip()
            commit_file(first_seed, "upstream change")
            git(first_seed, "push", "upstream", "main")
            git(second, "checkout", "-b", "topic")
            git(
                second, "-c", "user.name=CBoK Test",
                "-c", "user.email=cbok@example.test",
                "commit", "--allow-empty", "-m", "topic",
            )
            git(second, "checkout", "main")
            git(second, "merge", "--no-ff", "--no-commit", "topic")
            self.assertEqual("", git(second, "status", "--porcelain").stdout)

            with self.assertRaisesRegex(RepositorySyncError, "zsvirt-ee.*unfinished Git operation"):
                sync_repositories(root / "zstack-workspace", ("zsvirt", "zsvirt-ee"))

            self.assertEqual(first_before, git(first, "rev-parse", "HEAD").stdout.strip())

    def test_missing_upstream_does_not_fall_back_to_origin(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, _seed = create_repository(root, "zsvirt")
            git(checkout, "remote", "remove", "upstream")
            before = git(checkout, "rev-parse", "HEAD").stdout.strip()

            with self.assertRaisesRegex(RepositorySyncError, "remote get-url upstream failed"):
                sync_repositories(root / "zstack-workspace", ("zsvirt",))

            self.assertEqual(before, git(checkout, "rev-parse", "HEAD").stdout.strip())

    def test_missing_upstream_branch_preserves_local_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, _seed = create_repository(root, "zsvirt")
            git(checkout, "checkout", "-b", "local-only-branch")
            before = git(checkout, "rev-parse", "HEAD").stdout.strip()

            with self.assertRaisesRegex(RepositorySyncError, "fetch .*upstream.*local-only-branch.*failed"):
                sync_repositories(root / "zstack-workspace", ("zsvirt",))

            self.assertEqual(before, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual("local-only-branch", git(checkout, "branch", "--show-current").stdout.strip())

    def test_invalid_repository_list_is_rejected_before_any_git_operation(self):
        cases = (
            ((), "sync_repos is empty"),
            (("zsvirt", "zsvirt"), "duplicate repositories"),
            (("../zsvirt",), "invalid sync repository name"),
        )
        with tempfile.TemporaryDirectory() as td:
            for names, message in cases:
                with self.subTest(names=names):
                    with self.assertRaisesRegex(RepositorySyncError, message):
                        sync_repositories(Path(td), names)

    def test_ignored_file_collision_preserves_local_data_and_all_worktree_heads(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first, first_seed = create_repository(root, "zsvirt")
            second, second_seed = create_repository(root, "zsvirt-ee")
            before = [git(repo, "rev-parse", "HEAD").stdout.strip() for repo in (first, second)]
            (second / ".git/info/exclude").write_text("local.conf\n", encoding="utf-8")
            (second / "local.conf").write_text("local-only settings", encoding="utf-8")
            commit_file(first_seed, "upstream change")
            commit_file(second_seed, "upstream settings", "local.conf")
            for seed in (first_seed, second_seed):
                git(seed, "push", "upstream", "main")

            with self.assertRaisesRegex(RepositorySyncError, "ignored.*local.conf"):
                sync_repositories(root / "zstack-workspace", ("zsvirt", "zsvirt-ee"))

            self.assertEqual("local-only settings", (second / "local.conf").read_text())
            self.assertEqual(before, [git(repo, "rev-parse", "HEAD").stdout.strip() for repo in (first, second)])

    def test_worktree_changes_during_fetch_are_preserved_and_stop_sync(self):
        for change in ("branch", "commit", "untracked"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                checkout, seed = create_repository(root, "zsvirt")
                before = git(checkout, "rev-parse", "HEAD").stdout.strip()
                commit_file(seed, "upstream change")
                git(seed, "push", "upstream", "main")
                run_git = repo_sync._git
                changed_head = before

                def fetch_then_change(repo_root, *args):
                    nonlocal changed_head
                    result = run_git(repo_root, *args)
                    if args[0] == "fetch":
                        if change == "branch":
                            git(checkout, "checkout", "-b", "other")
                        elif change == "commit":
                            changed_head = commit_file(checkout, "concurrent local commit")
                        else:
                            (checkout / "local.txt").write_text("local work", encoding="utf-8")
                    return result

                with mock.patch.object(repo_sync, "_git", side_effect=fetch_then_change):
                    with self.assertRaisesRegex(RepositorySyncError, "changed while preparing|uncommitted|local commits"):
                        sync_repositories(root / "zstack-workspace", ("zsvirt",))

                self.assertEqual(changed_head, git(checkout, "rev-parse", "HEAD").stdout.strip())
                if change == "branch":
                    self.assertEqual("other", git(checkout, "branch", "--show-current").stdout.strip())
                    self.assertEqual(before, git(checkout, "rev-parse", "main").stdout.strip())
                elif change == "untracked":
                    self.assertEqual("local work", (checkout / "local.txt").read_text())

    def test_hidden_untracked_files_still_stop_sync(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            before = git(checkout, "rev-parse", "HEAD").stdout.strip()
            commit_file(seed, "upstream change")
            git(seed, "push", "upstream", "main")
            git(checkout, "config", "status.showUntrackedFiles", "no")
            (checkout / "local.txt").write_text("local work", encoding="utf-8")

            with self.assertRaisesRegex(RepositorySyncError, "uncommitted"):
                sync_repositories(root / "zstack-workspace", ("zsvirt",))

            self.assertEqual(before, git(checkout, "rev-parse", "HEAD").stdout.strip())

    def test_clean_index_with_unfinished_sequencer_stops_sync(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            before = git(checkout, "rev-parse", "HEAD").stdout.strip()
            commit_file(seed, "upstream change")
            git(seed, "push", "upstream", "main")
            sequencer = checkout / ".git/sequencer"
            sequencer.mkdir()
            (sequencer / "todo").write_text(f"pick {before} initial\n", encoding="utf-8")

            with self.assertRaisesRegex(RepositorySyncError, "unfinished Git operation"):
                sync_repositories(root / "zstack-workspace", ("zsvirt",))

            self.assertEqual(before, git(checkout, "rev-parse", "HEAD").stdout.strip())

    def test_fetch_does_not_contact_submodule_origin(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            _child_checkout, child_seed = create_repository(root / "child", "utility")
            child_remote = root / "child/utility-upstream.git"
            git(seed, "-c", "protocol.file.allow=always", "submodule", "add", str(child_remote), "utility")
            commit_file(seed, "add submodule")
            git(seed, "push", "upstream", "main")
            git(checkout, "fetch", "upstream")
            git(checkout, "merge", "--ff-only", "upstream/main")
            git(checkout, "-c", "protocol.file.allow=always", "submodule", "update", "--init")
            git(checkout, "config", "fetch.recurseSubmodules", "true")
            child = checkout / "utility"
            before = git(child, "rev-parse", "origin/main").stdout.strip()
            commit_file(child_seed, "child update")
            git(child_seed, "push", "upstream", "main")
            git(seed / "utility", "fetch", "origin")
            git(seed / "utility", "merge", "--ff-only", "origin/main")
            git(seed, "add", "utility")
            target = commit_file(seed, "update gitlink")
            git(seed, "push", "upstream", "main")

            self.assertEqual([("zsvirt", target)], sync_repositories(root / "zstack-workspace", ("zsvirt",)))

            self.assertEqual(before, git(child, "rev-parse", "origin/main").stdout.strip())

    def test_sync_repos_command_uses_active_workspace_context(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            (root / "cbok" / "cbok").mkdir(parents=True)
            (root / "cbok" / "scriptlet").mkdir()
            workspace.init_workspace(root)
            workspace.init_editor(root, "Cursor")
            workspace.init_company(root, "zs")
            workspace.use_context(root, "Cursor", "zs")

            company_root = root / "Cursor" / "zs"
            checkout, seed = create_repository(company_root, "zsvirt")
            upstream_head = commit_file(seed, "upstream change")
            git(seed, "push", "upstream", "main")

            parser = configparser.ConfigParser()
            parser["zsv"] = {
                "base_ref": "origin/main",
                "sync_repos": "zsvirt",
            }
            settings.Workspace = str(root)
            zsv_config.settings.CONF = parser

            command = ZSphereCommands()
            self.assertEqual(0, command.sync_repos())
            self.assertEqual(upstream_head, git(checkout, "rev-parse", "HEAD").stdout.strip())


if __name__ == "__main__":
    unittest.main()
