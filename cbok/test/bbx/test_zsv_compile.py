import configparser
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from cbok.bbx.zsv import compile
from cbok.bbx.zsv import worktree_container
from cbok.conf import config as cbok_config


class FakeWorktreeContainerStore:
    def __init__(self):
        self.records = {}

    def get_or_create(self, defaults):
        existing = self.records.get(defaults.worktree_key)
        if existing:
            return existing, False
        self.records[defaults.worktree_key] = defaults
        return defaults, True

    def save(self, record, update_fields=None):
        self.records[record.worktree_key] = record

    def find_by_container_name(self, container_name):
        for record in self.records.values():
            if record.container_name == container_name:
                return record
        return None


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.containers = set()

    def run_command(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]:
            script = cmd[-1]
            if "docker inspect" in script:
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            if "docker create" in script:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _conf(**values):
    parser = configparser.ConfigParser()
    parser.add_section("zsv_compile")
    for key, value in values.items():
        parser.set("zsv_compile", key, str(value))
    return parser


class ZsvCompileTest(unittest.TestCase):
    def setUp(self):
        self._orig_conf = compile.settings.CONF
        self._orig_auto_detect_modules = compile.auto_detect_modules
        self._orig_git_summary = compile.git_summary
        self._orig_git = compile._git
        self._orig_local_jar_copy_root_for_root = compile._local_jar_copy_root_for_root
        self._orig_collect_changed_web_classes_files = compile.collect_changed_web_classes_files
        self._orig_default_compile_state_store = compile.default_compile_deploy_state_store
        self._orig_default_state_store = worktree_container.default_state_store
        self._worktree_store = FakeWorktreeContainerStore()
        self._compile_state_store = compile.InMemoryCompileDeployStateStore()
        compile.default_compile_deploy_state_store = lambda: self._compile_state_store
        worktree_container.default_state_store = lambda: self._worktree_store

    def tearDown(self):
        compile.settings.CONF = self._orig_conf
        compile.auto_detect_modules = self._orig_auto_detect_modules
        compile.git_summary = self._orig_git_summary
        compile._git = self._orig_git
        compile._local_jar_copy_root_for_root = self._orig_local_jar_copy_root_for_root
        compile.collect_changed_web_classes_files = self._orig_collect_changed_web_classes_files
        compile.default_compile_deploy_state_store = self._orig_default_compile_state_store
        worktree_container.default_state_store = self._orig_default_state_store

    def test_remote_docker_conf_reads_optional_values(self):
        compile.settings.CONF = _conf(
            remote_docker_image="zstack-buildbin:debug7-arm64",
            remote_docker_platform="linux/arm64",
            remote_docker_host="http://172.26.50.70:2375",
            remote_docker_workdir="/zwork",
            remote_docker_m2_volume="zsv-m2",
        )

        conf = compile.remote_docker_compile_from_conf()

        self.assertEqual("zstack-buildbin:debug7-arm64", conf.image)
        self.assertEqual("linux/arm64", conf.platform)
        self.assertEqual("tcp://172.26.50.70:2375", conf.docker_host)
        self.assertEqual("/zwork", conf.workdir)
        self.assertEqual("auto", conf.container_name)
        self.assertEqual("zsv-m2", conf.m2_volume)
        self.assertFalse(hasattr(conf, "premium_source"))

    def test_remote_docker_conf_defaults_to_worktree_scoped_m2(self):
        compile.settings.CONF = _conf()

        conf = compile.remote_docker_compile_from_conf()

        self.assertEqual("auto", conf.m2_volume)

    def test_compile_deploy_state_key_is_scoped_to_base_ref(self):
        compile.settings.CONF = _conf(base_ref="origin/feature")
        remote = compile.remote_docker_compile_from_conf()
        feature_key = compile.compile_worktree_key("/zstack", "/premium", remote)

        compile.settings.CONF = _conf(base_ref="origin/zsv_5.1.0")
        zsv_key = compile.compile_worktree_key("/zstack", "/premium", remote)

        self.assertNotEqual(feature_key, zsv_key)

    def test_validate_changed_paths_base_ref_fetches_upstream_branch_first(self):
        compile.settings.CONF = _conf(base_ref="origin/feature/zsv")
        calls = []

        def fake_git(repo, *args):
            calls.append(args)
            if args == ("remote", "get-url", "origin"):
                return subprocess.CompletedProcess(["git"], 0, "git@example.invalid/repo.git\n", "")
            if args == ("fetch", "origin", "+refs/heads/feature/zsv:refs/remotes/origin/feature/zsv"):
                return subprocess.CompletedProcess(["git"], 0, "", "")
            if args == ("merge-base", "--is-ancestor", "origin/feature/zsv", "HEAD"):
                return subprocess.CompletedProcess(["git"], 0, "", "")
            raise AssertionError("unexpected git command: %s" % (args,))

        compile._git = fake_git

        self.assertTrue(compile.validate_changed_paths_base_ref("/repo"))
        self.assertEqual([
            ("remote", "get-url", "origin"),
            ("fetch", "origin", "+refs/heads/feature/zsv:refs/remotes/origin/feature/zsv"),
            ("merge-base", "--is-ancestor", "origin/feature/zsv", "HEAD"),
        ], calls)

    def test_zsv_compile_config_does_not_expose_profile_switch(self):
        option_names = [opt.name for opt in cbok_config.ZSV_COMPILE.options]

        self.assertNotIn("run_maven_profile_premium", option_names)
        self.assertNotIn("remote_docker_premium_source", option_names)
        self.assertIn("base_ref", option_names)

    def test_run_compile_flow_requires_zstack_root(self):
        runner = FakeRunner()

        with self.assertLogs(compile.LOG.name, level="ERROR") as logs:
            rc = compile.run_compile_flow(
                address=None,
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=True,
                premium_root="/repo/premium",
                runner=runner,
            )

        self.assertEqual(1, rc)
        self.assertIn("--zstack-root is required", "\n".join(logs.output))
        self.assertEqual([], runner.calls)

    def test_run_compile_flow_defaults_to_worktree_container_name(self):
        compile.settings.CONF = _conf(
            remote_docker_host="tcp://172.26.50.70:2375",
            remote_docker_image="zstack-buildbin:debug7-arm64",
            base_ref="",
        )
        compile.auto_detect_modules = lambda _root, _premium_root=None: (["plugin/foo"], [])
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            (root / "plugin" / "foo").mkdir(parents=True)
            premium.mkdir(parents=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "plugin" / "foo" / "pom.xml").write_text(
                "<project/>", encoding="utf-8")
            runner = FakeRunner()

            rc = compile.run_compile_flow(
                address=None,
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=True,
                zstack_root=str(root),
                premium_root=str(premium),
                runner=runner,
            )

        self.assertEqual(0, rc)
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        self.assertTrue(any("--name cbok-zsv-worktree-zstack-" in script for script in shell_scripts))
        self.assertFalse(any("zsv-remote" in script for script in shell_scripts))

    def test_run_compile_flow_uses_remote_docker_daemon_without_bind_mounts(self):
        compile.settings.CONF = _conf(
            remote_docker_image="registry.docker.zstack.io:80/buildbin:debug7",
            remote_docker_platform="linux/amd64",
            remote_docker_host="http://172.26.50.70:2375",
            remote_docker_workdir="/work",
            remote_docker_m2_volume="zsv-m2",
            base_ref="",
        )
        compile.auto_detect_modules = lambda _root, _premium_root=None: (["plugin/foo"], [])
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            (root / "plugin" / "foo").mkdir(parents=True)
            (root / "testlib").mkdir(parents=True)
            (premium / "testlib-premium").mkdir(parents=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "plugin" / "foo" / "pom.xml").write_text("<project/>", encoding="utf-8")
            runner = FakeRunner()

            rc = compile.run_compile_flow(
                address=None,
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=True,
                zstack_root=str(root),
                premium_root=str(premium),
                runner=runner,
            )

        self.assertEqual(0, rc)
        self.assertFalse(
            any(isinstance(cmd, list) and cmd[:2] == ["docker", "run"] for cmd, _kwargs in runner.calls)
        )
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        self.assertTrue(any("DOCKER_HOST=tcp://172.26.50.70:2375 docker create" in script for script in shell_scripts))
        self.assertTrue(any("--platform linux/amd64" in script for script in shell_scripts))
        self.assertTrue(
            any("docker exec -i cbok-zsv-worktree-zstack-" in script and "/tmp/cbok-zsv-src/zstack" in script for script in shell_scripts)
        )
        archive_scripts = [script for script in shell_scripts if "tar $tar_extra_opts -C" in script and "docker exec -i" in script]
        self.assertTrue(any("COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 tar $tar_extra_opts -C" in script for script in archive_scripts))
        self.assertTrue(any("--no-xattrs" in script and "--no-mac-metadata" in script for script in archive_scripts))
        self.assertTrue(any("--exclude '._*'" in script for script in archive_scripts))
        self.assertTrue(any("--exclude '*/._*'" in script for script in archive_scripts))
        self.assertTrue(any("--exclude .DS_Store" in script for script in archive_scripts))
        docker_cp_scripts = [
            script for script in shell_scripts
            if "DOCKER_HOST=tcp://172.26.50.70:2375 docker cp cbok-zsv-worktree-zstack-" in script
            and ":/tmp/cbok-zsv-out/" in script
        ]
        self.assertTrue(docker_cp_scripts)
        self.assertFalse(any(str(root) in script for script in docker_cp_scripts))
        self.assertFalse(any(str(premium) in script for script in docker_cp_scripts))
        self.assertTrue(any("cbok-zsv-jars-" in script for script in docker_cp_scripts))
        build_scripts = [script for script in shell_scripts if "docker exec cbok-zsv-worktree-zstack-" in script and " bash -lc" in script]
        self.assertGreaterEqual(len(build_scripts), 3)
        self.assertTrue(any("./runMavenProfile premium" in script for script in build_scripts))
        self.assertFalse(any("mvn -T 12 -Dmaven.test.skip=true -P premium clean install" in script for script in build_scripts))
        self.assertTrue(any("cd /work/zstack/testlib" in script for script in build_scripts))
        self.assertNotIn("mvn -DskipTests clean install -pl plugin/foo", build_scripts[-1])
        self.assertIn("sync_target /work/zstack /tmp/cbok-zsv-out/zstack plugin/foo", build_scripts[-1])
        self.assertIn('local props="$target/maven-archiver/pom.properties"', build_scripts[-1])
        self.assertIn('cp "$jar" "$dest/"', build_scripts[-1])
        self.assertNotIn('rsync -a --delete "$target"/ "$dest"/', build_scripts[-1])

    def test_run_compile_flow_rejects_configured_premium_branch_mismatch(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://172.26.50.70:2375", base_ref="")
        compile.auto_detect_modules = lambda _root, _premium_root=None: (["plugin/foo"], [])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            (root / "plugin" / "foo").mkdir(parents=True)
            premium.mkdir(parents=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "plugin" / "foo" / "pom.xml").write_text(
                "<project/>", encoding="utf-8")

            branches = {
                str(root.resolve()): "feature-a",
                str(premium.resolve()): "feature-b",
            }

            def fake_git(repo, *args):
                if args == ("rev-parse", "--abbrev-ref", "HEAD"):
                    return subprocess.CompletedProcess(
                        ["git", "-C", repo, *args],
                        0,
                        branches[os.path.realpath(repo)] + "\n",
                        "",
                    )
                return subprocess.CompletedProcess(["git", "-C", repo, *args], 0, "", "")

            compile._git = fake_git
            runner = FakeRunner()

            with self.assertLogs(compile.LOG.name, level="ERROR") as logs:
                rc = compile.run_compile_flow(
                    address=None,
                    remote_lib=compile.DEFAULT_REMOTE_LIB,
                    no_deploy=True,
                    zstack_root=str(root),
                    premium_root=str(premium),
                    runner=runner,
                )

        self.assertEqual(1, rc)
        self.assertIn("zstack and premium branch names must be the same", "\n".join(logs.output))
        self.assertEqual([], runner.calls)

    def test_run_compile_flow_rejects_base_ref_before_detecting_modules(self):
        compile.settings.CONF = _conf(
            remote_docker_host="tcp://172.26.50.70:2375",
            base_ref="origin/feature",
        )

        def fail_auto_detect(_root, _premium_root=None):
            raise AssertionError("auto_detect_modules should not run when base_ref is invalid")

        compile.auto_detect_modules = fail_auto_detect

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            root.mkdir()
            premium.mkdir()
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")

            def fake_git(repo, *args):
                if args == ("rev-parse", "--abbrev-ref", "HEAD"):
                    return subprocess.CompletedProcess(["git"], 0, "feature\n", "")
                if args == ("merge-base", "--is-ancestor", "origin/feature", "HEAD"):
                    return subprocess.CompletedProcess(["git"], 1, "", "")
                return subprocess.CompletedProcess(["git"], 0, "", "")

            compile._git = fake_git
            runner = FakeRunner()

            with self.assertLogs(compile.LOG.name, level="ERROR") as logs:
                rc = compile.run_compile_flow(
                    address=None,
                    remote_lib=compile.DEFAULT_REMOTE_LIB,
                    no_deploy=True,
                    zstack_root=str(root),
                    premium_root=str(premium),
                    runner=runner,
                )

        self.assertEqual(1, rc)
        self.assertIn("Configured base ref origin/feature is not an ancestor", "\n".join(logs.output))
        self.assertEqual([], runner.calls)

    def test_auto_detect_modules_combines_worktree_changes_and_head_commit(self):
        compile.settings.CONF = _conf(base_ref="")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            for module in ("utils", "identity"):
                (root / module).mkdir(parents=True)
                (root / module / "pom.xml").write_text("<project/>", encoding="utf-8")
            for module in ("volumebackup", "mevoco"):
                (premium / module).mkdir(parents=True)
                (premium / module / "pom.xml").write_text("<project/>", encoding="utf-8")

            def fake_git(repo, *args):
                repo = os.path.realpath(repo)
                if args == ("diff", "--name-only", "HEAD"):
                    out = {
                        os.path.realpath(root): "utils/src/main/java/org/zstack/utils/Digest.java\n",
                        os.path.realpath(premium): "volumebackup/src/main/java/org/zstack/storage/backup/BackupQosStruct.java\n",
                    }.get(repo, "")
                    return subprocess.CompletedProcess(["git"], 0, out, "")
                if args == ("ls-files", "--others", "--exclude-standard"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("rev-parse", "--verify", "HEAD^"):
                    return subprocess.CompletedProcess(["git"], 0, "parent\n", "")
                if args == ("diff", "--name-only", "HEAD^", "HEAD"):
                    out = {
                        os.path.realpath(root): "identity/src/main/java/org/zstack/identity/Account.java\n",
                        os.path.realpath(premium): "mevoco/src/main/java/org/zstack/mevoco/MevocoGlobalProperty.java\n",
                    }.get(repo, "")
                    return subprocess.CompletedProcess(["git"], 0, out, "")
                return subprocess.CompletedProcess(["git"], 0, "", "")

            compile._git = fake_git

            main, prem = compile.auto_detect_modules(str(root), str(premium))

        self.assertEqual(["utils", "identity"], main)
        self.assertEqual(["volumebackup", "mevoco"], prem)

    def test_auto_detect_modules_falls_back_to_head_when_no_worktree_module_changed(self):
        compile.settings.CONF = _conf(base_ref="")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            (root / "identity").mkdir(parents=True)
            (root / "identity" / "pom.xml").write_text("<project/>", encoding="utf-8")
            (premium / "mevoco").mkdir(parents=True)
            (premium / "mevoco" / "pom.xml").write_text("<project/>", encoding="utf-8")

            def fake_git(repo, *args):
                repo = os.path.realpath(repo)
                if args == ("diff", "--name-only", "HEAD"):
                    return subprocess.CompletedProcess(["git"], 0, "README.md\n", "")
                if args == ("ls-files", "--others", "--exclude-standard"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("rev-parse", "--verify", "HEAD^"):
                    return subprocess.CompletedProcess(["git"], 0, "parent\n", "")
                if args == ("diff", "--name-only", "HEAD^", "HEAD"):
                    out = {
                        os.path.realpath(root): "identity/src/main/java/org/zstack/identity/Account.java\n",
                        os.path.realpath(premium): "mevoco/src/main/java/org/zstack/mevoco/MevocoGlobalProperty.java\n",
                    }.get(repo, "")
                    return subprocess.CompletedProcess(["git"], 0, out, "")
                return subprocess.CompletedProcess(["git"], 0, "", "")

            compile._git = fake_git

            main, prem = compile.auto_detect_modules(str(root), str(premium))

        self.assertEqual(["identity"], main)
        self.assertEqual(["mevoco"], prem)

    def test_auto_detect_modules_uses_top_commit_even_when_upstream_exists(self):
        compile.settings.CONF = _conf(base_ref="")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            (root / "storage").mkdir(parents=True)
            (root / "storage" / "pom.xml").write_text("<project/>", encoding="utf-8")
            (premium / "crypto").mkdir(parents=True)
            (premium / "crypto" / "pom.xml").write_text("<project/>", encoding="utf-8")

            def fake_git(repo, *args):
                repo = os.path.realpath(repo)
                if args == ("diff", "--name-only", "HEAD"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("ls-files", "--others", "--exclude-standard"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"):
                    raise AssertionError("upstream must not be used to detect changed modules")
                if args == ("merge-base", "origin/feature", "HEAD"):
                    raise AssertionError("merge-base must not be used to detect changed modules")
                if args == ("diff", "--name-only", "base", "HEAD"):
                    raise AssertionError("base ref diff must not be used to detect changed modules")
                if args == ("rev-parse", "--verify", "HEAD^"):
                    return subprocess.CompletedProcess(["git"], 0, "parent\n", "")
                if args == ("diff", "--name-only", "HEAD^", "HEAD"):
                    out = {
                        os.path.realpath(root): "storage/src/main/java/org/zstack/storage/encrypt/RemoteOnly.java\n",
                        os.path.realpath(premium): "crypto/src/main/java/org/zstack/crypto/keyprovider/KeyProviderAvailabilityApiInterceptor.java\n",
                    }.get(repo, "")
                    return subprocess.CompletedProcess(["git"], 0, out, "")
                return subprocess.CompletedProcess(["git"], 0, "", "")

            compile._git = fake_git

            main, prem = compile.auto_detect_modules(str(root), str(premium))

        self.assertEqual(["storage"], main)
        self.assertEqual(["crypto"], prem)

    def test_changed_paths_uses_configured_base_ref(self):
        compile.settings.CONF = _conf(base_ref="origin/feature")
        calls = []

        def fake_git(repo, *args):
            calls.append(args)
            if args == ("diff", "--name-only", "origin/feature", "HEAD"):
                return subprocess.CompletedProcess(["git"], 0, "storage/Feature.java\n", "")
            raise AssertionError("unexpected git command: %s" % (args,))

        compile._git = fake_git

        paths = compile.changed_paths_from_head_commit("/repo")

        self.assertEqual(["storage/Feature.java"], paths)
        self.assertEqual([
            ("diff", "--name-only", "origin/feature", "HEAD"),
        ], calls)

    def test_auto_detect_modules_includes_implementers_of_changed_interfaces(self):
        compile.settings.CONF = _conf(base_ref="")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            interface_file = root / "storage" / "src" / "main" / "java" / "org" / "zstack" / "storage" / "encrypt" / "VolumeEncryptedResourceKeyBackend.java"
            implementer_file = premium / "crypto" / "src" / "main" / "java" / "org" / "zstack" / "crypto" / "keyprovider" / "KeyProviderResourceKeyBackendVolume.java"
            caller_file = premium / "volumebackup" / "src" / "main" / "java" / "org" / "zstack" / "storage" / "backup" / "VolumeBackupManagerImpl.java"
            for module in (root / "storage", premium / "crypto", premium / "volumebackup"):
                module.mkdir(parents=True)
                (module / "pom.xml").write_text("<project/>", encoding="utf-8")
            interface_file.parent.mkdir(parents=True)
            interface_file.write_text(
                "package org.zstack.storage.encrypt;\n"
                "public interface VolumeEncryptedResourceKeyBackend {\n"
                "    boolean checkBackupKeyProviderAttached(String backupUuid);\n"
                "}\n",
                encoding="utf-8",
            )
            implementer_file.parent.mkdir(parents=True)
            implementer_file.write_text(
                "package org.zstack.crypto.keyprovider;\n"
                "import org.zstack.storage.encrypt.VolumeEncryptedResourceKeyBackend;\n"
                "public class KeyProviderResourceKeyBackendVolume implements VolumeEncryptedResourceKeyBackend {\n"
                "}\n",
                encoding="utf-8",
            )
            caller_file.parent.mkdir(parents=True)
            caller_file.write_text(
                "package org.zstack.storage.backup;\n"
                "public class VolumeBackupManagerImpl {}\n",
                encoding="utf-8",
            )

            def fake_git(repo, *args):
                repo = os.path.realpath(repo)
                if args == ("diff", "--name-only", "HEAD"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("ls-files", "--others", "--exclude-standard"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("rev-parse", "--verify", "HEAD^"):
                    return subprocess.CompletedProcess(["git"], 0, "parent\n", "")
                if args == ("diff", "--name-only", "HEAD^", "HEAD"):
                    out = {
                        os.path.realpath(root): "storage/src/main/java/org/zstack/storage/encrypt/VolumeEncryptedResourceKeyBackend.java\n",
                        os.path.realpath(premium): "volumebackup/src/main/java/org/zstack/storage/backup/VolumeBackupManagerImpl.java\n",
                    }.get(repo, "")
                    return subprocess.CompletedProcess(["git"], 0, out, "")
                return subprocess.CompletedProcess(["git"], 0, "", "")

            compile._git = fake_git

            main, prem = compile.auto_detect_modules(str(root), str(premium))

        self.assertEqual(["storage"], main)
        self.assertEqual(["volumebackup", "crypto"], prem)

    def test_collect_built_jars_uses_maven_main_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            target = premium / "mevoco" / "target"
            (target / "maven-archiver").mkdir(parents=True)
            (target / "maven-archiver" / "pom.properties").write_text(
                "groupId=org.zstack\nartifactId=mevoco\nversion=5.0.0\n",
                encoding="utf-8",
            )
            main_jar = target / "mevoco-5.0.0.jar"
            main_jar.write_bytes(b"main")
            (target / "mevoco-fat.jar").write_bytes(b"fat")

            jars = compile.collect_built_jars(
                str(root),
                [],
                ["mevoco"],
                premium_root=str(premium),
            )

        self.assertEqual([str(main_jar)], jars)

    def test_collect_web_classes_files_maps_spring_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            main_xml = root / "conf" / "springConfigXml" / "core.xml"
            premium_xml = premium / "conf" / "springConfigXml" / "crypto.xml"
            main_xml.parent.mkdir(parents=True)
            premium_xml.parent.mkdir(parents=True)
            main_xml.write_text("<beans/>", encoding="utf-8")
            premium_xml.write_text("<beans/>", encoding="utf-8")

            files = compile.collect_web_classes_files(
                str(root),
                ["conf/springConfigXml/core.xml", "identity/src/main/java/Foo.java"],
                ["conf/springConfigXml/crypto.xml"],
                str(premium),
            )

        mapped = {item.relative_path: item.source for item in files}
        self.assertEqual(str(main_xml), mapped["springConfigXml/core.xml"])
        self.assertEqual(str(premium_xml), mapped["springConfigXml/crypto.xml"])

    def test_deploy_uses_unique_remote_staging_per_compile(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://172.26.50.70:2375", base_ref="")
        compile.auto_detect_modules = lambda _root, _premium_root=None: (["identity"], [])
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            worktree_target = root / "identity" / "target"
            worktree_target.mkdir(parents=True)
            premium.mkdir(parents=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "identity" / "pom.xml").write_text("<project/>", encoding="utf-8")
            (worktree_target / "identity-5.0.0.jar").write_bytes(b"wrong")
            jar_copy_root = Path(td) / "jar-copy"
            jar_copy_target = jar_copy_root / "zstack" / "identity" / "target"
            jar_copy_target.mkdir(parents=True)
            copied_jar = jar_copy_target / "identity-5.0.0.jar"
            copied_jar.write_bytes(b"jar")
            compile._local_jar_copy_root_for_root = lambda _root: str(jar_copy_root)
            runner = FakeRunner()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = compile.run_compile_flow(
                    address="172.26.213.50",
                    remote_lib=compile.DEFAULT_REMOTE_LIB,
                    no_deploy=False,
                    zstack_root=str(root),
                    premium_root=str(premium),
                    runner=runner,
                )

        self.assertEqual(0, rc)
        self.assertIn(
            "WARNING: compile finished but MN has not been restarted. Run: cbok zsv restart_mn --address 172.26.213.50",
            stdout.getvalue(),
        )
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        scp_scripts = [s for s in shell_scripts if "zsv_scp_jars_to_remote" in s]
        install_scripts = [s for s in shell_scripts if "zsv_remote_install_jars_from_staging" in s]
        self.assertEqual(1, len(scp_scripts))
        self.assertEqual(1, len(install_scripts))
        staging_prefix = f"{compile.REMOTE_JAR_STAGING}-zstack-"
        self.assertIn(staging_prefix, scp_scripts[0])
        self.assertIn(staging_prefix, install_scripts[0])
        self.assertIn(str(copied_jar), scp_scripts[0])
        self.assertNotIn(str(worktree_target / "identity-5.0.0.jar"), scp_scripts[0])

    def test_deploy_syncs_changed_web_classes_archive(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://172.26.50.70:2375", base_ref="")
        compile.auto_detect_modules = lambda _root, _premium_root=None: (["identity"], [])
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            worktree_target = root / "identity" / "target"
            worktree_target.mkdir(parents=True)
            premium_xml = premium / "conf" / "springConfigXml" / "crypto.xml"
            premium_xml.parent.mkdir(parents=True)
            premium_xml.write_text("<beans/>", encoding="utf-8")
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "identity" / "pom.xml").write_text("<project/>", encoding="utf-8")
            jar_copy_root = Path(td) / "jar-copy"
            jar_copy_target = jar_copy_root / "zstack" / "identity" / "target"
            jar_copy_target.mkdir(parents=True)
            (jar_copy_target / "identity-5.0.0.jar").write_bytes(b"jar")
            compile._local_jar_copy_root_for_root = lambda _root: str(jar_copy_root)
            compile.collect_changed_web_classes_files = lambda _root, _premium_root=None: [
                compile.WebClassesFile(str(premium_xml), "springConfigXml/crypto.xml")
            ]
            runner = FakeRunner()

            rc = compile.run_compile_flow(
                address="172.26.213.50",
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=False,
                zstack_root=str(root),
                premium_root=str(premium),
                runner=runner,
            )

        self.assertEqual(0, rc)
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        self.assertTrue(any("zsv_scp_web_classes_archive_to_remote" in script for script in shell_scripts))
        self.assertTrue(any("zsv_remote_install_web_classes_archive" in script for script in shell_scripts))
        self.assertTrue(any("/usr/local/zstack/apache-tomcat/webapps/zstack/WEB-INF/classes" in script for script in shell_scripts))

    def test_deploy_replays_previous_modules_removed_from_current_diff(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://172.26.50.70:2375", base_ref="")
        compile.auto_detect_modules = lambda _root, _premium_root=None: (["identity"], [])
        compile.collect_changed_web_classes_files = lambda _root, _premium_root=None: []
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            for module in ("identity", "storage"):
                (root / module / "target").mkdir(parents=True)
                (root / module / "pom.xml").write_text("<project/>", encoding="utf-8")
            premium.mkdir(parents=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            jar_copy_root = Path(td) / "jar-copy"
            for module in ("identity", "storage"):
                target = jar_copy_root / "zstack" / module / "target"
                target.mkdir(parents=True)
                (target / f"{module}-5.0.0.jar").write_bytes(b"jar")
            compile._local_jar_copy_root_for_root = lambda _root: str(jar_copy_root)
            remote = compile.remote_docker_compile_from_conf()
            worktree_key = compile.compile_worktree_key(str(root), str(premium), remote)
            self._compile_state_store.save_selection(
                worktree_key,
                str(root),
                str(premium),
                compile.CompileDeploySelection(["storage"], [], []),
            )
            runner = FakeRunner()

            rc = compile.run_compile_flow(
                address="172.26.213.50",
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=False,
                zstack_root=str(root),
                premium_root=str(premium),
                runner=runner,
            )

        self.assertEqual(0, rc)
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        scp_scripts = [s for s in shell_scripts if "zsv_scp_jars_to_remote" in s]
        self.assertEqual(1, len(scp_scripts))
        self.assertIn("identity-5.0.0.jar", scp_scripts[0])
        self.assertIn("storage-5.0.0.jar", scp_scripts[0])
        selection = self._compile_state_store.load_selection(worktree_key)
        self.assertEqual(["identity"], selection.main_modules)
        self.assertEqual([], selection.premium_modules)

    def test_deploy_replays_previous_web_classes_when_current_diff_is_empty(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://172.26.50.70:2375", base_ref="")
        compile.auto_detect_modules = lambda _root, _premium_root=None: ([], [])
        compile.collect_changed_web_classes_files = lambda _root, _premium_root=None: []
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            premium = Path(td) / "premium"
            premium_xml = premium / "conf" / "springConfigXml" / "crypto.xml"
            premium_xml.parent.mkdir(parents=True)
            premium_xml.write_text("<beans/>", encoding="utf-8")
            (root / "pom.xml").parent.mkdir(parents=True, exist_ok=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            jar_copy_root = Path(td) / "jar-copy"
            compile._local_jar_copy_root_for_root = lambda _root: str(jar_copy_root)
            remote = compile.remote_docker_compile_from_conf()
            worktree_key = compile.compile_worktree_key(str(root), str(premium), remote)
            self._compile_state_store.save_selection(
                worktree_key,
                str(root),
                str(premium),
                compile.CompileDeploySelection(
                    [],
                    [],
                    [
                        compile.CompileWebClassesState(
                            "premium",
                            "conf/springConfigXml/crypto.xml",
                            "springConfigXml/crypto.xml",
                        )
                    ],
                ),
            )
            runner = FakeRunner()

            rc = compile.run_compile_flow(
                address="172.26.213.50",
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=False,
                zstack_root=str(root),
                premium_root=str(premium),
                runner=runner,
            )

        self.assertEqual(0, rc)
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        self.assertTrue(any("zsv_scp_web_classes_archive_to_remote" in script for script in shell_scripts))
        self.assertTrue(any("zsv_remote_install_web_classes_archive" in script for script in shell_scripts))
        selection = self._compile_state_store.load_selection(worktree_key)
        self.assertEqual([], selection.main_modules)
        self.assertEqual([], selection.premium_modules)
        self.assertEqual([], selection.web_classes)

if __name__ == "__main__":
    unittest.main()
