import configparser
import unittest

from cbok.bbx.zsv import config as zsv_config


def _conf(zsv_values=None, zsv_compile_values=None):
    parser = configparser.ConfigParser()
    if zsv_values is not None:
        parser.add_section("zsv")
        for key, value in zsv_values.items():
            parser.set("zsv", key, str(value))
    if zsv_compile_values is not None:
        parser.add_section("zsv_compile")
        for key, value in zsv_compile_values.items():
            parser.set("zsv_compile", key, str(value))
    return parser


class ZsvConfigTest(unittest.TestCase):
    def setUp(self):
        self._orig_conf = zsv_config.settings.CONF
        self._orig_workspace = zsv_config.settings.Workspace

    def tearDown(self):
        zsv_config.settings.CONF = self._orig_conf
        zsv_config.settings.Workspace = self._orig_workspace

    def test_base_ref_prefers_shared_zsv_config(self):
        zsv_config.settings.CONF = _conf(
            zsv_values={"base_ref": "origin/shared"},
            zsv_compile_values={"base_ref": "origin/legacy"},
        )

        self.assertEqual("origin/shared", zsv_config.zsv_base_ref())

    def test_base_ref_falls_back_to_legacy_compile_config(self):
        zsv_config.settings.CONF = _conf(
            zsv_compile_values={"base_ref": "origin/legacy"},
        )

        self.assertEqual("origin/legacy", zsv_config.zsv_base_ref())

    def test_zstack_root_is_derived_from_workspace(self):
        zsv_config.settings.CONF = _conf(zsv_values={"zstack_root": "/ignored/zstack"})
        zsv_config.settings.Workspace = "/workspace"

        self.assertEqual(
            "/workspace/Cursor/zs/zstack",
            zsv_config.zstack_root_from_workspace(),
        )
