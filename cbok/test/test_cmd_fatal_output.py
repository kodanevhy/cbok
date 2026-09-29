import configparser
import contextlib
from datetime import datetime, timezone
import io
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock
import requests

from cbok.bbx.zsv import schema_repair
from cbok.bbx.zsv import service as zsv_service
from cbok.bbx.zsv.service import ZsvHostDiscoveryError
from cbok.cmd import bbx, foundation, zsv


class CommandFatalOutputTest(unittest.TestCase):
    def assert_failure(self, run, message, code=1):
        stderr = io.StringIO()
        with self.assertLogs("cbok.cmd.output", level="ERROR") as logs:
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exited:
                    run()

        self.assertEqual(code, exited.exception.code)
        self.assertEqual(message + "\n", stderr.getvalue())
        self.assertIn(message, "\n".join(logs.output))

    def test_which_failure_is_not_silent_success(self):
        command = bbx.BinCommands()
        command.p_runner = mock.Mock()
        command.p_runner.run_command.return_value = subprocess.CompletedProcess(
            ["which", "missing-bin"], 1, "", "not found")

        self.assert_failure(
            lambda: command.which("missing-bin"),
            "Failed to locate binary: missing-bin",
        )

    def test_proxy_config_error_is_plain_text(self):
        with mock.patch.object(bbx.settings, "CONF", configparser.ConfigParser()):
            self.assert_failure(
                bbx.ProxyCommands()._read_proxy_address,
                "Missing [proxy] in cbok.conf.",
            )

    def test_openstack_invalid_ip_is_plain_stderr(self):
        command = bbx.OpenStackCommands()
        self.assert_failure(
            lambda: command.deploy("invalid-ip", None, "eth0", "disk"),
            "Not an allowed IPv4 address: invalid-ip",
        )

    def test_openstack_declined_confirmation_is_plain_text(self):
        command = bbx.OpenStackCommands()
        with mock.patch.object(bbx.cbok_utils, "is_ipv4", return_value=True), \
                mock.patch("builtins.input", return_value="n"):
            self.assert_failure(
                lambda: command.deploy("192.0.2.1", None, "eth0", "disk"),
                "OpenStack deployment cancelled.",
            )

    def test_proxy_shell_failure_keeps_return_code(self):
        command = bbx.ProxyCommands()
        command.p_runner = mock.Mock()
        command.p_runner.run_shell_script.return_value = subprocess.CompletedProcess(
            ["deploy"], 7, "", "")
        with mock.patch.object(command, "_read_proxy_address", return_value="node"), \
                mock.patch.object(command, "_deploy_env", return_value={}):
            self.assert_failure(
                command.deploy,
                "Shell command failed.",
                code=7,
            )

    def test_proxy_client_delete_on_non_macos_fails(self):
        with mock.patch.object(bbx.sys, "platform", "linux"):
            self.assert_failure(
                lambda: bbx.ProxyCommands().delete("client"),
                "Client delete is only supported on macOS.",
            )

    def test_foundation_unknown_service_is_plain_text(self):
        command = foundation.FoundationCommands()
        with mock.patch.object(command, "_check_and_reflag_success", return_value="node"), \
                mock.patch.object(command, "ensure_remote_scriptlet"), \
                mock.patch.object(foundation.os.path, "isdir", return_value=False):
            self.assert_failure(
                lambda: command.apply(service="missing"),
                "No such service: missing",
            )

    def test_foundation_shell_failure_keeps_return_code(self):
        command = foundation.FoundationCommands()
        command.p_runner = mock.Mock()
        command.p_runner.run_command.return_value = subprocess.CompletedProcess(
            ["remove"], 7, "", "")
        with mock.patch.object(command, "_check_and_reflag_success", return_value="node"), \
                mock.patch.object(command, "ensure_remote_scriptlet"), \
                mock.patch.object(foundation.os.path, "isdir", return_value=True):
            self.assert_failure(
                lambda: command.remove(service="cbok"),
                "Shell command failed.",
                code=7,
            )

    def test_zsv_missing_required_address_is_plain_text(self):
        self.assert_failure(
            lambda: zsv.ZSphereCommands().restart_mn(),
            "restart_mn requires --address.",
        )

    def test_zsv_host_discovery_hides_remote_output(self):
        command = zsv.ZSphereCommands()
        with mock.patch.object(zsv, "_log_zsv_base_ref"), \
                mock.patch.object(zsv, "discover_healthy_kvm_host_nodes",
                                  side_effect=ZsvHostDiscoveryError("private remote output")):
            stderr = io.StringIO()
            with self.assertLogs("cbok.cmd.output", level="ERROR") as logs:
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as exited:
                        command.replace_zstore("node", "/repo/store")

        self.assertEqual(1, exited.exception.code)
        self.assertEqual("Failed to discover healthy KVM hosts.\n", stderr.getvalue())
        self.assertIn("private remote output", "\n".join(logs.output))

    def test_zsv_upgrade_failure_keeps_return_code(self):
        command = zsv.ZSphereCommands()
        tracker = mock.Mock()
        tracker.upgrade.return_value = (7, SimpleNamespace(name="upgrade.iso"), None)
        with mock.patch.object(command, "_tracker", return_value=tracker):
            self.assert_failure(
                lambda: command.upgrade(name="env", upgrade_url="url", primary_node="node"),
                "Upgrade command was not completed: upgrade.iso",
                code=7,
            )

    def test_zsv_upgrade_ssh_error(self):
        command = zsv.ZSphereCommands()
        tracker = zsv.ZSphereTracker(
            name="env", upgrade_url="http://example.invalid/upgrade.bin",
            primary_node="node", runner=mock.Mock(),
        )
        tracker.check = mock.Mock(return_value=(
            SimpleNamespace(name="upgrade.bin"), object(), True, True))
        failure = subprocess.CompletedProcess(
            ["ssh"], 255,
            "ssh: connect to host node port 22: Network is unreachable\n"
            "private remote output", "",
        )

        with mock.patch.object(command, "_tracker", return_value=tracker), \
                mock.patch.object(tracker, "resolve_upgrade_nodes"), \
                mock.patch.object(command, "ensure_remote_scriptlet",
                                  return_value=failure):
            self.assert_failure(
                lambda: command.upgrade(
                    name="env", upgrade_url=tracker.upgrade_url,
                    primary_node="node"),
                "SSH connection to primary node node failed: Network is unreachable.",
                code=255,
            )
        tracker.runner.run_command.assert_not_called()

    def test_zsv_upgrade_bad_url(self):
        command = zsv.ZSphereCommands()
        with mock.patch.object(zsv.ZSphereTracker, "resolve_upgrade_nodes",
                               side_effect=AssertionError("unexpected remote discovery")):
            self.assert_failure(
                lambda: command.upgrade(
                    name="env", upgrade_url="http:http://example.invalid/upgrade.bin",
                    primary_node="node"),
                "upgrade_url must be an absolute HTTP(S) URL with a host.",
            )

    def test_zsv_check_bad_url(self):
        command = zsv.ZSphereCommands()
        state = SimpleNamespace(
            name="env", iso_url="http:http://example.invalid/upgrade.bin")
        with mock.patch.object(zsv, "_latest_upgrade_state", return_value=state), \
                mock.patch.object(zsv.ZSphereTracker, "check",
                                  side_effect=AssertionError("unexpected metadata probe")):
            self.assert_failure(
                lambda: command.check(primary_node="node"),
                "upgrade_url must be an absolute HTTP(S) URL with a host.",
            )

    def test_zsv_upgrade_already_current(self):
        command = zsv.ZSphereCommands()
        runner = mock.Mock()
        tracker = zsv.ZSphereTracker(
            name="env", upgrade_url="http://example.invalid/upgrade.bin",
            primary_node="node", runner=runner,
        )
        iso = SimpleNamespace(name="upgrade.bin")
        with mock.patch.object(command, "_tracker", return_value=tracker), \
                mock.patch.object(tracker, "resolve_upgrade_nodes"), \
                mock.patch.object(tracker, "check",
                                  return_value=(iso, object(), False, False)):
            self.assert_failure(
                lambda: command.upgrade(
                    name="env", upgrade_url="http://example.invalid/upgrade.bin",
                    primary_node="node"),
                "Already up to date: upgrade.bin.",
            )

        runner.run_command.assert_not_called()

    def test_zsv_upgrade_404(self):
        url = "http://example.invalid/upgrade.bin"
        command = zsv.ZSphereCommands()
        tracker = zsv.ZSphereTracker(
            name="env", upgrade_url=url, primary_node="node", runner=mock.Mock(),
        )
        modified_at = datetime(2026, 9, 28, tzinfo=timezone.utc)
        state = SimpleNamespace(
            latest_iso_name="upgrade.iso", latest_iso_modified_at=modified_at,
            last_upgraded_iso_name="upgrade.iso",
            last_upgraded_iso_modified_at=modified_at,
            save=mock.Mock(),
        )
        response = requests.Response()
        response.status_code = 404
        response.url = url

        with mock.patch.object(command, "_tracker", return_value=tracker), \
                mock.patch.object(tracker, "get_state", return_value=state), \
                mock.patch.object(tracker, "resolve_upgrade_nodes") as discover, \
                mock.patch.object(zsv_service.requests, "head", return_value=response):
            self.assert_failure(
                lambda: command.upgrade(name="env", upgrade_url=url, primary_node="node"),
                "Unable to check upgrade package metadata (HTTP 404): upgrade.bin.",
            )
        discover.assert_not_called()

    def test_zsv_check_404(self):
        url = "http://example.invalid/upgrade.bin"
        state = SimpleNamespace(
            name="env", iso_url=url,
            latest_iso_name="upgrade.iso", latest_iso_modified_at=None,
            last_upgraded_iso_name="upgrade.iso",
            last_upgraded_iso_modified_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
            last_upgraded_at=None,
            save=mock.Mock(),
        )
        response = requests.Response()
        response.status_code = 404
        response.url = url

        with mock.patch.object(zsv, "_latest_upgrade_state", return_value=state), \
                mock.patch.object(zsv.ZSphereTracker, "get_state", return_value=state), \
                mock.patch.object(zsv_service.requests, "head", return_value=response):
            self.assert_failure(
                lambda: zsv.ZSphereCommands().check(primary_node="node"),
                "Unable to check upgrade package metadata (HTTP 404): upgrade.bin.",
            )

    def test_zsv_precheck_error(self):
        command = zsv.ZSphereCommands()
        runner = mock.Mock()
        tracker = zsv.ZSphereTracker(
            name="env", upgrade_url="http://example.invalid/upgrade.iso",
            primary_node="node", runner=runner,
        )
        tracker.discovered_nodes = True
        iso = SimpleNamespace(name="upgrade.iso", download_url="http://example.invalid/upgrade.iso",
                              modified_at=None, size="")
        runner.run_command.return_value = subprocess.CompletedProcess(
            ["precheck"], 1,
            "__CBOK_ZSV_SCHEMA_PRECHECK__\n"
            "primary_node=node\n"
            "sql_source=upgrade.iso!WEB-INF/classes/db/ee/V5.2.0__schema.sql\n"
            "script=V5.2.0__schema.sql\n"
            "version=5.2.0\n"
            "version_rank=170\n"
            "applied_checksum=1097995333\n"
            "resolved_checksum=-1071519265\n", "",
        )
        message = schema_repair.format_manual_repair_hint(
            address="node",
            migration=schema_repair.AppliedMigration(
                version="5.2.0", version_rank=170, checksum=1097995333,
                script="V5.2.0__schema.sql"),
            mismatch=schema_repair.ChecksumMismatch(
                version="5.2.0", applied_checksum=1097995333,
                resolved_checksum=-1071519265),
            db_file="upgrade.iso!WEB-INF/classes/db/ee/V5.2.0__schema.sql",
        )

        with mock.patch.object(command, "_tracker", return_value=tracker), \
                mock.patch.object(tracker, "resolve_upgrade_nodes"), \
                mock.patch.object(tracker, "check", return_value=(iso, object(), True, True)):
            self.assert_failure(
                lambda: command.upgrade(name="env", upgrade_url=iso.download_url,
                                        primary_node="node"),
                message,
            )

        self.assertEqual(1, runner.run_command.call_count)

    def test_zsv_no_log_reread(self):
        command = zsv.ZSphereCommands()
        runner = mock.Mock()
        tracker = zsv.ZSphereTracker(
            name="env", upgrade_url="http://example.invalid/upgrade.iso",
            primary_node="node", runner=runner,
        )
        tracker.discovered_nodes = True
        iso = SimpleNamespace(name="upgrade.iso", download_url="http://example.invalid/upgrade.iso",
                              modified_at=None, size="")
        runner.run_command.side_effect = [
            subprocess.CompletedProcess(["precheck"], 0, "", ""),
            subprocess.CompletedProcess(
                ["upgrade"], 7,
                "Reason: failed to upgrade database\n"
                "The detailed installation log could be found in "
                "/tmp/zstack_installation-2026-09-28-16:59:01.log\n", "",
            ),
        ]
        with mock.patch.object(command, "_tracker", return_value=tracker), \
                mock.patch.object(tracker, "resolve_upgrade_nodes"), \
                mock.patch.object(tracker, "check", return_value=(iso, object(), True, True)), \
                mock.patch("subprocess.Popen",
                           side_effect=AssertionError("unexpected installer log read")):
            self.assert_failure(
                lambda: command.upgrade(name="env", upgrade_url=iso.download_url,
                                        primary_node="node"),
                "Upgrade command was not completed: upgrade.iso",
                code=7,
            )

        self.assertEqual(2, runner.run_command.call_count)


if __name__ == "__main__":
    unittest.main()
