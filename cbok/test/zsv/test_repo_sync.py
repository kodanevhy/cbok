import configparser
import subprocess
import tempfile
import unittest
from pathlib import Path

from cbok import settings
from cbok import workspace
from cbok.bbx.zsv import config as zsv_config
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


def commit_file(root: Path, content: str) -> str:
    (root / "content.txt").write_text(content, encoding="utf-8")
    git(root, "add", "content.txt")
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

            with self.assertRaisesRegex(RepositorySyncError, "fetch upstream.*local-only-branch.*failed"):
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
