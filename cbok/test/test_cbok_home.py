import configparser
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from cbok import settings
from cbok import utils


class CbokHomeTest(unittest.TestCase):
    def test_defaults_to_configured_editor_and_me_company(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            home = root / "VSCode" / "me" / "cbok"
            home.mkdir(parents=True)
            conf = configparser.ConfigParser()
            conf.read_dict({"default": {"editor": "VSCode"}})

            with mock.patch.dict("os.environ", {"CBOK_HOME": ""}), \
                    mock.patch.object(settings, "Workspace", str(root)), \
                    mock.patch.object(settings, "CONF", conf):
                self.assertEqual(str(home), utils.assert_cbok_home())

    def test_reports_missing_workspace_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            stderr = io.StringIO()
            with mock.patch.dict("os.environ", {"CBOK_HOME": ""}), \
                    mock.patch.object(settings, "Workspace", temp), \
                    redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
                utils.assert_cbok_home()

            self.assertEqual(1, caught.exception.code)
            self.assertEqual("cbok: home not found.\n", stderr.getvalue())

    def test_uses_explicit_cbok_home(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()

            with mock.patch.dict("os.environ", {"CBOK_HOME": str(root)}):
                self.assertEqual(str(root), utils.assert_cbok_home())

    def test_rejects_missing_explicit_home(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "missing"
            stderr = io.StringIO()
            with mock.patch.dict("os.environ", {"CBOK_HOME": str(home)}), \
                    redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
                utils.assert_cbok_home()

            self.assertEqual(1, caught.exception.code)
            self.assertEqual("cbok: home not found.\n", stderr.getvalue())
