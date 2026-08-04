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


def fake_materialize_schema_db_file(target_dir, **_kwargs):
    path = Path(target_dir, "V5.1.0__schema.sql")
    path.write_text("CREATE TABLE T(id int);\n", encoding="utf-8")
    return str(path)


class SchemaRepairTest(unittest.TestCase):
    def test_discover_management_nodes_ignores_ssh_banner_lines(self):
        class Runner:
            def run_command(self, cmd, **kwargs):
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout=(
                        "Authorized users only. All activities may be monitored and reported.\n"
                        "172.24.193.164\n"
                        "mysql: [Warning] Using a password on the command line interface can be insecure.\n"
                        "172.24.196.228\n"
                        "172.24.241.203\n"
                        "172.24.241.203\n"
                    ),
                    stderr="",
                )

        self.assertEqual(
            ["172.24.193.164", "172.24.196.228", "172.24.241.203"],
            zsv_service.discover_management_nodes("172.24.241.203", Runner()),
        )

    def test_fetch_latest_artifact_accepts_exact_bin_url(self):
        bin_url = (
            "http://storage.zstack.io/mirror/zstack_feature-zsv-5.1.0-encryption/"
            "latest/ZStack-ZSphere-installer-fv-2606181047-36.bin"
        )
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_url=bin_url,
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

    def test_tracker_rejects_upgrade_directory_url(self):
        with self.assertRaisesRegex(ValueError, "exact \\.iso or \\.bin file URL"):
            ZSphereTracker(
                name="test-env",
                upgrade_url="http://example.invalid/latest/",
                primary_node="172.26.213.50",
                runner=FakeRunner(),
            )

    def test_tracker_rejects_upgrade_url_type_mismatch(self):
        with self.assertRaisesRegex(ValueError, "does not match upgrade_type"):
            ZSphereTracker(
                name="test-env",
                upgrade_type="bin",
                upgrade_url="http://example.invalid/ZStack-ZSphere-x86_64-DVD.iso",
                primary_node="172.26.213.50",
                runner=FakeRunner(),
            )

    def test_tracker_infers_upgrade_type_from_bin_url(self):
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_url="http://example.invalid/ZStack-ZSphere-installer.bin",
            primary_node="172.26.213.50",
            runner=FakeRunner(),
        )

        self.assertEqual("bin", tracker.upgrade_type)

    def test_tracker_infers_upgrade_type_from_iso_url(self):
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_url="http://example.invalid/ZStack-ZSphere-x86_64-DVD.iso",
            primary_node="172.26.213.50",
            runner=FakeRunner(),
        )

        self.assertEqual("iso", tracker.upgrade_type)

    def test_fetch_exact_artifact_tolerates_local_metadata_probe_failure(self):
        bin_url = "http://example.invalid/ZStack-ZSphere-installer.bin"
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_url=bin_url,
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
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_discover = zsv_service.discover_management_nodes
        original_precheck = schema_repair.run_schema_mismatch_precheck_for_file
        original_materialize = schema_repair.materialize_zsv_schema_db_file
        zsv_service.discover_management_nodes = lambda address, runner: [address]
        schema_repair.run_schema_mismatch_precheck_for_file = lambda **kwargs: 0
        schema_repair.materialize_zsv_schema_db_file = fake_materialize_schema_db_file
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
        tracker.check = lambda persist_state=True: (artifact, state, True, True)

        try:
            rc, _artifact, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.materialize_zsv_schema_db_file = original_materialize
            schema_repair.run_schema_mismatch_precheck_for_file = original_precheck
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
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_discover = zsv_service.discover_management_nodes
        original_precheck = schema_repair.run_schema_mismatch_precheck_for_file
        original_materialize = schema_repair.materialize_zsv_schema_db_file
        zsv_service.discover_management_nodes = lambda address, runner: [address]
        schema_repair.run_schema_mismatch_precheck_for_file = lambda **kwargs: 0
        schema_repair.materialize_zsv_schema_db_file = fake_materialize_schema_db_file
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
        tracker.check = lambda persist_state=True: (artifact, state, True, True)

        try:
            rc, _artifact, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.materialize_zsv_schema_db_file = original_materialize
            schema_repair.run_schema_mismatch_precheck_for_file = original_precheck
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
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_discover = zsv_service.discover_management_nodes
        original_precheck = schema_repair.run_schema_mismatch_precheck_for_file
        original_materialize = schema_repair.materialize_zsv_schema_db_file
        zsv_service.discover_management_nodes = lambda address, runner: [address]
        schema_repair.run_schema_mismatch_precheck_for_file = lambda **kwargs: 0
        schema_repair.materialize_zsv_schema_db_file = fake_materialize_schema_db_file
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
        tracker.check = lambda persist_state=True: (artifact, state, True, True)

        try:
            rc, _artifact, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.materialize_zsv_schema_db_file = original_materialize
            schema_repair.run_schema_mismatch_precheck_for_file = original_precheck
            zsv_service.discover_management_nodes = original_discover

        self.assertEqual(1, rc)
        self.assertIn("zsv_ensure_ui_started 172.26.213.50", runner.commands[-1][0][-1])
        self.assertEqual([], saved)

    def test_upgrade_fails_when_resources_do_not_become_ready(self):
        class HealthFailRunner(FakeRunner):
            def run_command(self, cmd, **kwargs):
                self.commands.append((cmd, kwargs))
                rc = 1 if "zsv_wait_resources_ready" in cmd[-1] else 0
                return subprocess.CompletedProcess(
                    args=cmd, returncode=rc, stdout="", stderr="")

        runner = HealthFailRunner()
        saved = []
        bin_url = "http://example.invalid/ZStack-ZSphere-installer.bin"
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="bin",
            upgrade_url=bin_url,
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_discover = zsv_service.discover_management_nodes
        original_precheck = schema_repair.run_schema_mismatch_precheck_for_file
        original_materialize = schema_repair.materialize_zsv_schema_db_file
        zsv_service.discover_management_nodes = lambda address, runner: [address]
        schema_repair.run_schema_mismatch_precheck_for_file = lambda **kwargs: 0
        schema_repair.materialize_zsv_schema_db_file = fake_materialize_schema_db_file
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
        tracker.check = lambda persist_state=True: (artifact, state, True, True)

        try:
            rc, _artifact, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.materialize_zsv_schema_db_file = original_materialize
            schema_repair.run_schema_mismatch_precheck_for_file = original_precheck
            zsv_service.discover_management_nodes = original_discover

        self.assertEqual(1, rc)
        scripts = [cmd[-1] for cmd, _kwargs in runner.commands]
        self.assertIn("zsv_ensure_ui_started 172.26.213.50", scripts[-2])
        self.assertIn("zsv_wait_resources_ready 172.26.213.50 1800 10", scripts[-1])
        self.assertEqual([], saved)

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
            upgrade_url="http://example.invalid/ZStack-ZSphere-x86_64-DVD.iso",
            primary_node="172.26.213.50",
            runner=FakeRunner(),
        )

        self.assertEqual(["172.26.213.50"], tracker.nodes)

    def test_printed_upgrade_command_does_not_include_nodes(self):
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="bin",
            upgrade_url="http://example.invalid/ZStack-ZSphere-installer.bin",
            primary_node="172.26.213.50",
            runner=FakeRunner(),
        )
        tracker.nodes = ["172.26.213.50", "172.26.213.51"]

        command = _upgrade_command(tracker)

        self.assertNotIn("--nodes", command)
        self.assertNotIn("--upgrade-type", command)
        self.assertNotIn("--db-file", command)
        self.assertIn("--upgrade-url http://example.invalid/ZStack-ZSphere-installer.bin", command)

    def test_upgrade_command_does_not_include_db_file(self):
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="bin",
            upgrade_url="http://example.invalid/ZStack-ZSphere-installer.bin",
            primary_node="172.26.213.50",
            runner=FakeRunner(),
        )

        command = _upgrade_command(tracker)

        self.assertNotIn("--db-file", command)

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

    def test_check_builds_tracker_from_current_artifact_url(self):
        command = ZSphereCommands()
        command.p_runner = FakeRunner()
        tracker = command._tracker(
            name="test-env",
            upgrade_url="http://example.invalid/ZStack-ZSphere-installer.bin",
            primary_node="172.26.213.50",
        )

        self.assertEqual("bin", tracker.upgrade_type)

    def test_zsv_upgrade_requires_full_execution_args(self):
        required_args = ("--name", "--upgrade-url", "--primary-node")
        options = {
            arg: kwargs
            for args, kwargs in getattr(ZSphereCommands.upgrade, "_args", [])
            for arg in args
        }
        for arg in required_args:
            self.assertIn(arg, options)
            self.assertTrue(options[arg]["required"])
        self.assertIn("directory or index URLs are not supported", options["--upgrade-url"]["help"])
        self.assertNotIn("--upgrade-type", options)
        self.assertNotIn("--db-file", options)

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
            self.assertNotIn("--db-file", option_names)

    def test_zsv_shared_settings_configure_base_ref_only(self):
        self.assertIn("zsv", [group.name for group in cbok_config.ALL_GROUPS])
        option_names = [opt.name for opt in cbok_config.ZSV.options]

        self.assertIn("base_ref", option_names)
        self.assertNotIn("zstack_root", option_names)
        self.assertNotIn("schema_branch", option_names)
        self.assertNotIn("db_file", option_names)

    def test_zsv_static_environment_knobs_are_not_cli_args(self):
        stable_cli_args = {
            ZSphereCommands.compile: ("--remote-lib", "--docker-host"),
            ZSphereCommands.groovy_test: ("--image", "--platform", "--docker-host", "--m2-dir"),
            ZSphereCommands.prune_worktree_containers: ("--docker-host",),
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
            ZSphereCommands.prune_worktree_containers: ("--container-name",),
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
                primary_node="172.26.213.50",
                runner=FakeRunner(),
            )

    def test_tracker_requires_name_and_primary_node(self):
        common = {
            "name": "test-env",
            "upgrade_url": "http://example.invalid/ZStack-ZSphere-installer.bin",
            "primary_node": "172.26.213.50",
            "runner": FakeRunner(),
        }

        for required in ("name", "primary_node"):
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
            upgrade_url="http://example.invalid/ZStack-ZSphere-x86_64-DVD.iso",
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_discover = zsv_service.discover_management_nodes
        original_precheck = schema_repair.run_schema_mismatch_precheck_for_file
        original_materialize = schema_repair.materialize_zsv_schema_db_file
        zsv_service.discover_management_nodes = (
            lambda address, runner: ["172.26.213.50", "172.26.213.51"]
        )
        schema_repair.run_schema_mismatch_precheck_for_file = lambda **kwargs: 0
        schema_repair.materialize_zsv_schema_db_file = fake_materialize_schema_db_file
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
        def fake_get_state(persist_source=True):
            if persist_source:
                state.iso_url = tracker.iso_url
                state.nodes = ",".join(tracker.nodes)
                state.save(update_fields=["iso_url", "nodes"])
            return state
        tracker.get_state = fake_get_state

        try:
            rc, _iso, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.materialize_zsv_schema_db_file = original_materialize
            schema_repair.run_schema_mismatch_precheck_for_file = original_precheck
            zsv_service.discover_management_nodes = original_discover

        self.assertEqual(0, rc)
        self.assertEqual(["172.26.213.50", "172.26.213.51"], tracker.nodes)
        self.assertEqual(1, len(saved))
        self.assertIn("iso_url", saved[0])
        self.assertIn("nodes", saved[0])
        self.assertIn("last_upgraded_at", saved[0])
        self.assertEqual("172.26.213.50,172.26.213.51", state.nodes)

    def test_upgrade_falls_back_to_primary_when_discovery_returns_no_nodes(self):
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="iso",
            upgrade_url="http://example.invalid/ZStack-ZSphere-x86_64-DVD.iso",
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

    def test_upgrade_resolves_db_file_from_base_ref(self):
        runner = FakeRunner()
        prechecks = []
        materialized = []
        tracker = ZSphereTracker(
            name="test-env",
            upgrade_type="iso",
            upgrade_url="http://example.invalid/ZStack-ZSphere-x86_64-DVD.iso",
            primary_node="172.26.213.50",
            runner=runner,
        )
        original_precheck = schema_repair.run_schema_mismatch_precheck_for_file
        original_discover = zsv_service.discover_management_nodes
        original_materialize = schema_repair.materialize_zsv_schema_db_file

        def fake_materialize(target_dir, **_kwargs):
            path = Path(target_dir, "V5.1.0__schema.sql")
            path.write_text("CREATE TABLE T(id int);\n", encoding="utf-8")
            materialized.append(str(path))
            return str(path)

        def fake_precheck(**kwargs):
            prechecks.append((kwargs, Path(kwargs["db_file"]).read_text(encoding="utf-8")))
            return 0

        schema_repair.run_schema_mismatch_precheck_for_file = fake_precheck
        zsv_service.discover_management_nodes = lambda address, runner: [address]
        schema_repair.materialize_zsv_schema_db_file = fake_materialize
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
        tracker.check = lambda persist_state=True: (iso, state, True, True)

        try:
            rc, _iso, _state = tracker.upgrade(FakeCommand())
        finally:
            schema_repair.materialize_zsv_schema_db_file = original_materialize
            schema_repair.run_schema_mismatch_precheck_for_file = original_precheck
            zsv_service.discover_management_nodes = original_discover

        self.assertEqual(0, rc)
        self.assertEqual(1, len(materialized))
        self.assertEqual(1, len(prechecks))
        self.assertEqual("172.26.213.50", prechecks[0][0]["address"])
        self.assertTrue(prechecks[0][0]["db_file"].endswith("V5.1.0__schema.sql"))
        self.assertEqual("CREATE TABLE T(id int);\n", prechecks[0][1])
        self.assertIn("zsv_upgrade_latest", runner.commands[0][0][-1])

    def test_materialize_zsv_schema_db_file_reuses_compile_base_ref_sync(self):
        sync_calls = []
        read_calls = []
        original_base_ref = schema_repair.zsv_base_ref
        original_sync = schema_repair.zsv_base_ref_helper.sync_base_ref
        original_read = schema_repair.read_branch_file

        def fake_read(root, branch, path):
            read_calls.append((root, branch, path))
            return "CREATE TABLE T(id int);\n"

        schema_repair.zsv_base_ref = lambda: "origin/zsv_5.1.0"
        schema_repair.zsv_base_ref_helper.sync_base_ref = (
            lambda root: sync_calls.append(root) or True
        )
        schema_repair.read_branch_file = fake_read

        try:
            with tempfile.TemporaryDirectory() as td:
                path = schema_repair.materialize_zsv_schema_db_file(
                    target_dir=td,
                    zstack_root="/repo/zstack",
                )

                self.assertEqual("CREATE TABLE T(id int);\n", Path(path).read_text(encoding="utf-8"))
        finally:
            schema_repair.zsv_base_ref = original_base_ref
            schema_repair.zsv_base_ref_helper.sync_base_ref = original_sync
            schema_repair.read_branch_file = original_read

        self.assertEqual(["/repo/zstack"], sync_calls)
        self.assertEqual([
            ("/repo/zstack", "origin/zsv_5.1.0", "conf/db/zsv/V5.1.0__schema.sql"),
        ], read_calls)

    def test_file_schema_precheck_uses_single_configured_db_file(self):
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

                rc = schema_repair.run_schema_mismatch_precheck_for_file(
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

    def test_file_schema_precheck_stops_on_checksum_mismatch_with_skill_hint(self):
        class MismatchRunner(FakeRunner):
            def run_command(self, cmd, **kwargs):
                self.commands.append((cmd, kwargs))
                script = cmd[-1]
                if "zsv_mysql_query" in script:
                    return subprocess.CompletedProcess(
                        args=cmd,
                        returncode=0,
                        stdout="5.1.0\t168\t-152505803\tV5.1.0__schema.sql\n",
                        stderr="",
                    )
                if "zsv_schema_flyway_migrate" in script:
                    return subprocess.CompletedProcess(
                        args=cmd,
                        returncode=1,
                        stdout=(
                            "Migration Checksum mismatch for migration 5.1.0\n"
                            "-> Applied to database : -152505803\n"
                            "-> Resolved locally    : -373519170\n"
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        runner = MismatchRunner()
        with tempfile.TemporaryDirectory() as td:
            db_file = Path(td, "V5.1.0__schema.sql")
            db_file.write_text("CREATE TABLE IF NOT EXISTS `zstack`.`T` (`uuid` varchar(32));\n")

            with self.assertLogs(schema_repair.LOG, level="ERROR") as logs:
                rc = schema_repair.run_schema_mismatch_precheck_for_file(
                    address="172.26.213.50",
                    db_file=str(db_file),
                    runner=runner,
                )

            output = "\n".join(logs.output)

        scripts = [cmd[-1] for cmd, _kwargs in runner.commands]
        self.assertEqual(1, rc)
        self.assertTrue(any("zsv_schema_stage_sql_dir" in script for script in scripts))
        self.assertTrue(any("zsv_schema_flyway_migrate" in script for script in scripts))
        self.assertFalse(any("zsv_schema_apply_sql_file" in script for script in scripts))
        self.assertFalse(any("zsv_schema_flyway_repair" in script for script in scripts))
        self.assertIn(schema_repair.MANUAL_REPAIR_SKILL, output)
        self.assertIn("primary node: 172.26.213.50", output)
        self.assertIn("migration: 5.1.0 (V5.1.0__schema.sql)", output)
        self.assertIn("applied checksum: -152505803", output)
        self.assertIn("resolved checksum: -373519170", output)

    def test_scriptlet_keeps_only_schema_precheck_helpers(self):
        scriptlet = Path("scriptlet/lib/zsv.sh").read_text(encoding="utf-8")

        self.assertIn("zsv_schema_stage_sql_dir()", scriptlet)
        self.assertIn("zsv_schema_flyway_migrate()", scriptlet)
        self.assertIn('bash \\"\\$flyway\\" migrate', scriptlet)
        self.assertNotIn("zsv_schema_flyway_repair()", scriptlet)
        self.assertNotIn("zsv_schema_apply_sql_file()", scriptlet)

    def test_bootstrap_exports_only_schema_precheck_scriptlets(self):
        bootstrap = Path("scriptlet/bootstrap.sh").read_text(encoding="utf-8")

        self.assertIn("_cbok_export_func zsv_schema_stage_sql_dir", bootstrap)
        self.assertIn("_cbok_export_func zsv_schema_flyway_migrate", bootstrap)
        self.assertNotIn("_cbok_export_func zsv_schema_flyway_repair", bootstrap)
        self.assertNotIn("_cbok_export_func zsv_schema_apply_sql_file", bootstrap)


if __name__ == "__main__":
    unittest.main()
