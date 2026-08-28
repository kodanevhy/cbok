import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cbok import workspace
from cbok import utils
from cbok.cmd import base
from cbok.cmd import workspace as workspace_cmd


def make_cbok_home(path: Path):
    (path / "cbok").mkdir(parents=True)
    (path / "scriptlet").mkdir(parents=True)


class WorkspaceLayoutTest(unittest.TestCase):
    def setUp(self):
        self._orig_workspace = utils.settings.Workspace

    def tearDown(self):
        utils.settings.Workspace = self._orig_workspace

    def test_cbok_home_defaults_to_workspace_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "cbok"
            make_cbok_home(home)

            utils.settings.Workspace = str(root)
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(os.path.realpath(home), utils.assert_cbok_home())

    def test_cbok_home_env_override_is_kept_for_worktrees(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source-cbok"
            make_cbok_home(source)

            utils.settings.Workspace = str(root / "workspace")
            with mock.patch.dict(os.environ, {"CBOK_HOME": str(source)}, clear=True):
                self.assertEqual(os.path.realpath(source), utils.assert_cbok_home())

    def test_cbok_home_falls_back_to_running_source_for_legacy_layout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "Cursor" / "me" / "cbok"
            make_cbok_home(source)

            utils.settings.Workspace = str(root)
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(workspace, "source_root", return_value=str(source)):
                    self.assertEqual(os.path.realpath(source), utils.assert_cbok_home())

    def test_workspace_commands_are_registered_under_workspace_category(self):
        groups = utils.discover_command_groups(
            {"workspace": workspace_cmd.WorkspaceCommands},
            base.BaseCommand,
        )

        command_names = [name for _cat, _obj, commands in groups for name, _method in commands]

        self.assertEqual(
            ["init", "init_company", "init_editor", "init_project", "use"],
            command_names,
        )

    def test_init_workspace_prepares_workspace_without_root_code_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            make_cbok_home(root / "cbok")

            workspace.init_workspace(str(root))

            self.assertFalse((root / "cm").exists())
            self.assertFalse((root / "me").exists())

    def test_init_workspace_requires_cloned_cbok_home(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"

            with self.assertRaisesRegex(workspace.WorkspaceLayoutError, "cbok home does not exist"):
                workspace.init_workspace(str(root))

    def test_init_editor_registers_editor_and_default_code_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            make_cbok_home(root / "cbok")
            workspace.init_workspace(str(root))

            workspace.init_editor(str(root), "Cursor")

            self.assertTrue((root / "Cursor" / "cm").is_dir())
            self.assertTrue((root / "Cursor" / "me").is_dir())

    def test_init_editor_reports_directory_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            make_cbok_home(root / "cbok")
            workspace.init_workspace(str(root))
            (root / "Cursor").write_text("conflict", encoding="utf-8")

            with self.assertRaisesRegex(workspace.WorkspaceLayoutError, "not a directory"):
                workspace.init_editor(str(root), "Cursor")

    def test_init_workspace_writes_minimal_cbok_conf_when_cbok_home_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            home = root / "cbok"
            make_cbok_home(home)

            workspace.init_workspace(str(root))

            conf = (home / "cbok.conf").read_text(encoding="utf-8")
            self.assertIn("[default]\n", conf)
            self.assertIn(f"workspace = {os.path.realpath(root)}\n", conf)

    def test_init_company_requires_registered_editor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            make_cbok_home(root / "cbok")
            workspace.init_workspace(str(root))

            with self.assertRaisesRegex(workspace.WorkspaceLayoutError, "no initialized editors"):
                workspace.init_company(str(root), "zs")

    def test_init_company_applies_to_all_registered_editors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            make_cbok_home(root / "cbok")
            workspace.init_workspace(str(root))
            workspace.init_editor(str(root), "Cursor")
            workspace.init_editor(str(root), "VSCode")

            workspace.init_company(str(root), "zs")

            self.assertTrue((root / "Cursor" / "zs").is_dir())
            self.assertTrue((root / "VSCode" / "zs").is_dir())

    def test_init_project_clones_repo_into_company_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            calls = []
            make_cbok_home(root / "cbok")

            def fake_runner(cmd, check):
                calls.append(cmd)

            workspace.init_workspace(str(root))
            workspace.init_editor(str(root), "Cursor")
            workspace.init_company(str(root), "zs")

            project_home = workspace.init_project(
                str(root),
                "Cursor",
                "zs",
                "zstack",
                repo="git@example.test:zstack.git",
                runner=fake_runner,
            )

            self.assertEqual(os.path.realpath(root / "Cursor" / "zs" / "zstack"), project_home)
            self.assertEqual(
                [["git", "clone", "git@example.test:zstack.git", project_home]],
                calls,
            )

    def test_init_project_rejects_existing_clone_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            make_cbok_home(root / "cbok")
            workspace.init_workspace(str(root))
            workspace.init_editor(str(root), "Cursor")
            workspace.init_company(str(root), "zs")
            (root / "Cursor" / "zs" / "zstack").mkdir(parents=True)

            with self.assertRaisesRegex(workspace.WorkspaceLayoutError, "already exists"):
                workspace.init_project(
                    str(root),
                    "Cursor",
                    "zs",
                    "zstack",
                    repo="git@example.test:zstack.git",
                )

    def test_init_project_accepts_copied_git_repo_without_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            make_cbok_home(root / "cbok")
            workspace.init_workspace(str(root))
            workspace.init_editor(str(root), "Cursor")
            workspace.init_company(str(root), "zs")
            project = root / "Cursor" / "zs" / "zstack"
            (project / ".git").mkdir(parents=True)

            project_home = workspace.init_project(str(root), "Cursor", "zs", "zstack")

            self.assertEqual(os.path.realpath(project), project_home)

    def test_init_project_rejects_existing_non_git_project_without_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            make_cbok_home(root / "cbok")
            workspace.init_workspace(str(root))
            workspace.init_editor(str(root), "Cursor")
            workspace.init_company(str(root), "zs")
            project = root / "Cursor" / "zs" / "zstack"
            project.mkdir()
            (project / "README.md").write_text("not git", encoding="utf-8")

            with self.assertRaisesRegex(workspace.WorkspaceLayoutError, "not a git repository"):
                workspace.init_project(str(root), "Cursor", "zs", "zstack")

    def test_workspace_command_uses_configured_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            cmd = workspace_cmd.WorkspaceCommands()
            make_cbok_home(root / "cbok")
            workspace.init_workspace(str(root))

            utils.settings.Workspace = str(root)
            self.assertEqual(0, cmd.init_editor(editor="Cursor"))

            self.assertTrue((root / "Cursor" / "cm").is_dir())

    def test_editor_and_company_names_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            make_cbok_home(root / "cbok")
            workspace.init_workspace(str(root))

            with self.assertRaisesRegex(workspace.WorkspaceLayoutError, "invalid editor"):
                workspace.init_editor(str(root), "../Cursor")

            with self.assertRaisesRegex(workspace.WorkspaceLayoutError, "invalid company"):
                workspace.init_company(str(root), "../zs")

    def test_workspace_use_persists_active_editor_company_context(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            make_cbok_home(root / "cbok")
            workspace.init_workspace(str(root))
            workspace.init_editor(str(root), "Cursor")
            workspace.init_company(str(root), "zs")

            workspace.use_context(str(root), "Cursor", "zs")

            self.assertEqual(
                workspace.WorkspaceContext(os.path.realpath(root), "Cursor", "zs"),
                workspace.current_context(str(root)),
            )

    def test_workspace_use_accepts_existing_copied_company_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ws"
            make_cbok_home(root / "cbok")
            workspace.init_workspace(str(root))
            (root / "Cursor" / "zs" / "zstack" / ".git").mkdir(parents=True)

            workspace.use_context(str(root), "Cursor", "zs")

            self.assertEqual(
                workspace.WorkspaceContext(os.path.realpath(root), "Cursor", "zs"),
                workspace.current_context(str(root)),
            )


if __name__ == "__main__":
    unittest.main()
