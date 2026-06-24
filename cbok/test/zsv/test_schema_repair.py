import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
import requests

from cbok.bbx.zsv import schema_repair
from cbok.conf import config as cbok_config

if "bs4" not in sys.modules:
    bs4 = types.ModuleType("bs4")
    bs4.BeautifulSoup = object
    sys.modules["bs4"] = bs4

if "django" not in sys.modules:
    django = types.ModuleType("django")
    django_utils = types.ModuleType("django.utils")
    timezone = types.SimpleNamespace(
        now=lambda: None,
        localtime=lambda dt: dt,
        is_aware=lambda dt: True,
        make_aware=lambda dt, tz=None: dt,
        get_current_timezone=lambda: None,
    )
    django_utils.timezone = timezone
    sys.modules["django"] = django
    sys.modules["django.utils"] = django_utils
    sys.modules["django.utils.timezone"] = timezone

from cbok.bbx.zsv.service import IsoInfo
from cbok.bbx.zsv.service import ZSphereTracker
from cbok.bbx.zsv import service as zsv_service
from cbok.cmd.zsv import _upgrade_command
from cbok.cmd.zsv import _upgrade_type_from_state
from cbok.cmd.zsv import ZSphereCommands


class FakeRunner:
    def __init__(self):
        self.commands = []

    def run_command(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


class FakeCommand:
    def __init__(self):
        self.ensured = []

    def ensure_remote_scriptlet(self, address):
        self.ensured.append(address)
        return SimpleNamespace(returncode=0)


class SchemaRepairTest(unittest.TestCase):
    def test_fetch_latest_artifact_accepts_exact_bin_url(self):
        bin_url = (
            "http://storage.zstack.io/mirror/zstack_feature-zsv-5.1.0-encryption/"
            "latest/ZStack-ZSphere-installer-fv-2606181047-36.bin"
        )
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="bin",
            upgrade_url=bin_url,
            db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            primary_node="172.26.213.50",
            runner=FakeRunner(),
        )
        original_head = zsv_service.requests.head
        zsv_service.requests.head = lambda *args, **kwargs: SimpleNamespace(
            url=bin_url,
            headers={"Content-Length": "123"},
            raise_for_status=lambda: None,
        )

        try:
            artifact = tracker.fetch_latest_iso()
        finally:
            zsv_service.requests.head = original_head

        self.assertEqual("ZStack-ZSphere-installer-fv-2606181047-36.bin", artifact.name)
        self.assertEqual(bin_url, artifact.download_url)
        self.assertEqual("123", artifact.size)

    def test_fetch_exact_artifact_tolerates_local_metadata_probe_failure(self):
        bin_url = "http://example.invalid/ZStack-ZSphere-installer.bin"
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="bin",
            upgrade_url=bin_url,
            db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            primary_node="172.26.213.50",
            runner=FakeRunner(),
        )
        original_head = zsv_service.requests.head
        zsv_service.requests.head = lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.HTTPError("metadata probe failed")
        )

        try:
            artifact = tracker.fetch_latest_iso()
        finally:
            zsv_service.requests.head = original_head

        self.assertEqual("ZStack-ZSphere-installer.bin", artifact.name)
        self.assertEqual(bin_url, artifact.download_url)
        self.assertEqual("", artifact.size)

    def test_scriptlet_discovers_nodes_from_hostvo_with_default_env_mysql_password(self):
        scriptlet = Path("scriptlet/lib/zsv.sh").read_text(encoding="utf-8")

        self.assertIn("HostVO", scriptlet)
        self.assertIn("managementIp", scriptlet)
        self.assertIn("-uroot -pzstack.mysql.password", scriptlet)

    def test_upgrade_passes_bin_type_to_remote_scriptlet(self):
        runner = FakeRunner()
        bin_url = "http://example.invalid/ZStack-ZSphere-installer.bin"
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="bin",
            upgrade_url=bin_url,
            db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_discover = zsv_service.discover_management_nodes
        original_repair = schema_repair.run_schema_repair_for_file
        zsv_service.discover_management_nodes = lambda address, runner: [address]
        schema_repair.run_schema_repair_for_file = lambda **kwargs: 0
        artifact = IsoInfo(
            name="ZStack-ZSphere-installer.bin",
            download_url=bin_url,
            size="123",
        )
        state = SimpleNamespace(
            latest_iso_name="",
            latest_iso_modified_at=None,
            last_upgraded_iso_name="",
            last_upgraded_iso_modified_at=None,
            last_upgraded_at=None,
            save=lambda update_fields=None: None,
        )
        tracker.check = lambda: (artifact, state, True, True)

        try:
            rc, _artifact, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.run_schema_repair_for_file = original_repair
            zsv_service.discover_management_nodes = original_discover

        self.assertEqual(0, rc)
        scripts = [cmd[-1] for cmd, _kwargs in runner.commands]
        upgrade_script = next(script for script in scripts if "zsv_upgrade_latest" in script)
        self.assertIn("ZStack-ZSphere-installer.bin", upgrade_script)
        self.assertTrue(upgrade_script.rstrip().endswith(" bin"))

    def test_upgrade_starts_ui_after_successful_remote_upgrade(self):
        runner = FakeRunner()
        bin_url = "http://example.invalid/ZStack-ZSphere-installer.bin"
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="bin",
            upgrade_url=bin_url,
            db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_discover = zsv_service.discover_management_nodes
        original_repair = schema_repair.run_schema_repair_for_file
        zsv_service.discover_management_nodes = lambda address, runner: [address]
        schema_repair.run_schema_repair_for_file = lambda **kwargs: 0
        artifact = IsoInfo(
            name="ZStack-ZSphere-installer.bin",
            download_url=bin_url,
            size="123",
        )
        state = SimpleNamespace(
            latest_iso_name="",
            latest_iso_modified_at=None,
            last_upgraded_iso_name="",
            last_upgraded_iso_modified_at=None,
            last_upgraded_at=None,
            save=lambda update_fields=None: None,
        )
        tracker.check = lambda: (artifact, state, True, True)

        try:
            rc, _artifact, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.run_schema_repair_for_file = original_repair
            zsv_service.discover_management_nodes = original_discover

        self.assertEqual(0, rc)
        scripts = [cmd[-1] for cmd, _kwargs in runner.commands]
        self.assertIn("zsv_upgrade_latest", scripts[0])
        self.assertIn("zsv_ensure_ui_started 172.26.213.50", scripts[1])
        self.assertIn("zsv_wait_resources_ready 172.26.213.50 1800 10", scripts[2])

    def test_upgrade_fails_when_ui_cannot_be_started(self):
        class UiFailRunner(FakeRunner):
            def run_command(self, cmd, **kwargs):
                self.commands.append((cmd, kwargs))
                rc = 1 if "zsv_ensure_ui_started" in cmd[-1] else 0
                return subprocess.CompletedProcess(
                    args=cmd, returncode=rc, stdout="", stderr="")

        runner = UiFailRunner()
        saved = []
        bin_url = "http://example.invalid/ZStack-ZSphere-installer.bin"
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="bin",
            upgrade_url=bin_url,
            db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_discover = zsv_service.discover_management_nodes
        original_repair = schema_repair.run_schema_repair_for_file
        zsv_service.discover_management_nodes = lambda address, runner: [address]
        schema_repair.run_schema_repair_for_file = lambda **kwargs: 0
        artifact = IsoInfo(
            name="ZStack-ZSphere-installer.bin",
            download_url=bin_url,
            size="123",
        )
        state = SimpleNamespace(
            latest_iso_name="",
            latest_iso_modified_at=None,
            last_upgraded_iso_name="",
            last_upgraded_iso_modified_at=None,
            last_upgraded_at=None,
            save=lambda update_fields=None: saved.append(update_fields),
        )
        tracker.check = lambda: (artifact, state, True, True)

        try:
            rc, _artifact, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.run_schema_repair_for_file = original_repair
            zsv_service.discover_management_nodes = original_discover

        self.assertEqual(1, rc)
        self.assertIn("zsv_ensure_ui_started 172.26.213.50", runner.commands[-1][0][-1])
        self.assertIn(
            [
                "latest_iso_name",
                "latest_iso_modified_at",
                "last_upgraded_iso_name",
                "last_upgraded_iso_modified_at",
                "last_upgraded_at",
            ],
            saved,
        )

    def test_upgrade_fails_when_resources_do_not_become_ready(self):
        class HealthFailRunner(FakeRunner):
            def run_command(self, cmd, **kwargs):
                self.commands.append((cmd, kwargs))
                rc = 1 if "zsv_wait_resources_ready" in cmd[-1] else 0
                return subprocess.CompletedProcess(
                    args=cmd, returncode=rc, stdout="", stderr="")

        runner = HealthFailRunner()
        bin_url = "http://example.invalid/ZStack-ZSphere-installer.bin"
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="bin",
            upgrade_url=bin_url,
            db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_discover = zsv_service.discover_management_nodes
        original_repair = schema_repair.run_schema_repair_for_file
        zsv_service.discover_management_nodes = lambda address, runner: [address]
        schema_repair.run_schema_repair_for_file = lambda **kwargs: 0
        artifact = IsoInfo(
            name="ZStack-ZSphere-installer.bin",
            download_url=bin_url,
            size="123",
        )
        state = SimpleNamespace(
            latest_iso_name="",
            latest_iso_modified_at=None,
            last_upgraded_iso_name="",
            last_upgraded_iso_modified_at=None,
            last_upgraded_at=None,
            save=lambda update_fields=None: None,
        )
        tracker.check = lambda: (artifact, state, True, True)

        try:
            rc, _artifact, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.run_schema_repair_for_file = original_repair
            zsv_service.discover_management_nodes = original_discover

        self.assertEqual(1, rc)
        scripts = [cmd[-1] for cmd, _kwargs in runner.commands]
        self.assertIn("zsv_ensure_ui_started 172.26.213.50", scripts[-2])
        self.assertIn("zsv_wait_resources_ready 172.26.213.50 1800 10", scripts[-1])

    def test_scriptlet_bin_upgrade_runs_installer_with_u(self):
        scriptlet = Path("scriptlet/lib/zsv.sh").read_text(encoding="utf-8")

        self.assertIn('bash "$artifact_name" -u', scriptlet)

    def test_scriptlet_waits_for_hosts_primary_and_backup_storage(self):
        scriptlet = Path("scriptlet/lib/zsv.sh").read_text(encoding="utf-8")

        self.assertIn("zsv_wait_resources_ready", scriptlet)
        self.assertIn("HostVO", scriptlet)
        self.assertIn("PrimaryStorageVO", scriptlet)
        self.assertIn("BackupStorageVO", scriptlet)
        self.assertIn("Enabled/Connected", scriptlet)

    def test_omitted_nodes_default_to_primary_until_discovery(self):
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="iso",
            upgrade_url="http://example.invalid/latest/",
            db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            primary_node="172.26.213.50",
            runner=FakeRunner(),
        )

        self.assertEqual(["172.26.213.50"], tracker.nodes)

    def test_printed_upgrade_command_does_not_include_nodes(self):
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="bin",
            upgrade_url="http://example.invalid/ZStack-ZSphere-installer.bin",
            db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            primary_node="172.26.213.50",
            runner=FakeRunner(),
        )
        tracker.nodes = ["172.26.213.50", "172.26.213.51"]

        command = _upgrade_command(tracker)

        self.assertNotIn("--nodes", command)
        self.assertIn("--upgrade-type bin", command)
        self.assertIn("--upgrade-url http://example.invalid/ZStack-ZSphere-installer.bin", command)
        self.assertIn("--db-file /workspace/zstack/conf/db/zsv/V5.1.0__schema.sql", command)

    def test_zsv_status_only_requires_primary_node(self):
        options = {
            arg: kwargs
            for args, kwargs in getattr(ZSphereCommands.status, "_args", [])
            for arg in args
        }

        self.assertEqual(["--primary-node"], list(options))
        self.assertTrue(options["--primary-node"]["required"])

    def test_zsv_check_does_not_require_upgrade_execution_args(self):
        options = {
            arg: kwargs
            for args, kwargs in getattr(ZSphereCommands.check, "_args", [])
            for arg in args
        }

        self.assertEqual(["--primary-node"], list(options))
        self.assertTrue(options["--primary-node"]["required"])
        self.assertNotIn("--upgrade-url", options)
        self.assertNotIn("--name", options)
        self.assertNotIn("--upgrade-type", options)
        self.assertNotIn("--db-file", options)

    def test_check_reports_upgrade_type_from_latest_state(self):
        state = SimpleNamespace(
            last_upgraded_iso_name="ZStack-ZSphere-installer-fv-2606181047-36.bin",
            latest_iso_name="",
            iso_url="http://example.invalid/latest/",
        )

        self.assertEqual("bin", _upgrade_type_from_state(state))

    def test_check_infers_iso_type_from_latest_state(self):
        state = SimpleNamespace(
            last_upgraded_iso_name="",
            latest_iso_name="ZStack-ZSphere-x86_64-DVD.iso",
            iso_url="http://example.invalid/latest/",
        )

        self.assertEqual("iso", _upgrade_type_from_state(state))

    def test_zsv_upgrade_requires_full_execution_args(self):
        required_args = ("--name", "--upgrade-type", "--upgrade-url", "--db-file", "--primary-node")
        options = {
            arg: kwargs
            for args, kwargs in getattr(ZSphereCommands.upgrade, "_args", [])
            for arg in args
        }
        for arg in required_args:
            self.assertIn(arg, options)
            self.assertTrue(options[arg]["required"])

    def test_zsv_upgrade_commands_do_not_define_manual_schema_args(self):
        for method in (ZSphereCommands.check, ZSphereCommands.status, ZSphereCommands.upgrade):
            option_names = [
                arg
                for arg_args, _arg_kwargs in getattr(method, "_args", [])
                for arg in arg_args
            ]
            self.assertNotIn("--iso-url", option_names)
            self.assertNotIn("--schema-branch", option_names)
            self.assertNotIn("--no-apply-schema-repair", option_names)
            self.assertNotIn("--zstack-root", option_names)

    def test_zsv_upgrade_settings_are_not_configured_in_cbok_conf_schema(self):
        self.assertNotIn("zsv", [group.name for group in cbok_config.ALL_GROUPS])

    def test_zsv_static_environment_knobs_are_not_cli_args(self):
        stable_cli_args = {
            ZSphereCommands.compile: ("--remote-lib", "--docker-host"),
            ZSphereCommands.groovy_test: ("--image", "--platform", "--docker-host", "--m2-dir"),
            ZSphereCommands.replace_agent: (
                "--nodes",
                "--site-packages",
                "--kvm-virtualenv",
                "--backup-root",
                "--base-ref",
            ),
        }

        for method, arg_names in stable_cli_args.items():
            option_names = [
                arg
                for arg_args, _arg_kwargs in getattr(method, "_args", [])
                for arg in arg_args
            ]
            for arg_name in arg_names:
                self.assertNotIn(arg_name, option_names)

    def test_zsv_runtime_target_args_are_required_cli(self):
        required_by_method = {
            ZSphereCommands.restart_mn: ("--address",),
            ZSphereCommands.compile: ("--zstack-root", "--premium-root"),
            ZSphereCommands.groovy_test: (
                "--zstack-branch",
                "--premium-branch",
                "--zstack-repo",
                "--premium-repo",
                "--test-class",
            ),
            ZSphereCommands.replace_agent: ("--primary-node", "--utility-root"),
            ZSphereCommands.install_ssh_key: ("--primary-node",),
        }

        for method, arg_names in required_by_method.items():
            options = {
                arg: kwargs
                for args, kwargs in getattr(method, "_args", [])
                for arg in args
            }
            for arg_name in arg_names:
                self.assertIn(arg_name, options)
                self.assertTrue(options[arg_name]["required"])

    def test_zsv_deploy_paths_are_configured_in_cbok_conf_schema(self):
        groups = {group.name: group for group in cbok_config.ALL_GROUPS}

        self.assertIn("zsv_deploy", groups)
        option_names = [opt.name for opt in groups["zsv_deploy"].options]
        self.assertEqual(
            ["remote_lib", "site_packages", "kvm_virtualenv", "backup_root"],
            option_names,
        )
        defaults = {opt.name: opt.default for opt in groups["zsv_deploy"].options}
        self.assertEqual(
            "/var/lib/zstack/virtualenv/kvm/lib/python2.7/site-packages",
            defaults["site_packages"],
        )

    def test_tracker_requires_upgrade_url(self):
        with self.assertRaisesRegex(ValueError, "upgrade_url is required"):
            ZSphereTracker(
                name="test-env",
                upgrade_type="bin",
                db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
                primary_node="172.26.213.50",
                runner=FakeRunner(),
            )

    def test_tracker_allows_empty_db_file_for_check_only_flow(self):
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="bin",
            upgrade_url="http://example.invalid/ZStack-ZSphere-installer.bin",
            primary_node="172.26.213.50",
            runner=FakeRunner(),
        )

        self.assertEqual("", tracker.schema_db_file)

    def test_tracker_requires_name_upgrade_type_and_primary_node(self):
        common = {
            "name": "test-env",
            "upgrade_type": "bin",
            "upgrade_url": "http://example.invalid/ZStack-ZSphere-installer.bin",
            "db_file": "/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            "primary_node": "172.26.213.50",
            "runner": FakeRunner(),
        }

        for required in ("name", "upgrade_type", "primary_node"):
            kwargs = dict(common)
            kwargs.pop(required)
            with self.assertRaisesRegex(ValueError, f"{required} is required"):
                ZSphereTracker(**kwargs)

    def test_upgrade_discovers_nodes_from_primary_when_nodes_are_omitted(self):
        runner = FakeRunner()
        saved = []
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="iso",
            upgrade_url="http://example.invalid/latest/",
            db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_discover = zsv_service.discover_management_nodes
        original_repair = schema_repair.run_schema_repair_for_file
        zsv_service.discover_management_nodes = (
            lambda address, runner: ["172.26.213.50", "172.26.213.51"]
        )
        schema_repair.run_schema_repair_for_file = lambda **kwargs: 0
        iso = IsoInfo(
            name="ZStack-ZSphere-installer.bin",
            download_url="http://example.invalid/ZStack-ZSphere-installer.bin",
            size="123",
        )
        state = SimpleNamespace(
            iso_url="",
            nodes="",
            latest_iso_name="",
            latest_iso_modified_at=None,
            last_upgraded_iso_name="",
            last_upgraded_iso_modified_at=None,
            last_upgraded_at=None,
            save=lambda update_fields=None: saved.append(update_fields),
        )
        tracker.fetch_latest_iso = lambda: iso
        def fake_get_state():
            state.iso_url = tracker.iso_url
            state.nodes = ",".join(tracker.nodes)
            state.save(update_fields=["iso_url", "nodes"])
            return state
        tracker.get_state = fake_get_state

        try:
            rc, _iso, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.run_schema_repair_for_file = original_repair
            zsv_service.discover_management_nodes = original_discover

        self.assertEqual(0, rc)
        self.assertEqual(["172.26.213.50", "172.26.213.51"], tracker.nodes)
        self.assertIn(["iso_url", "nodes"], saved)
        self.assertEqual("172.26.213.50,172.26.213.51", state.nodes)

    def test_upgrade_falls_back_to_primary_when_discovery_returns_no_nodes(self):
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="iso",
            upgrade_url="http://example.invalid/latest/",
            db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            primary_node="172.26.213.50",
            runner=FakeRunner(),
        )
        original_discover = zsv_service.discover_management_nodes
        zsv_service.discover_management_nodes = lambda address, runner: []

        try:
            with self.assertLogs(zsv_service.LOG, level="WARNING") as logs:
                tracker.resolve_upgrade_nodes()
        finally:
            zsv_service.discover_management_nodes = original_discover

        self.assertEqual(["172.26.213.50"], tracker.nodes)
        self.assertIn(
            "No management nodes discovered from primary node 172.26.213.50",
            "\n".join(logs.output),
        )

    def test_upgrade_repairs_configured_db_file_before_remote_upgrade(self):
        runner = FakeRunner()
        repairs = []
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="iso",
            upgrade_url="http://example.invalid/latest/",
            db_file="/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql",
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_repair = schema_repair.run_schema_repair_for_file
        original_discover = zsv_service.discover_management_nodes
        schema_repair.run_schema_repair_for_file = lambda **kwargs: repairs.append(kwargs) or 0
        zsv_service.discover_management_nodes = lambda address, runner: [address]
        iso = IsoInfo(
            name="ZStack-ZSphere-installer.bin",
            download_url="http://example.invalid/ZStack-ZSphere-installer.bin",
            size="123",
        )
        state = SimpleNamespace(
            latest_iso_name="",
            latest_iso_modified_at=None,
            last_upgraded_iso_name="",
            last_upgraded_iso_modified_at=None,
            last_upgraded_at=None,
            save=lambda update_fields=None: None,
        )
        tracker.check = lambda: (iso, state, True, True)

        try:
            rc, _iso, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.run_schema_repair_for_file = original_repair
            zsv_service.discover_management_nodes = original_discover

        self.assertEqual(0, rc)
        self.assertEqual(1, len(repairs))
        self.assertEqual("172.26.213.50", repairs[0]["address"])
        self.assertEqual("/workspace/zstack/conf/db/zsv/V5.1.0__schema.sql", repairs[0]["db_file"])
        script = runner.commands[0][0][-1]
        self.assertIn("zsv_upgrade_latest", script)

    def test_file_schema_repair_uses_single_configured_db_file(self):
        staged_files = []
        applied_scripts = []
        flyway_dirs = []
        original_stage = schema_repair._stage_sql_dir
        original_applied = schema_repair._remote_applied_migrations
        original_flyway = schema_repair._run_remote_flyway

        def fake_stage(address, local_dir, remote_dir, runner):
            staged_files.extend(path.name for path in Path(local_dir).iterdir())
            return 0

        def fake_applied(address, scripts, runner):
            applied_scripts.extend(scripts)
            return {
                "5.1.0": schema_repair.AppliedMigration(
                    version="5.1.0",
                    version_rank=168,
                    checksum=-1252689812,
                    script="V5.1.0__schema.sql",
                )
            }

        def fake_flyway(address, remote_dir, runner):
            flyway_dirs.append(remote_dir)
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="",
                stderr="",
            )

        schema_repair._stage_sql_dir = fake_stage
        schema_repair._remote_applied_migrations = fake_applied
        schema_repair._run_remote_flyway = fake_flyway

        try:
            with tempfile.TemporaryDirectory() as td:
                db_file = Path(td, "V5.1.0__schema.sql")
                db_file.write_text("CREATE TABLE IF NOT EXISTS `zstack`.`T` (`uuid` varchar(32));\n")

                rc = schema_repair.run_schema_repair_for_file(
                    address="172.26.213.50",
                    db_file=str(db_file),
                    runner=FakeRunner(),
                )
        finally:
            schema_repair._stage_sql_dir = original_stage
            schema_repair._remote_applied_migrations = original_applied
            schema_repair._run_remote_flyway = original_flyway

        self.assertEqual(0, rc)
        self.assertEqual(["V5.1.0__schema.sql"], applied_scripts)
        self.assertEqual(["V5.1.0__schema.sql"], staged_files)
        self.assertEqual([schema_repair.DEFAULT_REMOTE_SQL_DIR], flyway_dirs)

    def test_repair_script_executes_missing_table_then_updates_checksum(self):
        report = schema_repair.SchemaRepairReport(
            version="5.1.0",
            version_rank=168,
            applied_checksum=421859272,
            resolved_checksum=-1252689812,
            missing_tables=["ScannerAlarmStateVO"],
            missing_columns=[],
            view_names=[],
            ddl_statements=[
                "CREATE TABLE IF NOT EXISTS `zstack`.`ScannerAlarmStateVO` (\n"
                "    `uuid` varchar(32) NOT NULL UNIQUE,\n"
                "    PRIMARY KEY (`uuid`)\n"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8"
            ],
        )

        script = schema_repair.build_repair_sql(report)

        self.assertIn("CREATE TABLE IF NOT EXISTS `zstack`.`ScannerAlarmStateVO`", script)
        self.assertIn(
            "UPDATE `zstack`.`schema_version` SET `checksum` = -1252689812 "
            "WHERE `version_rank` = 168 AND `version` = '5.1.0'",
            script,
        )

    def test_repair_report_allows_idempotent_zstack_update_statements(self):
        migration = schema_repair.AppliedMigration(
            version="5.1.0",
            version_rank=168,
            checksum=-1252689812,
            script="V5.1.0__schema.sql",
        )
        mismatch = schema_repair.ChecksumMismatch(
            version="5.1.0",
            applied_checksum=-1252689812,
            resolved_checksum=-577660424,
        )
        sql = (
            "UPDATE `zstack`.`VolumeBackupVO` vb\n"
            "SET vb.`encrypted` = 1\n"
            "WHERE EXISTS (SELECT 1 FROM `zstack`.`EncryptedResourceKeyRefVO` keyRef\n"
            "WHERE keyRef.`resourceUuid` = vb.`uuid`);\n"
        )

        report = schema_repair._repair_report_for_mismatch(
            address="172.26.213.50",
            migration=migration,
            mismatch=mismatch,
            sql=sql,
            runner=FakeRunner(),
        )

        self.assertEqual([sql.strip().rstrip(";")], report.ddl_statements)


if __name__ == "__main__":
    unittest.main()
