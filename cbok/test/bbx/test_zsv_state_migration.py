import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SETUP = """
import importlib
import sys
from pathlib import Path

import django
from django.conf import settings

root = Path(sys.argv[1])
migrations_dir = root / "bbx_migrations"
migrations_dir.mkdir()
(migrations_dir / "__init__.py").touch()
sys.path.insert(0, str(root))
settings.configure(
    INSTALLED_APPS=["cbok.bbx", "django.contrib.contenttypes"],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(root / "test.sqlite3")}},
    MIGRATION_MODULES={"bbx": "bbx_migrations"},
    DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
    SECRET_KEY="migration-test",
)
django.setup()

from django.apps import apps
from django.core.management import call_command
from django.db import connection, models
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.graph import MigrationGraph
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations import AddField, RemoveField, RenameField
from django.db.migrations.questioner import MigrationQuestioner
from django.db.migrations.state import ProjectState
from django.db.migrations.writer import MigrationWriter

def migration_files():
    return sorted(p.name for p in migrations_dir.glob("[0-9]*.py"))

def generate_and_migrate():
    call_command("makemigrations_bbx", verbosity=0)
    importlib.invalidate_caches()
    call_command("migrate", "bbx", verbosity=0)
"""


class ZsvStateMigrationTest(unittest.TestCase):
    def run_migration_script(self, script):
        with tempfile.TemporaryDirectory(prefix="cbok-migrations-") as td:
            env = dict(os.environ)
            env.pop("DJANGO_SETTINGS_MODULE", None)
            result = subprocess.run(
                [sys.executable, "-c", SETUP + textwrap.dedent(script), td],
                cwd=Path(__file__).resolve().parents[3],
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_upgrade_preserves_main_source_without_relabeling_premium_as_ee(self):
        self.run_migration_script("""
            old_state = ProjectState.from_apps(apps)
            old_names = {
                "zsvworktreecontainerstate": {
                    "zsvirt_root": "zstack_root", "zsvirt_head": "zstack_head",
                    "ee_root": "premium_root", "ee_head": "premium_head",
                },
                "zsvcompilestate": {
                    "zsvirt_root": "zstack_root", "ee_root": "premium_root",
                    "last_ee_modules": "last_premium_modules",
                },
            }
            for name, renames in old_names.items():
                fields = old_state.models["bbx", name].fields
                for current, old in renames.items():
                    fields[old] = fields.pop(current)
            detector = MigrationAutodetector(
                ProjectState(), old_state, MigrationQuestioner(specified_apps={"bbx"}))
            initial = detector.changes(graph=MigrationGraph(), convert_apps={"bbx"})["bbx"][0]
            writer = MigrationWriter(initial)
            Path(writer.path).write_text(writer.as_string())
            call_command("migrate", "bbx", verbosity=0)
            old_apps = MigrationExecutor(connection).loader.project_state().apps
            old_apps.get_model("bbx", "ZsvWorktreeContainerState").objects.create(
                worktree_key="container-key", zstack_root="/repos/zstack", zstack_head="main-sha",
                premium_root="/repos/premium", premium_head="premium-sha", image="builder",
                container_name="old-container", full_compile_done=True,
            )
            old_apps.get_model("bbx", "ZsvCompileState").objects.create(
                worktree_key="compile-key", zstack_root="/repos/zstack", premium_root="/repos/premium",
                last_main_modules='["core"]', last_premium_modules='["mevoco"]',
            )

            generate_and_migrate()
            container = apps.get_model("bbx", "ZsvWorktreeContainerState").objects.get(worktree_key="container-key")
            compiled = apps.get_model("bbx", "ZsvCompileState").objects.get(worktree_key="compile-key")
            assert container.zsvirt_root == compiled.zsvirt_root == "/repos/zstack"
            assert container.zsvirt_head == "main-sha"
            assert container.ee_root == container.ee_head == compiled.ee_root == compiled.last_ee_modules == ""
            assert compiled.last_main_modules == '["core"]'
            assert container.container_name == "old-container" and container.full_compile_done
            loader = MigrationLoader(connection)
            operations = loader.disk_migrations[loader.graph.leaf_nodes("bbx")[0]].operations
            assert {(op.model_name, op.old_name, op.new_name) for op in operations if isinstance(op, RenameField)} == {
                ("zsvworktreecontainerstate", "zstack_root", "zsvirt_root"),
                ("zsvworktreecontainerstate", "zstack_head", "zsvirt_head"),
                ("zsvcompilestate", "zstack_root", "zsvirt_root"),
            }
            assert {op.name for op in operations if isinstance(op, RemoveField)} == {
                "premium_root", "premium_head", "last_premium_modules"}
            assert {op.name for op in operations if isinstance(op, AddField)} == {
                "ee_root", "ee_head", "last_ee_modules"}
            before = migration_files()
            generate_and_migrate()
            assert migration_files() == before
        """)

    def test_fresh_database_and_second_run_are_noninteractive(self):
        self.run_migration_script("""
            generate_and_migrate()
            before = migration_files()
            assert len(before) == 1
            record = apps.get_model("bbx", "ZsvCompileState").objects.create(
                worktree_key="fresh", zsvirt_root="/repos/zsvirt", ee_root="/repos/zsvirt-ee")
            generate_and_migrate()
            assert migration_files() == before
            record.refresh_from_db()
            assert record.ee_root == "/repos/zsvirt-ee"
        """)

    def test_startup_resolves_bbx_renames_before_other_apps_scan_all_models(self):
        self.run_migration_script("""
            old_state = ProjectState.from_apps(apps)
            fields = old_state.models["bbx", "zsvcompilestate"].fields
            for current, old in {
                "zsvirt_root": "zstack_root", "ee_root": "premium_root",
                "last_ee_modules": "last_premium_modules",
            }.items():
                fields[old] = fields.pop(current)
            detector = MigrationAutodetector(
                ProjectState(), old_state, MigrationQuestioner(specified_apps={"bbx"}))
            initial = detector.changes(graph=MigrationGraph(), convert_apps={"bbx"})["bbx"][0]
            writer = MigrationWriter(initial)
            Path(writer.path).write_text(writer.as_string())
            call_command("migrate", "bbx", verbosity=0)

            try:
                call_command("makemigrations", "contenttypes", verbosity=0)
            except EOFError:
                pass
            else:
                raise AssertionError("Native makemigrations must reproduce the bbx rename prompt")

            startup = Path("foundation/cbok/01-config-map-cbok.yaml").read_text()
            for line in startup.splitlines():
                if line.strip().startswith("python3 manage.py makemigrations"):
                    command = line.split()[2]
                    arguments = () if command == "makemigrations_bbx" else ("contenttypes",)
                    call_command(command, *arguments, verbosity=0)
                    importlib.invalidate_caches()
            call_command("migrate", verbosity=0)
            compiled = apps.get_model("bbx", "ZsvCompileState").objects.create(
                worktree_key="multi-app", zsvirt_root="/repos/zsvirt")
            assert compiled.ee_root == compiled.last_ee_modules == ""
        """)

    def test_unknown_required_field_fails_without_inventing_default(self):
        self.run_migration_script("""
            generate_and_migrate()
            before = migration_files()
            models.CharField(max_length=32).contribute_to_class(
                apps.get_model("bbx", "ZsvCompileState"), "required_future_field")
            try:
                call_command("makemigrations_bbx", verbosity=0)
            except SystemExit as error:
                assert error.code == 3
            else:
                raise AssertionError("An unknown required field must fail noninteractively")
            assert migration_files() == before
        """)

    def test_command_rejects_other_apps_and_does_not_modify_django_defaults(self):
        self.run_migration_script("""
            from django.core.management.base import CommandError
            from django.core.management.commands.makemigrations import Command as DjangoCommand
            from cbok.bbx.management.commands.makemigrations_bbx import BbxMigrationQuestioner

            try:
                call_command("makemigrations_bbx", "auth", verbosity=0)
            except CommandError:
                pass
            else:
                raise AssertionError("The command must stay scoped to bbx")
            assert DjangoCommand.autodetector is MigrationAutodetector
            state = ProjectState.from_apps(apps)
            field = state.models["bbx", "zsvcompilestate"].fields["zsvirt_root"]
            questioner = BbxMigrationQuestioner(state)
            assert questioner.ask_rename("zsvcompilestate", "zstack_root", "zsvirt_root", field)
            assert not questioner.ask_rename("zsvcompilestate", "zstack_root", "zsvirt_root", field.clone())
            assert not questioner.ask_rename("zsvcompilestate", "premium_root", "ee_root", field)
        """)
