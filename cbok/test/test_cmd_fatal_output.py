import configparser
import contextlib
import io
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from cbok.bbx.zsv import schema_repair
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

    def test_zsv_upgrade_reports_schema_artifact_precheck_failure(self):
        command = zsv.ZSphereCommands()
        runner = mock.Mock()
        tracker = zsv.ZSphereTracker(
            name="env",
            upgrade_url="http://example.invalid/upgrade.iso",
            primary_node="node",
            runner=runner,
        )
        tracker.discovered_nodes = True
        iso = SimpleNamespace(
            name="upgrade.iso",
            download_url="http://example.invalid/upgrade.iso",
            modified_at=None,
            size="",
        )

        with mock.patch.object(command, "_tracker", return_value=tracker), \
                mock.patch.object(tracker, "resolve_upgrade_nodes"), \
                mock.patch.object(tracker, "check", return_value=(iso, object(), True, True)), \
                mock.patch.object(schema_repair, "run_schema_mismatch_precheck_for_artifact",
                                  return_value=7):
            self.assert_failure(
                lambda: command.upgrade(name="env", upgrade_url=iso.download_url,
                                        primary_node="node"),
                "ZSV schema artifact precheck failed.",
                code=7,
            )

        runner.run_command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
