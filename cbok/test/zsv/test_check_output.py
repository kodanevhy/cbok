import contextlib
from datetime import datetime
import io
from types import SimpleNamespace
import unittest
from unittest import mock

from cbok.cmd import zsv


class ZsvCheckOutputTest(unittest.TestCase):
    def run_check(self, needs_upgrade, modified_at):
        command = zsv.ZSphereCommands()
        address = "192.0.2.10"
        url = "http://example.invalid/upgrade.iso"
        state = SimpleNamespace(
            name="env",
            iso_url=url,
            last_upgraded_iso_modified_at=modified_at,
            last_upgraded_at=modified_at,
        )
        iso = SimpleNamespace(name="upgrade.iso", modified_at=modified_at)
        tracker = SimpleNamespace(
            name="env",
            upgrade_type="iso",
            upgrade_url=url,
            primary_node=address,
            check=mock.Mock(return_value=(iso, state, needs_upgrade, False)),
        )
        stdout = io.StringIO()

        with mock.patch.object(zsv, "_latest_upgrade_state", return_value=state), \
                mock.patch.object(command, "_tracker", return_value=tracker), \
                mock.patch.object(zsv.timezone, "localtime", side_effect=lambda dt: dt), \
                contextlib.redirect_stdout(stdout):
            result = command.check(primary_node=address)

        rows = [
            [cell.strip() for cell in line.strip("|").split("|")]
            for line in stdout.getvalue().splitlines()
            if line.startswith("|")
        ]
        return result, rows, stdout.getvalue(), tracker

    def test_check_table(self):
        modified_at = datetime.fromisoformat("2026-09-28T19:19:10+08:00")
        result, rows, text, tracker = self.run_check(False, modified_at)

        self.assertEqual(0, result)
        self.assertEqual([
            ["Field", "Value"],
            ["Name", "upgrade.iso"],
            ["Upgrade type", "iso"],
            ["DB", "2026-09-28T19:19:10+08:00"],
            ["URL", "2026-09-28T19:19:10+08:00"],
            ["Last sync at", "2026-09-28T19:19:10+08:00"],
        ], rows)
        self.assertFalse(text.startswith("Name:"))
        tracker.check.assert_called_once_with()

    def test_check_upgrade_command_row(self):
        result, rows, _, tracker = self.run_check(True, None)

        self.assertEqual(0, result)
        self.assertEqual(["DB", "never"], rows[3])
        self.assertEqual(["URL", "unknown"], rows[4])
        self.assertEqual(["Last sync at", "never"], rows[5])
        self.assertEqual(["Upgrade command", zsv._upgrade_command(tracker)], rows[6])


if __name__ == "__main__":
    unittest.main()
