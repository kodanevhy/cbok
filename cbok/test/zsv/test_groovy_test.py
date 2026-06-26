import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cbok.bbx.zsv import groovy_test
from cbok.bbx.zsv import worktree_container


class FakeRunner:
    def __init__(self):
        self.commands = []
        self.containers = set()

    def run_command(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        if cmd[:6] == ["git", "-C", cmd[2], "worktree", "add", "--detach"]:
            shutil.copytree(Path(cmd[2]), Path(cmd[6]))
        if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]:
            return self._run_shell(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    def _run_shell(self, cmd):
        script = cmd[-1]
        if "docker inspect" in script:
            name = shlex.split(script)[-1]
            if name in self.containers:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="true\n", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
        if "docker create" in script:
            parts = shlex.split(script)
            if "--name" in parts:
                self.containers.add(parts[parts.index("--name") + 1])
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "cat /tmp/cbok-zsv-groovy-run.exit" in script:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="0\n", stderr="")
        if "cat /tmp/cbok-zsv-groovy-run.log" in script:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


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


class GroovyContainerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_default_state_store = worktree_container.default_state_store
        self._worktree_store = FakeWorktreeContainerStore()
        worktree_container.default_state_store = lambda: self._worktree_store
        self.addCleanup(self._restore_state_store)
        self._orig_remote_docker_compile_from_conf = groovy_test.remote_docker_compile_from_conf
        self.addCleanup(self._restore_compile_conf)
        groovy_test.remote_docker_compile_from_conf = lambda _container_name="": groovy_test.RemoteDockerCompileConfig(
            image="compile-image:unit",
            platform="linux/amd64",
            docker_host="",
            workdir="/work",
            container_name="",
            m2_volume="zsv-m2",
        )
        self.root = Path(self.tmp.name)
        self.zstack_repo = self.root / "source-zstack"
        self.premium_repo = self.root / "source-premium"
        self.zstack_repo.mkdir()
        self.premium_repo.mkdir()
        self._write_minimal_repo_sources()

    def _restore_state_store(self):
        worktree_container.default_state_store = self._orig_default_state_store

    def _restore_compile_conf(self):
        groovy_test.remote_docker_compile_from_conf = self._orig_remote_docker_compile_from_conf

    def _write_minimal_repo_sources(self):
        (self.zstack_repo / "testlib").mkdir(parents=True)
        (self.premium_repo / "testlib-premium").mkdir(parents=True)
        self._write_module_pom(self.zstack_repo / "test/pom.xml")
        self._write_module_pom(self.premium_repo / "test-premium/pom.xml")
        self._write_file(
            self.zstack_repo
            / "test/src/test/groovy/org/zstack/test/integration/core/MustPassCase.groovy",
            "package org.zstack.test.integration.core\nclass MustPassCase {}\n",
        )
        self._write_file(
            self.zstack_repo
            / "test/src/test/groovy/org/zstack/test/integration/core/CoreLibraryTest.groovy",
            "package org.zstack.test.integration.core\nclass CoreLibraryTest {}\n",
        )
        self._write_file(
            self.zstack_repo / "test/src/test/groovy/TestGenerateApiHelper.groovy",
            "import org.junit.Test\nclass TestGenerateApiHelper { @Test void test() {} }\n",
        )
        self._write_file(
            self.zstack_repo / "test/src/test/groovy/Test3.groovy",
            "import org.zstack.testlib.Test\nclass Test3 extends Test {}\n",
        )
        self._write_file(
            self.zstack_repo
            / "test/src/test/groovy/org/zstack/test/integration/stabilisation/StabilityTestCase.groovy",
            "package org.zstack.test.integration.stabilisation\nclass StabilityTestCase extends StabilityTest {}\n",
        )
        self._write_file(
            self.premium_repo
            / "test-premium/src/test/groovy/org/zstack/test/integration/premium/logincontrol/LoginCase.groovy",
            "package org.zstack.test.integration.premium.logincontrol\nclass LoginCase {}\n",
        )
        self._write_file(
            self.premium_repo
            / "test-premium/src/test/groovy/org/zstack/test/integration/premium/logincontrol/LoginControlTest.groovy",
            "package org.zstack.test.integration.premium.logincontrol\nclass LoginControlTest {}\n",
        )
        self._write_file(
            self.premium_repo / "test-premium/src/test/groovy/CheckAPIResponseCase.groovy",
            "package org.zstack.test\nclass CheckAPIResponseCase extends PremiumSubCase {}\n",
        )
        self._write_file(
            self.premium_repo
            / "test-premium/src/test/groovy/org/zstack/test/integration/premium/ai/AITest.groovy",
            "package org.zstack.test.integration.premium.ai\nclass AITest extends TestPremium {}\n",
        )
        self._write_file(
            self.premium_repo
            / "test-premium/src/test/groovy/org/zstack/test/integration/premium/ai/DeployModelCase.groovy",
            "package org.zstack.test.integration.premium.ai\nclass DeployModelCase extends AICaseStub {}\n",
        )
        self._write_file(
            self.premium_repo
            / "test-premium/src/test/groovy/org/zstack/test/unittest/check/RequestParamCheckCase.java",
            "package org.zstack.test.unittest.check;\nimport org.junit.Test;\npublic class RequestParamCheckCase { @Test public void test() {} }\n",
        )

    @staticmethod
    def _write_file(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _write_module_pom(self, path):
        self._write_file(
            path,
            (
                "<project>\n"
                "  <build>\n"
                "    <sourceDirectory>src/test/groovy</sourceDirectory>\n"
                "    <testSourceDirectory>src/test/groovy</testSourceDirectory>\n"
                "  </build>\n"
                "</project>\n"
            ),
        )

    def _shell_scripts(self, runner):
        return [
            cmd[-1] for cmd, _kwargs in runner.commands
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]

    def test_core_case_runs_via_nearest_suite_in_persistent_worktree_container(self):
        runner = FakeRunner()
        work_root = self.root / "run"

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="org.zstack.test.integration.core.MustPassCase",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(work_root),
            runner=runner,
        )

        self.assertEqual(0, rc)
        self.assertEqual("../premium", os.readlink(work_root / "zstack" / "premium"))
        self.assertFalse(
            (
                work_root
                / "zstack/test/src/test/groovy/org/zstack/test/integration/ContainerGroovyTest.groovy"
            ).exists()
        )
        self.assertEqual(
            "org.zstack.test.integration.core.MustPassCase\n",
            (work_root / "cases.txt").read_text(encoding="utf-8"),
        )
        self.assertFalse(
            any(isinstance(cmd, list) and cmd[:2] == ["docker", "run"] for cmd, _kwargs in runner.commands)
        )
        shell_scripts = self._shell_scripts(runner)
        self.assertTrue(any("docker create" in script and "--name cbok-zsv-worktree" in script for script in shell_scripts))
        self.assertTrue(any("COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 tar $tar_extra_opts -C" in script and "/tmp/cbok-zsv-src/zstack" in script for script in shell_scripts))
        self.assertTrue(any("./runMavenProfile premium" in script for script in shell_scripts))
        self.assertFalse(any("mvn -T 12 -Dmaven.test.skip=true -P premium clean install" in script for script in shell_scripts))
        self.assertTrue(any("cd /work/zstack/testlib" in script for script in shell_scripts))
        self.assertTrue(any("docker cp " in script and ":/tmp/cbok-zsv-cases" in script for script in shell_scripts))
        run_script = (work_root / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("start_mysql", run_script)
        self.assertIn("cd /work/zstack/test", run_script)
        self.assertIn("-Dtest=CoreLibraryTest", run_script)
        self.assertIn("-DsubCaseCollectionStrategy=Designated", run_script)
        self.assertIn("-DcaseFilePath=/tmp/cbok-zsv-cases", run_script)
        self.assertIn("-DskipTests test-compile", run_script)
        self.assertIn("surefire:test", run_script)
        self.assertIn("disable_ukey_util", run_script)
        self.assertIn('rm -f "$util"', run_script)
        self.assertNotIn("patch_ukey_util", run_script)
        self.assertNotIn("ContainerGroovyTest", run_script)
        self.assertNotIn("-pl '!build' install", run_script)
        self.assertNotIn("javaagent:", run_script)
        self.assertIn("-DsurefireArgLine=", run_script)

    def test_remote_docker_daemon_streams_worktrees_without_bind_mounts(self):
        runner = FakeRunner()
        work_root = self.root / "run"

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="org.zstack.test.integration.core.MustPassCase",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(work_root),
            docker_host="http://172.26.50.70:2375",
            runner=runner,
        )

        self.assertEqual(0, rc)
        self.assertFalse(
            any(isinstance(cmd, list) and cmd[:2] == ["docker", "run"] for cmd, _kwargs in runner.commands)
        )
        shell_scripts = self._shell_scripts(runner)
        self.assertTrue(
            any("DOCKER_HOST=tcp://172.26.50.70:2375 docker create" in script for script in shell_scripts)
        )
        self.assertTrue(any("-v zsv-m2-" in script and ":/var/maven/.m2" in script for script in shell_scripts))
        self.assertTrue(
            any("docker exec -i cbok-zsv-worktree" in script and "tar -xzf - -C /tmp/cbok-zsv-src/zstack" in script for script in shell_scripts)
        )
        zstack_archive_scripts = [
            script for script in shell_scripts
            if "tar -xzf - -C /tmp/cbok-zsv-src/zstack" in script
        ]
        self.assertEqual(1, len(zstack_archive_scripts))
        self.assertIn("--exclude target", zstack_archive_scripts[0])
        self.assertIn("--exclude '*/target'", zstack_archive_scripts[0])
        self.assertIn("--exclude premium", zstack_archive_scripts[0])
        self.assertIn("--exclude ./premium", zstack_archive_scripts[0])
        self.assertTrue(any("rsync -a --delete" in script and "/work/zstack/" in script for script in shell_scripts))
        self.assertTrue(any("rsync -a --delete" in script and "/work/zstack/premium/" in script for script in shell_scripts))
        self.assertFalse(any("ln -sfn ../premium /work/zstack/premium" in script for script in shell_scripts))
        self.assertTrue(any("docker cp " in script and ":/tmp/cbok-zsv-groovy-run.sh" in script for script in shell_scripts))

    def test_default_run_root_can_already_exist_for_run_id_reuse(self):
        runner = FakeRunner()
        run_id = f"unit-existing-root-{os.getpid()}"
        default_root = Path("/tmp") / f"cbok-zsv-groovy-test-{run_id}"
        shutil.rmtree(default_root, ignore_errors=True)
        default_root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, default_root, ignore_errors=True)

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="org.zstack.test.integration.core.MustPassCase",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            run_id=run_id,
            runner=runner,
        )

        self.assertEqual(0, rc)
        self.assertTrue((default_root / "zstack").exists())
        self.assertTrue((default_root / "premium").exists())

    def test_existing_worktrees_are_reused_by_default(self):
        runner = FakeRunner()
        work_root = self.root / "run"
        shutil.copytree(self.zstack_repo, work_root / "zstack")
        shutil.copytree(self.premium_repo, work_root / "premium")

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="org.zstack.test.integration.core.MustPassCase",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(work_root),
            runner=runner,
        )

        self.assertEqual(0, rc)
        self.assertFalse(
            any(
                isinstance(cmd, list) and cmd[:5] == ["git", "-C", str(self.zstack_repo), "worktree", "remove"]
                for cmd, _kwargs in runner.commands
            )
        )
        self.assertFalse(
            any(
                isinstance(cmd, list) and cmd[:5] == ["git", "-C", str(self.zstack_repo), "worktree", "add"]
                for cmd, _kwargs in runner.commands
            )
        )

    def test_generated_worktrees_overlay_source_worktree_changes(self):
        runner = FakeRunner()
        work_root = self.root / "run"

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="org.zstack.test.integration.core.MustPassCase",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(work_root),
            runner=runner,
        )

        self.assertEqual(0, rc)
        shell_scripts = self._shell_scripts(runner)
        self.assertTrue(any(
            f"source_repo={shlex.quote(str(self.zstack_repo.resolve()))}" in script
            and f"target_worktree={shlex.quote(str((work_root / 'zstack').resolve()))}" in script
            and "git -C \"$source_repo\" diff --binary HEAD | git -C \"$target_worktree\" apply --binary" in script
            and "git -C \"$source_repo\" ls-files --others --exclude-standard -z" in script
            for script in shell_scripts
        ))
        self.assertTrue(any(
            f"source_repo={shlex.quote(str(self.premium_repo.resolve()))}" in script
            and f"target_worktree={shlex.quote(str((work_root / 'premium').resolve()))}" in script
            for script in shell_scripts
        ))

    def test_reused_worktree_container_incrementally_compiles_changed_modules(self):
        runner = FakeRunner()
        work_root = self.root / "run"
        original_auto_detect = groovy_test.auto_detect_modules
        groovy_test.auto_detect_modules = lambda _zstack, _premium: (["storage"], ["crypto"])
        try:
            rc1 = groovy_test.run_groovy_test_flow(
                zstack_branch="feature-zstack",
                premium_branch="feature-premium",
                test_class="org.zstack.test.integration.core.MustPassCase",
                zstack_repo=str(self.zstack_repo),
                premium_repo=str(self.premium_repo),
                work_root=str(work_root),
                runner=runner,
            )
            rc2 = groovy_test.run_groovy_test_flow(
                zstack_branch="feature-zstack",
                premium_branch="feature-premium",
                test_class="org.zstack.test.integration.core.MustPassCase",
                zstack_repo=str(self.zstack_repo),
                premium_repo=str(self.premium_repo),
                work_root=str(work_root),
                runner=runner,
            )
        finally:
            groovy_test.auto_detect_modules = original_auto_detect

        self.assertEqual(0, rc1)
        self.assertEqual(0, rc2)
        shell_scripts = self._shell_scripts(runner)
        self.assertEqual(1, sum("./runMavenProfile premium" in script for script in shell_scripts))
        self.assertTrue(any(
            "mvn -Ppremium -DskipTests clean install -pl storage,premium/crypto" in script
            for script in shell_scripts
        ))

    def test_different_run_roots_reuse_source_worktree_container(self):
        runner = FakeRunner()
        original_auto_detect = groovy_test.auto_detect_modules
        groovy_test.auto_detect_modules = lambda _zstack, _premium: (["storage"], ["crypto"])
        try:
            rc1 = groovy_test.run_groovy_test_flow(
                zstack_branch="feature-zstack",
                premium_branch="feature-premium",
                test_class="org.zstack.test.integration.core.MustPassCase",
                zstack_repo=str(self.zstack_repo),
                premium_repo=str(self.premium_repo),
                work_root=str(self.root / "run-a"),
                runner=runner,
            )
            rc2 = groovy_test.run_groovy_test_flow(
                zstack_branch="feature-zstack",
                premium_branch="feature-premium",
                test_class="org.zstack.test.integration.core.MustPassCase",
                zstack_repo=str(self.zstack_repo),
                premium_repo=str(self.premium_repo),
                work_root=str(self.root / "run-b"),
                runner=runner,
            )
        finally:
            groovy_test.auto_detect_modules = original_auto_detect

        self.assertEqual(0, rc1)
        self.assertEqual(0, rc2)
        shell_scripts = self._shell_scripts(runner)
        self.assertEqual(1, sum("./runMavenProfile premium" in script for script in shell_scripts))
        self.assertEqual(1, sum("docker create" in script and "--name cbok-zsv-worktree" in script for script in shell_scripts))
        self.assertTrue(any(
            "mvn -Ppremium -DskipTests clean install -pl storage,premium/crypto" in script
            for script in shell_scripts
        ))

    def test_premium_case_runs_requested_class_in_premium_test_module(self):
        runner = FakeRunner()
        work_root = self.root / "run"

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="org.zstack.test.integration.premium.logincontrol.LoginCase",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(work_root),
            runner=runner,
        )

        self.assertEqual(0, rc)
        self.assertFalse(
            (
                work_root
                / "premium/test-premium/src/test/groovy/org/zstack/test/integration/ContainerPremiumGroovyTest.groovy"
            ).exists()
        )
        run_script = (work_root / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("cd /work/zstack/premium/test-premium", run_script)
        self.assertIn("cp /work/zstack/test/target/test-classes/$file /work/zstack/premium/test-premium/target/test-classes/$file", run_script)
        self.assertIn("-Dtest=LoginControlTest", run_script)
        self.assertIn("-DsubCaseCollectionStrategy=Designated", run_script)
        self.assertIn("-DcaseFilePath=/tmp/cbok-zsv-cases", run_script)
        self.assertNotIn("ContainerPremiumGroovyTest", run_script)

    def test_suite_mode_runs_requested_test_class_directly(self):
        runner = FakeRunner()

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="org.zstack.test.integration.core.CoreLibraryTest",
            test_mode="auto",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(0, rc)
        run_script = (self.root / "run" / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("-Dtest=CoreLibraryTest", run_script)
        self.assertNotIn("-DcaseFilePath", run_script)

    def test_default_package_junit_test_runs_directly(self):
        runner = FakeRunner()

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="TestGenerateApiHelper",
            test_mode="auto",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(0, rc)
        run_script = (self.root / "run" / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("cd /work/zstack/test", run_script)
        self.assertIn("-Dtest=TestGenerateApiHelper", run_script)
        self.assertNotIn("-DcaseFilePath", run_script)

    def test_extends_test_without_test_suffix_runs_directly(self):
        runner = FakeRunner()

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="Test3",
            test_mode="auto",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(0, rc)
        run_script = (self.root / "run" / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("-Dtest=Test3", run_script)
        self.assertNotIn("-DcaseFilePath", run_script)

    def test_premium_java_junit_test_runs_directly(self):
        runner = FakeRunner()

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="org.zstack.test.unittest.check.RequestParamCheckCase",
            test_mode="auto",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(0, rc)
        run_script = (self.root / "run" / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("cd /work/zstack/premium/test-premium", run_script)
        self.assertIn("-Dtest=RequestParamCheckCase", run_script)
        self.assertNotIn("-DcaseFilePath", run_script)

    def test_java_doc_class_words_do_not_confuse_source_class_name(self):
        source = self.root / "MetadataImpactCheckerCase.java"
        self._write_file(
            source,
            (
                "package org.zstack.test.unittest.check;\n"
                "/** the class name is documented here */\n"
                "public class MetadataImpactCheckerCase { }\n"
            ),
        )

        self.assertEqual(
            "org.zstack.test.unittest.check.MetadataImpactCheckerCase",
            groovy_test._groovy_fqcn(source),
        )

    def test_case_stub_subclass_runs_via_nearest_suite(self):
        runner = FakeRunner()

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="org.zstack.test.integration.premium.ai.DeployModelCase",
            test_mode="auto",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(0, rc)
        run_script = (self.root / "run" / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("-Dtest=AITest", run_script)
        self.assertIn("-DsubCaseCollectionStrategy=Designated", run_script)
        self.assertIn("-DcaseFilePath=/tmp/cbok-zsv-cases", run_script)

    def test_package_mismatched_premium_case_gets_package_local_harness(self):
        runner = FakeRunner()
        work_root = self.root / "run"

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="org.zstack.test.CheckAPIResponseCase",
            test_mode="auto",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(work_root),
            runner=runner,
        )

        self.assertEqual(0, rc)
        harness = (
            work_root
            / "premium/test-premium/src/test/groovy/org/zstack/test/ContainerPremiumGroovyTest.groovy"
        )
        self.assertTrue(harness.is_file())
        self.assertIn("package org.zstack.test", harness.read_text(encoding="utf-8"))
        run_script = (work_root / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("cd /work/zstack/premium/test-premium", run_script)
        self.assertIn("-Dtest=ContainerPremiumGroovyTest", run_script)
        self.assertIn("-DsubCaseCollectionStrategy=Designated", run_script)
        self.assertEqual(
            "org.zstack.test.CheckAPIResponseCase\n",
            (work_root / "cases.txt").read_text(encoding="utf-8"),
        )

    def test_stability_runner_runs_directly(self):
        runner = FakeRunner()

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="org.zstack.test.integration.stabilisation.StabilityTestCase",
            test_mode="auto",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(0, rc)
        run_script = (self.root / "run" / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("-Dtest=StabilityTestCase", run_script)
        self.assertNotIn("-DcaseFilePath", run_script)

    def test_case_mode_requires_fully_qualified_class_name(self):
        runner = FakeRunner()

        rc = groovy_test.run_groovy_test_flow(
            zstack_branch="feature-zstack",
            premium_branch="feature-premium",
            test_class="MustPassCase",
            test_mode="case",
            zstack_repo=str(self.zstack_repo),
            premium_repo=str(self.premium_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(1, rc)
        self.assertEqual([], runner.commands)


if __name__ == "__main__":
    unittest.main()
