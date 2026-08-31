import configparser
import inspect
import subprocess
import unittest
from unittest import mock

from cbok.bbx import proxy_bypass
from cbok.cmd import bbx
from cbok.conf import config as cbok_config


class FakeRunner:
    def __init__(self, responses=None):
        self.commands = []
        self.kwargs = []
        self.responses = list(responses or [])

    def run_command(self, cmd, **kwargs):
        self.commands.append(cmd)
        self.kwargs.append(kwargs)
        response = self.responses.pop(0) if self.responses else {}
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=response.get("returncode", 0),
            stdout=response.get("stdout", ""),
            stderr=response.get("stderr", ""),
        )


def _conf(bypass_domains=None):
    conf = configparser.ConfigParser()
    conf.add_section("proxy")
    if bypass_domains is not None:
        conf.set("proxy", "bypass_domains", bypass_domains)
    return conf


class ProxyBypassConfigTest(unittest.TestCase):
    def test_proxy_bypass_domains_has_no_default_in_config_schema(self):
        proxy_group = next(
            group for group in cbok_config.ALL_GROUPS if group.name == "proxy"
        )
        option = next(
            opt for opt in proxy_group.options if opt.name == "bypass_domains"
        )

        self.assertIsNone(option.default)
        self.assertFalse(option.required)

    def test_read_bypass_domains_accepts_comma_and_newline_separated_values(self):
        domains = proxy_bypass.read_bypass_domains(_conf(
            "*.local, localhost\n"
            "  127.0.0.1\n"
            "  ::1, *.zstack.io\n"
        ))

        self.assertEqual(
            ["*.local", "localhost", "127.0.0.1", "::1", "*.zstack.io"],
            domains,
        )

    def test_read_bypass_domains_requires_proxy_option(self):
        with self.assertRaisesRegex(proxy_bypass.ProxyBypassError, "bypass_domains"):
            proxy_bypass.read_bypass_domains(_conf())


class ProxyBypassApplyTest(unittest.TestCase):
    def test_apply_bypass_domains_detects_current_wifi_service_from_default_route(self):
        runner = FakeRunner(responses=[
            {
                "stdout": (
                    "   route to: default\n"
                    "destination: default\n"
                    "  interface: en0\n"
                )
            },
            {
                "stdout": (
                    "An asterisk (*) denotes that a network service is disabled.\n"
                    "(1) Office Wi-Fi\n"
                    "(Hardware Port: Wi-Fi, Device: en0)\n"
                    "\n"
                    "(2) Thunderbolt Bridge\n"
                    "(Hardware Port: Thunderbolt Bridge, Device: bridge0)\n"
                )
            },
            {},
        ])

        service = proxy_bypass.apply_bypass_domains(
            ["*.local", "*.zstack.io"],
            runner=runner,
        )

        self.assertEqual("Office Wi-Fi", service)
        self.assertEqual(
            [
                ["/sbin/route", "-n", "get", "default"],
                ["/usr/sbin/networksetup", "-listnetworkserviceorder"],
                [
                    "/usr/sbin/networksetup",
                    "-setproxybypassdomains",
                    "Office Wi-Fi",
                    "*.local",
                    "*.zstack.io",
                ],
            ],
            runner.commands,
        )
        self.assertEqual(False, runner.kwargs[0]["log_output"])
        self.assertEqual(False, runner.kwargs[1]["log_output"])

    def test_apply_bypass_domains_rejects_current_non_wifi_service(self):
        runner = FakeRunner(responses=[
            {"stdout": "  interface: en5\n"},
            {
                "stdout": (
                    "(1) USB Ethernet\n"
                    "(Hardware Port: Ethernet Adapter, Device: en5)\n"
                )
            },
        ])

        with self.assertRaisesRegex(proxy_bypass.ProxyBypassError, "not a Wi-Fi service"):
            proxy_bypass.apply_bypass_domains(["*.local"], runner=runner)

    def test_apply_bypass_domains_only_uses_current_wifi_service(self):
        self.assertNotIn(
            "service",
            inspect.signature(proxy_bypass.apply_bypass_domains).parameters,
        )


class ProxyCommandsBypassTest(unittest.TestCase):
    def test_proxy_bypass_command_applies_domains_from_cbok_conf(self):
        command = bbx.ProxyCommands()
        command.p_runner = FakeRunner(responses=[
            {"stdout": "  interface: en0\n"},
            {
                "stdout": (
                    "(1) Office Wi-Fi\n"
                    "(Hardware Port: Wi-Fi, Device: en0)\n"
                )
            },
            {},
        ])
        original_conf = bbx.settings.CONF
        bbx.settings.CONF = _conf("*.local, localhost, *.zstack.io")
        try:
            with mock.patch.object(bbx.sys, "platform", "darwin"):
                with mock.patch("builtins.print"):
                    result = command.bypass()
        finally:
            bbx.settings.CONF = original_conf

        self.assertEqual(0, result)
        self.assertEqual(
            [
                "/usr/sbin/networksetup",
                "-setproxybypassdomains",
                "Office Wi-Fi",
                "*.local",
                "localhost",
                "*.zstack.io",
            ],
            command.p_runner.commands[-1],
        )

    def test_proxy_bypass_command_requires_configured_domains(self):
        command = bbx.ProxyCommands()
        command.p_runner = FakeRunner()
        original_conf = bbx.settings.CONF
        bbx.settings.CONF = _conf()
        try:
            with mock.patch.object(bbx.sys, "platform", "darwin"):
                with self.assertLogs("cbok.cmd.bbx", level="ERROR") as logs:
                    result = command.bypass()
        finally:
            bbx.settings.CONF = original_conf

        self.assertEqual(1, result)
        self.assertEqual([], command.p_runner.commands)
        self.assertIn("bypass_domains", "\n".join(logs.output))

    def test_proxy_bypass_command_does_not_accept_service_override(self):
        self.assertNotIn(
            "service",
            inspect.signature(bbx.ProxyCommands.bypass).parameters,
        )
        self.assertFalse(hasattr(bbx.ProxyCommands.bypass, "_args"))

    def test_proxy_bypass_command_is_macos_only(self):
        command = bbx.ProxyCommands()
        command.p_runner = FakeRunner()
        with mock.patch.object(bbx.sys, "platform", "linux"):
            with self.assertLogs("cbok.cmd.bbx", level="ERROR") as logs:
                result = command.bypass()

        self.assertEqual(1, result)
        self.assertEqual([], command.p_runner.commands)
        self.assertIn("only supported on macOS", "\n".join(logs.output))
