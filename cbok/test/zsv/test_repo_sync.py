import configparser
from contextlib import redirect_stdout
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cbok import settings
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


def create_repository_with_submodule(root: Path) -> tuple[Path, Path, Path]:
    checkout, seed = create_repository(root, "zsvirt")
    _child_checkout, child_seed = create_repository(root / "child", "utility")
    child_remote = root / "child/utility-upstream.git"
    git(seed, "-c", "protocol.file.allow=always", "submodule", "add", str(child_remote), "utility")
    commit_file(seed, "add utility")
    git(seed, "push", "upstream", "main")
    git(checkout, "fetch", "upstream")
    git(checkout, "merge", "--ff-only", "upstream/main")
    git(checkout, "-c", "protocol.file.allow=always", "submodule", "update", "--init")
    return checkout, seed, child_seed


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
                ("zsvirt:main",),
            )

            self.assertNotEqual(before, upstream_head)
            self.assertEqual(upstream_head, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual([("zsvirt", "main", upstream_head)], results)

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
                    ("zsvirt:main", "zsvirt-ee:main"),
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
                sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

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
                sync_repositories(root / "zstack-workspace", ("zsvirt:main", "zsvirt-ee:main"))

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
                sync_repositories(root / "zstack-workspace", ("zsvirt:main", "zsvirt-ee:main"))

            self.assertEqual(first_before, git(first, "rev-parse", "HEAD").stdout.strip())

    def test_missing_upstream_does_not_fall_back_to_origin(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, _seed = create_repository(root, "zsvirt")
            git(checkout, "remote", "remove", "upstream")
            before = git(checkout, "rev-parse", "HEAD").stdout.strip()

            with self.assertRaisesRegex(RepositorySyncError, "remote get-url upstream failed"):
                sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

            self.assertEqual(before, git(checkout, "rev-parse", "HEAD").stdout.strip())

    def test_missing_upstream_branch_preserves_local_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, _seed = create_repository(root, "zsvirt")
            git(checkout, "checkout", "-b", "local-only-branch")
            before = git(checkout, "rev-parse", "HEAD").stdout.strip()

            with self.assertRaisesRegex(RepositorySyncError, "upstream.*missing.*failed"):
                sync_repositories(root / "zstack-workspace", ("zsvirt:missing",))

            self.assertEqual(before, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual("local-only-branch", git(checkout, "branch", "--show-current").stdout.strip())

    def test_invalid_repository_list_is_rejected_before_repository_updates(self):
        cases = (
            ((), "sync_repos is empty"),
            (("zsvirt:main", "zsvirt:release"), "duplicate repositories"),
            (("../zsvirt:main",), "invalid sync repository name"),
            (("zsvirt",), "project:branch"),
            (("zsvirt:",), "project:branch"),
            ((":main",), "project:branch"),
            (("zsvirt:bad..branch",), "invalid sync branch"),
            (("zsvirt:HEAD",), "invalid sync branch"),
            (("zsvirt:@{-1}",), "invalid sync branch"),
            (("zsvirt:--detach",), "invalid sync branch"),
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
                sync_repositories(root / "zstack-workspace", ("zsvirt:main", "zsvirt-ee:main"))

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
                        sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

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
                sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

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
                sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

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

            self.assertEqual([("zsvirt", "main", target)], sync_repositories(root / "zstack-workspace", ("zsvirt:main",)))

            self.assertEqual(before, git(child, "rev-parse", "origin/main").stdout.strip())

    def test_sync_repos_command_uses_existing_layout_without_workspace_initialization(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            company_root = root / "Cursor" / "zs"
            checkout, seed = create_repository(company_root, "zsvirt")
            upstream_head = commit_file(seed, "upstream change")
            git(seed, "push", "upstream", "main")
            premium, premium_seed = create_repository(company_root, "premium")
            git(premium_seed, "checkout", "-b", "5.5.48")
            premium_head = commit_file(premium_seed, "premium baseline")
            git(premium_seed, "push", "upstream", "5.5.48")

            parser = configparser.ConfigParser()
            parser["zsv"] = {
                "base_ref": "origin/main",
                "sync_repos": "zsvirt:main,premium:5.5.48",
            }
            settings.Workspace = str(root)
            zsv_config.settings.CONF = parser

            command = ZSphereCommands()
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, command.sync_repos())
            self.assertEqual(upstream_head, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual(premium_head, git(premium, "rev-parse", "HEAD").stdout.strip())
            self.assertTrue(output.getvalue().strip(), "Successful synchronization must print a summary table")
            rows = [
                [cell.strip() for cell in line.strip("|").split("|")]
                for line in output.getvalue().splitlines()
                if line.startswith("|")
            ]
            self.assertEqual([
                ["Project", "Branch", "Upstream", "Commit", "Result"],
                ["zsvirt", "main", "upstream/main", upstream_head[:12], "SYNCED"],
                ["premium", "5.5.48", "upstream/5.5.48", premium_head[:12], "SYNCED"],
            ], rows)

    def test_configured_branch_is_updated_without_rewriting_development_commits(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            git(checkout, "checkout", "-b", "development")
            development_head = commit_file(checkout, "unfinished feature")
            upstream_head = commit_file(seed, "latest baseline")
            git(seed, "push", "upstream", "main")

            self.assertEqual(
                [("zsvirt", "main", upstream_head)],
                sync_repositories(root / "zstack-workspace", ("zsvirt : main",)),
            )

            self.assertEqual("main", git(checkout, "branch", "--show-current").stdout.strip())
            self.assertEqual("latest baseline", (checkout / "content.txt").read_text())
            self.assertEqual(development_head, git(checkout, "rev-parse", "development").stdout.strip())

    def test_missing_local_branch_is_created_from_the_configured_upstream_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            git(seed, "checkout", "-b", "release/5.2")
            upstream_head = commit_file(seed, "release baseline")
            git(seed, "push", "upstream", "release/5.2")

            sync_repositories(root / "zstack-workspace", ("zsvirt:release/5.2",))

            self.assertEqual("release/5.2", git(checkout, "branch", "--show-current").stdout.strip())
            self.assertEqual(upstream_head, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual("release baseline", (checkout / "content.txt").read_text())

    def test_each_repository_uses_its_own_configured_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first, first_seed = create_repository(root, "zsvirt")
            second, second_seed = create_repository(root, "premium")
            first_head = commit_file(first_seed, "main baseline")
            git(first_seed, "push", "upstream", "main")
            git(second_seed, "checkout", "-b", "5.5.48")
            second_head = commit_file(second_seed, "premium baseline")
            git(second_seed, "push", "upstream", "5.5.48")

            self.assertEqual(
                [("zsvirt", "main", first_head), ("premium", "5.5.48", second_head)],
                sync_repositories(root / "zstack-workspace", ("zsvirt:main", "premium:5.5.48")),
            )

            self.assertEqual("main", git(first, "branch", "--show-current").stdout.strip())
            self.assertEqual("5.5.48", git(second, "branch", "--show-current").stdout.strip())

    def test_fetch_updates_all_upstream_branches_but_checks_out_only_the_configured_one(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            main_head = commit_file(seed, "main update")
            git(seed, "push", "upstream", "main")
            git(seed, "checkout", "-b", "release")
            release_head = commit_file(seed, "release update")
            git(seed, "push", "upstream", "release")

            sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

            self.assertEqual(main_head, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual(release_head, git(checkout, "rev-parse", "upstream/release").stdout.strip())
            self.assertEqual("main", git(checkout, "branch", "--show-current").stdout.strip())

    def test_target_branch_in_another_worktree_prevents_all_updates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first, first_seed = create_repository(root, "zsvirt")
            second, _second_seed = create_repository(root, "premium")
            first_before = git(first, "rev-parse", "HEAD").stdout.strip()
            commit_file(first_seed, "upstream update")
            git(first_seed, "push", "upstream", "main")
            git(second, "checkout", "-b", "development")
            git(second, "worktree", "add", str(root / "other"), "main")

            with self.assertRaisesRegex(RepositorySyncError, "premium.*another worktree"):
                sync_repositories(root / "zstack-workspace", ("zsvirt:main", "premium:main"))

            self.assertEqual(first_before, git(first, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual("development", git(second, "branch", "--show-current").stdout.strip())

    def test_ignored_files_are_preserved_during_the_intermediate_branch_checkout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            commit_file(seed, "old tracked settings", "local.conf")
            git(seed, "push", "upstream", "main")
            git(checkout, "fetch", "upstream")
            git(checkout, "merge", "--ff-only", "upstream/main")
            git(checkout, "checkout", "-b", "development")
            git(checkout, "rm", "local.conf")
            development_head = commit_file(checkout, "development")
            (checkout / ".git/info/exclude").write_text("local.conf\n", encoding="utf-8")
            (checkout / "local.conf").write_text("local-only settings", encoding="utf-8")
            git(seed, "rm", "local.conf")
            commit_file(seed, "upstream removed settings")
            git(seed, "push", "upstream", "main")

            with self.assertRaisesRegex(RepositorySyncError, "ignored.*local.conf"):
                sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

            self.assertEqual(development_head, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual("local-only settings", (checkout / "local.conf").read_text())

    def test_deleted_upstream_branch_is_not_restored_from_a_stale_tracking_ref(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            git(seed, "branch", "release")
            git(seed, "push", "upstream", "release")
            git(checkout, "fetch", "upstream")
            git(seed, "push", "upstream", "--delete", "release")
            before = git(checkout, "rev-parse", "HEAD").stdout.strip()

            with self.assertRaisesRegex(RepositorySyncError, "upstream/release.*failed"):
                sync_repositories(root / "zstack-workspace", ("zsvirt:release",))

            self.assertEqual(before, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual("main", git(checkout, "branch", "--show-current").stdout.strip())

    def test_configured_branch_changes_during_fetch_stop_sync_without_switching(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            git(checkout, "checkout", "-b", "development")
            development_head = commit_file(checkout, "local feature")
            upstream_head = commit_file(seed, "latest baseline")
            git(seed, "push", "upstream", "main")
            run_git = repo_sync._git

            def fetch_then_move_target(repo_root, *args):
                result = run_git(repo_root, *args)
                if args[0] == "fetch":
                    git(checkout, "update-ref", "refs/heads/main", upstream_head)
                return result

            with mock.patch.object(repo_sync, "_git", side_effect=fetch_then_move_target):
                with self.assertRaisesRegex(RepositorySyncError, "changed while preparing"):
                    sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

            self.assertEqual("development", git(checkout, "branch", "--show-current").stdout.strip())
            self.assertEqual(development_head, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual(upstream_head, git(checkout, "rev-parse", "main").stdout.strip())

    def test_local_commits_on_an_inactive_configured_branch_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, _seed = create_repository(root, "zsvirt")
            target_head = commit_file(checkout, "local baseline change")
            git(checkout, "checkout", "-b", "development")
            development_head = commit_file(checkout, "local feature")

            with self.assertRaisesRegex(RepositorySyncError, "configured branch main.*local commits"):
                sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

            self.assertEqual("development", git(checkout, "branch", "--show-current").stdout.strip())
            self.assertEqual(development_head, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual(target_head, git(checkout, "rev-parse", "main").stdout.strip())

    def test_changes_after_checkout_stop_sync_before_merging(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            before = git(checkout, "rev-parse", "HEAD").stdout.strip()
            git(checkout, "checkout", "-b", "development")
            commit_file(seed, "latest baseline")
            git(seed, "push", "upstream", "main")
            run_git = repo_sync._git

            def checkout_then_change(repo_root, *args):
                result = run_git(repo_root, *args)
                if args[0] == "checkout":
                    (checkout / "local.txt").write_text("concurrent work", encoding="utf-8")
                return result

            with mock.patch.object(repo_sync, "_git", side_effect=checkout_then_change):
                with self.assertRaisesRegex(RepositorySyncError, "uncommitted"):
                    sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

            self.assertEqual(before, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual("concurrent work", (checkout / "local.txt").read_text())

    def test_branch_and_tag_with_the_same_name_do_not_change_the_selected_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed = create_repository(root, "zsvirt")
            git(checkout, "tag", "main")
            git(checkout, "checkout", "-b", "development")
            upstream_head = commit_file(seed, "latest baseline")
            git(seed, "push", "upstream", "main")

            sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

            self.assertEqual("refs/heads/main", git(checkout, "symbolic-ref", "HEAD").stdout.strip())
            self.assertEqual(upstream_head, git(checkout, "rev-parse", "HEAD").stdout.strip())

    def test_checkout_preserves_clean_submodules_without_treating_old_gitlinks_as_local_edits(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkout, seed, child_seed = create_repository_with_submodule(root)
            git(checkout, "config", "submodule.recurse", "true")
            git(checkout, "checkout", "-b", "development")
            child_head = commit_file(child_seed, "new utility")
            git(child_seed, "push", "upstream", "main")
            child = checkout / "utility"
            git(child, "fetch", "origin")
            git(child, "merge", "--ff-only", "origin/main")
            git(checkout, "add", "utility")
            development_head = commit_file(checkout, "update development gitlink")
            upstream_head = commit_file(seed, "latest baseline")
            git(seed, "push", "upstream", "main")

            sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

            self.assertEqual(upstream_head, git(checkout, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual(development_head, git(checkout, "rev-parse", "development").stdout.strip())
            self.assertEqual(child_head, git(child, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual("new utility", (child / "content.txt").read_text())

    def test_concurrent_submodule_changes_after_checkout_are_not_treated_as_expected_gitlink_changes(self):
        for change in ("tracked", "untracked", "commit"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                checkout, seed, child_seed = create_repository_with_submodule(root)
                before = git(checkout, "rev-parse", "HEAD").stdout.strip()
                git(checkout, "checkout", "-b", "development")
                child = checkout / "utility"
                child_head = commit_file(child_seed, "new utility")
                git(child_seed, "push", "upstream", "main")
                git(child, "fetch", "origin")
                git(child, "merge", "--ff-only", "origin/main")
                git(checkout, "add", "utility")
                commit_file(checkout, "update development gitlink")
                commit_file(seed, "latest baseline")
                git(seed, "push", "upstream", "main")
                run_git = repo_sync._git

                def checkout_then_change_submodule(repo_root, *args):
                    nonlocal child_head
                    result = run_git(repo_root, *args)
                    if args[0] == "checkout":
                        if change == "commit":
                            child_head = commit_file(child, "concurrent child commit")
                        else:
                            filename = "content.txt" if change == "tracked" else "local.txt"
                            (child / filename).write_text("concurrent child work", encoding="utf-8")
                    return result

                with mock.patch.object(repo_sync, "_git", side_effect=checkout_then_change_submodule):
                    with self.assertRaisesRegex(RepositorySyncError, "uncommitted"):
                        sync_repositories(root / "zstack-workspace", ("zsvirt:main",))

                self.assertEqual(before, git(checkout, "rev-parse", "HEAD").stdout.strip())
                self.assertEqual(child_head, git(child, "rev-parse", "HEAD").stdout.strip())
                if change != "commit":
                    filename = "content.txt" if change == "tracked" else "local.txt"
                    self.assertEqual("concurrent child work", (child / filename).read_text())


if __name__ == "__main__":
    unittest.main()
