import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cbok.conf.files import read_cbok_conf, resolve_cbok_conf_path


class CbokConfFilesTest(unittest.TestCase):
    def test_resolve_cbok_conf_path_defaults_to_repo_root(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            path = resolve_cbok_conf_path("/repo/root")

        self.assertEqual("/repo/root/cbok.conf", path)

    def test_resolve_cbok_conf_path_uses_env_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "custom.conf")
            with mock.patch.dict(os.environ, {"CBOK_CONF": raw_path}):
                path = resolve_cbok_conf_path("/repo/root")

        self.assertEqual(raw_path, path)

    def test_resolve_cbok_conf_path_expands_user_and_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "CBOK_CONF_DIR": tmpdir,
                    "CBOK_CONF": "$CBOK_CONF_DIR/../custom.conf",
                },
            ):
                path = resolve_cbok_conf_path("/repo/root")

        self.assertEqual(str(Path(tmpdir).parent / "custom.conf"), path)

    def test_read_cbok_conf_reads_resolved_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conf_path = os.path.join(tmpdir, "cbok.conf")
            with open(conf_path, "w", encoding="utf-8") as fp:
                fp.write("[default]\nworkspace = /tmp/cbok\n")

            conf = read_cbok_conf(conf_path)

        self.assertEqual("/tmp/cbok", conf.get("default", "workspace"))
