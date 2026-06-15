import configparser
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cbok.bbx.zsv import compile


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run_command(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0)


def _conf(**values):
    parser = configparser.ConfigParser()
    parser.add_section("zsv_compile")
    parser.set("zsv_compile", "docker_container", values.pop("docker_container", "none"))
    parser.set("zsv_compile", "docker_zstack_root", values.pop("docker_zstack_root", "/root/zstack"))
    for key, value in values.items():
        parser.set("zsv_compile", key, str(value))
    return parser


class ZsvCompileTest(unittest.TestCase):
    def setUp(self):
        self._orig_conf = compile.settings.CONF
        self._orig_auto_detect_modules = compile.auto_detect_modules
        self._orig_git_summary = compile.git_summary

    def tearDown(self):
        compile.settings.CONF = self._orig_conf
        compile.auto_detect_modules = self._orig_auto_detect_modules
        compile.git_summary = self._orig_git_summary

    def test_docker_tmpfs_conf_reads_optional_values(self):
        compile.settings.CONF = _conf(
            docker_tmpfs_enabled="true",
            docker_tmpfs_image="zstack-buildbin:debug7-arm64",
            docker_tmpfs_platform="linux/arm64",
            docker_tmpfs_size="8g",
            docker_tmpfs_workdir="/zwork",
            docker_tmpfs_container_name="zsv-tmpfs",
            docker_tmpfs_m2_volume="zsv-m2",
            docker_tmpfs_preload_m2="false",
            docker_tmpfs_m2_source="~/.m2/repository",
            docker_tmpfs_premium_source="../premium",
        )

        conf = compile.docker_tmpfs_compile_from_conf()

        self.assertTrue(conf.enabled)
        self.assertEqual("zstack-buildbin:debug7-arm64", conf.image)
        self.assertEqual("linux/arm64", conf.platform)
        self.assertEqual("8g", conf.size)
        self.assertEqual("/zwork", conf.workdir)
        self.assertEqual("zsv-tmpfs", conf.container_name)
        self.assertEqual("zsv-m2", conf.m2_volume)
        self.assertFalse(conf.preload_m2)
        self.assertEqual("~/.m2/repository", conf.m2_source)
        self.assertEqual("../premium", conf.premium_source)

    def test_run_compile_flow_uses_docker_tmpfs_container(self):
        compile.settings.CONF = _conf(
            docker_container="legacy-amd64-container",
            docker_tmpfs_enabled="true",
            docker_tmpfs_image="zstack-buildbin:debug7-arm64",
            docker_tmpfs_platform="linux/arm64",
            docker_tmpfs_size="6g",
            docker_tmpfs_workdir="/work",
            docker_tmpfs_container_name="zsv-tmpfs",
            docker_tmpfs_m2_volume="zsv-m2",
            docker_tmpfs_preload_m2="true",
            docker_tmpfs_m2_source="~/.m2/repository",
        )
        compile.auto_detect_modules = lambda _root: (["plugin/foo"], [])
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            (root / "plugin" / "foo").mkdir(parents=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "plugin" / "foo" / "pom.xml").write_text(
                "<project/>", encoding="utf-8")
            runner = FakeRunner()

            rc = compile.run_compile_flow(
                address=None,
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=True,
                zstack_root=str(root),
                runner=runner,
            )

        self.assertEqual(0, rc)
        docker_runs = [
            cmd for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["docker", "run"]
        ]
        self.assertEqual(1, len(docker_runs))
        docker_cmd = docker_runs[0]
        self.assertIn("--platform", docker_cmd)
        self.assertIn("linux/arm64", docker_cmd)
        self.assertIn("--tmpfs", docker_cmd)
        self.assertIn("/work:rw,exec,size=6g", docker_cmd)
        self.assertIn("-v", docker_cmd)
        self.assertIn("zsv-m2:/root/.m2", docker_cmd)
        self.assertIn("zstack-buildbin:debug7-arm64", docker_cmd)
        script = docker_cmd[-1]
        self.assertIn("rsync -a --delete --exclude .git --exclude target /src/zstack/ /work/zstack/", script)
        self.assertIn("rsync -a --ignore-existing /host-m2/ /root/.m2/repository/", script)
        self.assertIn("mvn -DskipTests clean install -pl plugin/foo", script)
        self.assertIn("find \"$work_root\" -type d -name target", script)
        self.assertIn("sync_targets /work/zstack /out/zstack", script)
        self.assertFalse(any(call[0][:2] == ["docker", "exec"] for call in runner.calls))


if __name__ == "__main__":
    unittest.main()
