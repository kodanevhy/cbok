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

    def tearDown(self):
        zsv_config.settings.CONF = self._orig_conf

    def test_base_ref_reads_shared_zsv_config(self):
        zsv_config.settings.CONF = _conf(
            zsv_values={"base_ref": "origin/shared"},
        )

        self.assertEqual("origin/shared", zsv_config.zsv_base_ref())

    def test_base_ref_ignores_compile_config(self):
        zsv_config.settings.CONF = _conf(
            zsv_compile_values={"remote_docker_host": "tcp://172.26.50.70:2375"},
        )

        self.assertEqual("", zsv_config.zsv_base_ref())

    def test_sync_repos_reads_trimmed_repository_names(self):
        zsv_config.settings.CONF = _conf(
            zsv_values={"sync_repos": "zsvirt, zsvirt-ee,zsvirt-utility"},
        )

        self.assertEqual(
            ("zsvirt", "zsvirt-ee", "zsvirt-utility"),
            zsv_config.zsv_sync_repos(),
        )

    def test_missing_sync_repos_does_not_select_repositories_implicitly(self):
        for conf in (_conf(), _conf(zsv_values={"base_ref": "origin/main"})):
            with self.subTest(sections=conf.sections()):
                zsv_config.settings.CONF = conf
                self.assertEqual((), zsv_config.zsv_sync_repos())
