import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace

from cbok.cmd.zsv import ZSphereCommands


CBOK_ROOT = Path(__file__).resolve().parents[3]


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run_command(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0)


class ZsvRestartMnTest(unittest.TestCase):
    def test_restart_mn_syncs_scriptlet_then_restarts_target_mn(self):
        command = ZSphereCommands()
        runner = FakeRunner()
        ensured = []
        command.p_runner = runner
        command.ensure_remote_scriptlet = (
            lambda address: ensured.append(address) or SimpleNamespace(returncode=0)
        )

        if not hasattr(command, "restart_mn"):
            self.fail("ZSphereCommands must expose restart_mn")

        rc = command.restart_mn(address="172.26.213.50")

        self.assertEqual(0, rc)
        self.assertEqual(["172.26.213.50"], ensured)
        self.assertEqual(1, len(runner.calls))
        cmd, kwargs = runner.calls[0]
        self.assertEqual(
            ["bash", "-lc", "source scriptlet/bootstrap.sh; zsv_restart_mn 172.26.213.50"],
            cmd,
        )
        self.assertFalse(kwargs["cmd_purge_output"])

    def test_zsv_restart_mn_scriptlet_restarts_node_and_prints_status(self):
        script = """
source scriptlet/bootstrap.sh
remote_bash() {
  printf 'address=%s\\n' "$1"
  printf 'script=%s\\n' "$2"
}
zsv_restart_mn 172.26.213.50
"""

        result = subprocess.run(
            ["bash", "-lc", script],
            cwd=str(CBOK_ROOT),
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("address=172.26.213.50", result.stdout)
        self.assertIn("zstack-ctl restart_node", result.stdout)
        self.assertIn("zstack-ctl status", result.stdout)

    def test_zsv_ensure_ui_started_syncs_scriptlet_then_starts_ui(self):
        script = """
source scriptlet/bootstrap.sh
ensure_remote_scriptlet() {
  printf 'ensure=%s\\n' "$1"
}
remote_exec() {
  printf 'remote_exec=%s %s %s %s\\n' "$1" "$2" "$3" "$4"
}
zsv_ensure_ui_started 172.26.213.50
"""

        result = subprocess.run(
            ["bash", "-lc", script],
            cwd=str(CBOK_ROOT),
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("ensure=172.26.213.50", result.stdout)
        self.assertIn(
            "remote_exec=172.26.213.50 zsv_start_ui_if_needed 12 5",
            result.stdout,
        )

    def test_zsv_start_ui_scriptlet_runs_start_ui_and_checks_status(self):
        scriptlet = Path("scriptlet/lib/zsv.sh").read_text(encoding="utf-8")

        self.assertIn("zstack-ctl start_ui", scriptlet)
        self.assertIn("UI status:.*Running", scriptlet)
