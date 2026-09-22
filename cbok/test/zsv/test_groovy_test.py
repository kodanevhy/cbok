import argparse
import contextlib
import io
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbok.bbx.zsv import compile as compile_module
from cbok.bbx.zsv import groovy_test
from cbok.bbx.zsv import worktree_container


class FakeRunner:
    def __init__(self):
        self.commands = []
        self.containers = set()
        self.remote_run_exit = "0\n"
        self.remote_run_log = "ok\n"

    def run_command(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        if cmd[:6] == ["git", "-C", cmd[2], "worktree", "add", "--detach"]:
            shutil.copytree(Path(cmd[2]), Path(cmd[6]))
        if isinstance(cmd, list) and len(cmd) > 3 and cmd[3] == "rev-parse":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="source-sha\n", stderr="")
        if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]:
            return self._run_shell(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    def _run_shell(self, cmd):
        script = cmd[-1]
        if "df -Pk /" in script:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="%d\n" % (100 * 1024 * 1024), stderr="")
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
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=self.remote_run_exit, stderr="")
        if "tail -n " in script and "/tmp/cbok-zsv-groovy-run.log" in script:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=self.remote_run_log, stderr="")
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
        for name, value in (("check_worktree_clean", True), ("sync_base_ref", True), ("rebase_worktree", True), ("zsv_base_ref", "origin/main")):
            mocked = patch.object(groovy_test, name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_default_state_store = worktree_container.default_state_store
        self._worktree_store = FakeWorktreeContainerStore()
        worktree_container.default_state_store = lambda: self._worktree_store
        self.addCleanup(self._restore_state_store)
        self._orig_remote_docker_compile_from_conf = groovy_test.remote_docker_compile_from_conf
        self.addCleanup(self._restore_compile_conf)
        self._orig_validate_changed_paths_base_ref = groovy_test.validate_changed_paths_base_ref
        self.addCleanup(self._restore_base_ref_validation)
        groovy_test.remote_docker_compile_from_conf = lambda _container_name="": groovy_test.RemoteDockerCompileConfig(
            image="compile-image:unit",
            platform="linux/amd64",
            docker_host="",
            workdir="/work",
            container_name="",
            m2_volume="zsv-m2",
        )
        groovy_test.validate_changed_paths_base_ref = lambda _root: True
        self.root = Path(self.tmp.name)
        self.zsvirt_repo = self.root / "source-zsvirt"
        self.ee_repo = self.root / "source-ee"
        self.zsvirt_repo.mkdir()
        self.ee_repo.mkdir()
        self._write_minimal_repo_sources()

    def _restore_state_store(self):
        worktree_container.default_state_store = self._orig_default_state_store

    def _restore_compile_conf(self):
        groovy_test.remote_docker_compile_from_conf = self._orig_remote_docker_compile_from_conf

    def _restore_base_ref_validation(self):
        groovy_test.validate_changed_paths_base_ref = self._orig_validate_changed_paths_base_ref

    def _write_minimal_repo_sources(self):
        (self.zsvirt_repo / "tests/testlib-simple").mkdir(parents=True)
        (self.zsvirt_repo / "tests/testlib-premium").mkdir(parents=True)
        self._write_module_pom(self.zsvirt_repo / "tests/test-simple/pom.xml")
        self._write_module_pom(self.zsvirt_repo / "tests/test-authentication/pom.xml")
        self._write_file(
            self.zsvirt_repo
            / "tests/test-simple/src/test/groovy/org/zstack/test/integration/core/MustPassCase.groovy",
            "package org.zstack.test.integration.core\nclass MustPassCase {}\n",
        )
        self._write_file(
            self.zsvirt_repo
            / "tests/test-simple/src/test/groovy/org/zstack/test/integration/core/CoreLibraryTest.groovy",
            "package org.zstack.test.integration.core\nclass CoreLibraryTest {}\n",
        )
        self._write_file(
            self.zsvirt_repo / "tests/test-simple/src/test/groovy/TestGenerateApiHelper.groovy",
            "import org.junit.Test\nclass TestGenerateApiHelper { @Test void test() {} }\n",
        )
        self._write_file(
            self.zsvirt_repo / "tests/test-simple/src/test/groovy/Test3.groovy",
            "import org.zstack.testlib.Test\nclass Test3 extends Test {}\n",
        )
        self._write_file(
            self.zsvirt_repo
            / "tests/test-simple/src/test/groovy/org/zstack/test/integration/stabilisation/StabilityTestCase.groovy",
            "package org.zstack.test.integration.stabilisation\nclass StabilityTestCase extends StabilityTest {}\n",
        )
        self._write_file(
            self.zsvirt_repo
            / "tests/test-authentication/src/test/groovy/org/zstack/test/integration/premium/logincontrol/LoginCase.groovy",
            "package org.zstack.test.integration.premium.logincontrol\nclass LoginCase {}\n",
        )
        self._write_file(
            self.zsvirt_repo
            / "tests/test-authentication/src/test/groovy/org/zstack/test/integration/premium/logincontrol/LoginControlTest.groovy",
            "package org.zstack.test.integration.premium.logincontrol\nclass LoginControlTest {}\n",
        )
        self._write_file(
            self.zsvirt_repo / "tests/test-authentication/src/test/groovy/CheckAPIResponseCase.groovy",
            "package org.zstack.test\nclass CheckAPIResponseCase extends SubCase {}\n",
        )
        self._write_file(
            self.zsvirt_repo
            / "tests/test-authentication/src/test/groovy/org/zstack/test/integration/premium/ai/AITest.groovy",
            "package org.zstack.test.integration.premium.ai\nclass AITest extends Test {}\n",
        )
        self._write_file(
            self.zsvirt_repo
            / "tests/test-authentication/src/test/groovy/org/zstack/test/integration/premium/ai/DeployModelCase.groovy",
            "package org.zstack.test.integration.premium.ai\nclass DeployModelCase extends AICaseStub {}\n",
        )
        self._write_file(
            self.zsvirt_repo
            / "tests/test-authentication/src/test/groovy/org/zstack/test/unittest/check/RequestParamCheckCase.java",
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
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="org.zstack.test.integration.core.MustPassCase",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
            work_root=str(work_root),
            runner=runner,
        )

        self.assertEqual(0, rc)
        records = list(self._worktree_store.records.values())
        self.assertEqual((), records[0].pr_refs)
        self.assertEqual("../zsvirt-ee", os.readlink(work_root / "zsvirt" / "zsvirt-ee"))
        self.assertFalse(
            (
                work_root
                / "zsvirt/tests/test-simple/src/test/groovy/org/zstack/test/integration/ContainerGroovyTest.groovy"
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
        self.assertTrue(any("COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 tar $tar_extra_opts -C" in script and "/tmp/cbok-zsv-src/zsvirt" in script and "/tmp/cbok-zsv-src/zsvirt-ee" not in script for script in shell_scripts))
        self.assertTrue(any("./runMavenProfile ee" in script for script in shell_scripts))
        self.assertFalse(any("mvn -T 12 -Dmaven.test.skip=true -P premium clean install" in script for script in shell_scripts))
        self.assertTrue(any("docker cp " in script and ":/tmp/cbok-zsv-cases" in script for script in shell_scripts))
        run_script = (work_root / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("start_mysql", run_script)
        self.assertIn("cd /work/zsvirt/tests/test-simple", run_script)
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
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="org.zstack.test.integration.core.MustPassCase",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
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
            any("docker exec -i cbok-zsv-worktree" in script and "tar -xzf - -C /tmp/cbok-zsv-src/zsvirt" in script for script in shell_scripts)
        )
        zsvirt_archive_scripts = [
            script for script in shell_scripts
            if "tar -xzf - -C /tmp/cbok-zsv-src/zsvirt" in script and "/tmp/cbok-zsv-src/zsvirt-ee" not in script
        ]
        self.assertEqual(1, len(zsvirt_archive_scripts))
        self.assertIn("--exclude target", zsvirt_archive_scripts[0])
        self.assertIn("--exclude '*/target'", zsvirt_archive_scripts[0])
        self.assertIn("--exclude zsvirt-ee", zsvirt_archive_scripts[0])
        self.assertIn("--exclude ./zsvirt-ee", zsvirt_archive_scripts[0])
        self.assertTrue(any("rsync -a --delete" in script and "/work/zsvirt/" in script for script in shell_scripts))
        self.assertTrue(any("rsync -a --delete" in script and "/work/zsvirt/zsvirt-ee/" in script for script in shell_scripts))
        self.assertFalse(any("ln -sfn ../zsvirt-ee /work/zsvirt/premium" in script for script in shell_scripts))
        self.assertTrue(any("docker cp " in script and ":/tmp/cbok-zsv-groovy-run.sh" in script for script in shell_scripts))

    def test_reuses_prepared_deploy_db_when_container_db_is_ready(self):
        runner = FakeRunner()
        work_root = self.root / "run"
        original_db_ready = groovy_test._container_db_is_ready
        groovy_test._container_db_is_ready = lambda _runner, _docker_host, _container_name: True
        try:
            rc = groovy_test.run_groovy_test_flow(
                zsvirt_branch="feature-zsvirt",
                ee_branch="feature-ee",
                test_class="org.zstack.test.integration.core.MustPassCase",
                zsvirt_repo=str(self.zsvirt_repo),
                ee_repo=str(self.ee_repo),
                work_root=str(work_root),
                runner=runner,
            )
        finally:
            groovy_test._container_db_is_ready = original_db_ready

        self.assertEqual(0, rc)
        run_script = (work_root / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("-DcbokReuseDeployDb=true", run_script)
        self.assertIn('if (Boolean.getBoolean("cbokReuseDeployDb"))', run_script)

    def test_refresh_deploy_db_ignores_prepared_deploy_db(self):
        runner = FakeRunner()
        work_root = self.root / "run"
        original_db_ready = groovy_test._container_db_is_ready
        groovy_test._container_db_is_ready = lambda _runner, _docker_host, _container_name: True
        try:
            rc = groovy_test.run_groovy_test_flow(
                zsvirt_branch="feature-zsvirt",
                ee_branch="feature-ee",
                test_class="org.zstack.test.integration.core.MustPassCase",
                zsvirt_repo=str(self.zsvirt_repo),
                ee_repo=str(self.ee_repo),
                work_root=str(work_root),
                refresh_deploy_db=True,
                runner=runner,
            )
        finally:
            groovy_test._container_db_is_ready = original_db_ready

        self.assertEqual(0, rc)
        run_script = (work_root / "remote-run.sh").read_text(encoding="utf-8")
        self.assertNotIn("-DcbokReuseDeployDb=true", run_script)
        self.assertNotIn('if (Boolean.getBoolean("cbokReuseDeployDb"))', run_script)

    def test_reused_prepared_deploy_db_schema_failure_suggests_refresh(self):
        runner = FakeRunner()
        runner.remote_run_exit = "1\n"
        runner.remote_run_log = (
            "org.hibernate.exception.SQLGrammarException: could not execute statement\n"
            "java.sql.SQLSyntaxErrorException: Table 'zstack.ManagementNodeVO' doesn't exist\n"
        )
        work_root = self.root / "run"
        original_db_ready = groovy_test._container_db_is_ready
        groovy_test._container_db_is_ready = lambda _runner, _docker_host, _container_name: True
        try:
            with self.assertLogs(groovy_test.LOG, level="ERROR") as logs:
                rc = groovy_test.run_groovy_test_flow(
                    zsvirt_branch="feature-zsvirt",
                    ee_branch="feature-ee",
                    test_class="org.zstack.test.integration.core.MustPassCase",
                    zsvirt_repo=str(self.zsvirt_repo),
                    ee_repo=str(self.ee_repo),
                    work_root=str(work_root),
                    runner=runner,
                )
        finally:
            groovy_test._container_db_is_ready = original_db_ready

        self.assertEqual(1, rc)
        self.assertIn(
            "Retry with --refresh-deploy-db",
            "\n".join(logs.output),
        )

    def test_default_run_root_can_already_exist_for_run_id_reuse(self):
        runner = FakeRunner()
        run_id = f"unit-existing-root-{os.getpid()}"
        default_root = Path("/tmp") / f"cbok-zsv-groovy-test-{run_id}"
        shutil.rmtree(default_root, ignore_errors=True)
        default_root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, default_root, ignore_errors=True)

        rc = groovy_test.run_groovy_test_flow(
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="org.zstack.test.integration.core.MustPassCase",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
            run_id=run_id,
            runner=runner,
        )

        self.assertEqual(0, rc)
        self.assertTrue((default_root / "zsvirt").exists())
        self.assertTrue((default_root / "zsvirt-ee").exists())

    def test_old_worktrees_without_rebase_metadata_are_recreated(self):
        runner = FakeRunner()
        work_root = self.root / "run"
        shutil.copytree(self.zsvirt_repo, work_root / "zsvirt")
        shutil.copytree(self.ee_repo, work_root / "zsvirt-ee")

        rc = groovy_test.run_groovy_test_flow(
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="org.zstack.test.integration.core.MustPassCase",
            zsvirt_repo=str(self.zsvirt_repo.resolve()),
            ee_repo=str(self.ee_repo),
            work_root=str(work_root),
            runner=runner,
        )

        self.assertEqual(0, rc)
        self.assertTrue(
            any(
                isinstance(cmd, list) and cmd[:5] == ["git", "-C", str(self.zsvirt_repo.resolve()), "worktree", "remove"]
                for cmd, _kwargs in runner.commands
            )
        )
        self.assertTrue(
            any(
                isinstance(cmd, list) and cmd[:5] == ["git", "-C", str(self.zsvirt_repo.resolve()), "worktree", "add"]
                for cmd, _kwargs in runner.commands
            )
        )

    def _run_preparation_flow(self, runner, work_root):
        return groovy_test.run_groovy_test_flow(
            zsvirt_branch="feature-zsvirt", ee_branch="feature-ee",
            test_class="org.zstack.test.integration.core.MustPassCase",
            zsvirt_repo=str(self.zsvirt_repo), ee_repo=str(self.ee_repo),
            work_root=str(work_root), runner=runner,
        )

    def test_clean_checks_and_rebase_precede_reset_and_container(self):
        events = []
        runner = FakeRunner()
        work_root = self.root / "run"
        with patch.object(groovy_test, "check_worktree_clean", side_effect=lambda root: events.append(("check", root)) or True), \
                patch.object(groovy_test, "sync_base_ref", side_effect=lambda root: events.append(("fetch", root)) or True), \
                patch.object(groovy_test, "rebase_worktree", side_effect=lambda root: events.append(("rebase", root)) or True), \
                patch.object(groovy_test, "_reset_test_worktree", side_effect=lambda *args: events.append(("reset", str(args[1]))) or 0), \
                patch.object(groovy_test, "ensure_worktree_container", side_effect=lambda *args, **kwargs: (events.append(("container", "")) or (1, None))):
            self.assertEqual(1, self._run_preparation_flow(runner, work_root))
        self.assertEqual(["check", "check", "fetch", "fetch", "rebase", "rebase", "reset", "reset", "container"], [e[0] for e in events])
        self.assertEqual([str((work_root / "zsvirt").resolve()), str((work_root / "zsvirt-ee").resolve())], [e[1] for e in events if e[0] == "rebase"])

    def test_rebase_failure_halts_before_reset_and_test_resolution(self):
        with patch.object(groovy_test, "rebase_worktree", return_value=False), \
                patch.object(groovy_test, "_reset_test_worktree") as reset, \
                patch.object(groovy_test, "_resolve_test_target") as resolve, \
                patch.object(groovy_test, "ensure_worktree_container", return_value=(1, None)) as container:
            self.assertEqual(1, self._run_preparation_flow(FakeRunner(), self.root / "run"))
        reset.assert_not_called()
        resolve.assert_not_called()
        container.assert_not_called()

    def test_dirty_source_stops_before_fetch_or_worktree_creation(self):
        for clean_results in ([False], [True, False]):
            with self.subTest(clean_results=clean_results):
                runner = FakeRunner()
                with patch.object(groovy_test, "check_worktree_clean", side_effect=clean_results), \
                        patch.object(groovy_test, "sync_base_ref") as fetch, \
                        patch.object(groovy_test, "ensure_worktree_container", return_value=(1, None)) as container:
                    self.assertEqual(1, self._run_preparation_flow(runner, self.root / "run"))
                fetch.assert_not_called()
                container.assert_not_called()
                self.assertEqual([], runner.commands)

    def test_fetch_failure_stops_before_worktree_creation(self):
        runner = FakeRunner()
        with patch.object(groovy_test, "sync_base_ref", side_effect=[True, False]), \
                patch.object(groovy_test, "rebase_worktree") as rebase:
            self.assertEqual(1, self._run_preparation_flow(runner, self.root / "run"))
        self.assertEqual([], runner.commands)
        rebase.assert_not_called()

    def test_missing_base_ref_rejects_even_existing_worktrees(self):
        with patch.object(groovy_test, "zsv_base_ref", return_value=""), \
                patch.object(groovy_test, "sync_base_ref") as fetch:
            self.assertEqual(1, self._run_preparation_flow(FakeRunner(), self.root / "run"))
        fetch.assert_not_called()

    def test_successful_rebased_worktrees_are_reused(self):
        runner = FakeRunner()
        with patch.object(groovy_test, "rebase_worktree", return_value=True) as rebase:
            self.assertEqual(0, self._run_preparation_flow(runner, self.root / "run"))
            self.assertEqual(0, self._run_preparation_flow(runner, self.root / "run"))
        self.assertEqual(2, rebase.call_count)
        self.assertEqual(2, sum(cmd[3:5] == ["worktree", "add"] for cmd, _ in runner.commands))

    def test_local_git_refresh_rebase_reuse_and_upstream_change(self):
        from cbok.bbx.zsv import base_ref

        class LocalGitRunner:
            def __init__(self):
                self.commands = []

            def run_command(self, cmd, **kwargs):
                self.commands.append(cmd)
                return subprocess.run(cmd, capture_output=True, text=True)

        def git(repo, *args):
            return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()

        upstreams = []
        original_heads = []
        for name, repo in (("main", self.zsvirt_repo), ("ee", self.ee_repo)):
            remote = self.root / (name + ".git")
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@example.invalid")
            (repo / "initial.txt").write_text("initial\n")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "initial")
            git(repo, "remote", "add", "origin", str(remote))
            git(repo, "push", "origin", "main")
            git(repo, "checkout", "-b", "feature")
            (repo / "feature.txt").write_text("feature\n")
            git(repo, "add", "feature.txt")
            git(repo, "commit", "-m", "feature")
            original_heads.append(git(repo, "rev-parse", "HEAD"))
            upstream = self.root / (name + "-upstream")
            subprocess.run(["git", "clone", "-b", "main", str(remote), str(upstream)], check=True, capture_output=True)
            git(upstream, "config", "user.name", "Test")
            git(upstream, "config", "user.email", "test@example.invalid")
            (upstream / "upstream.txt").write_text("fresh\n")
            git(upstream, "add", "upstream.txt")
            git(upstream, "commit", "-m", "advance upstream")
            git(upstream, "push", "origin", "main")
            upstreams.append(upstream)
        runner = LocalGitRunner()
        work_root = self.root / "real-run"
        def run():
            return groovy_test.run_groovy_test_flow(
                zsvirt_branch="feature", ee_branch="origin/main",
                test_class="org.zstack.test.integration.core.MustPassCase",
                zsvirt_repo=str(self.zsvirt_repo), ee_repo=str(self.ee_repo),
                work_root=str(work_root), runner=runner,
            )
        with patch.object(base_ref, "zsv_base_ref", return_value="origin/main"), \
                patch.object(groovy_test, "check_worktree_clean", side_effect=base_ref.check_worktree_clean), \
                patch.object(groovy_test, "sync_base_ref", side_effect=base_ref.sync_base_ref) as fetch, \
                patch.object(groovy_test, "rebase_worktree", side_effect=base_ref.rebase_worktree) as rebase, \
                patch.object(groovy_test, "_resolve_test_target", side_effect=ValueError("stop before container")):
            for repo in (self.zsvirt_repo, self.ee_repo):
                for kind in ("unstaged", "staged", "untracked"):
                    with self.subTest(repo=repo.name, kind=kind):
                        changed = repo / ("untracked.txt" if kind == "untracked" else "feature.txt")
                        changed.write_text("uncommitted\n")
                        if kind == "staged":
                            git(repo, "add", "feature.txt")
                        self.assertEqual(1, run())
                        fetch.assert_not_called()
                        rebase.assert_not_called()
                        self.assertFalse(work_root.exists())
                        self.assertEqual("uncommitted\n", changed.read_text())
                        git(repo, "reset", "--hard", "HEAD")
                        if kind == "untracked":
                            changed.unlink()
            (self.zsvirt_repo / "feature.txt").write_text("committed source\n")
            git(self.zsvirt_repo, "commit", "-am", "commit source change")
            original_heads[0] = git(self.zsvirt_repo, "rev-parse", "HEAD")
            self.assertEqual(1, run())
            for work in (work_root / "zsvirt", work_root / "zsvirt-ee"):
                self.assertEqual("fresh\n", (work / "upstream.txt").read_text())
                git(work, "merge-base", "--is-ancestor", "origin/main", "HEAD")
            self.assertEqual("committed source\n", (work_root / "zsvirt/feature.txt").read_text())
            self.assertEqual(original_heads, [git(repo, "rev-parse", "HEAD") for repo in (self.zsvirt_repo, self.ee_repo)])
            (work_root / "zsvirt/generated-harness.groovy").write_text("old harness")
            (work_root / "zsvirt/feature.txt").write_text("generated test change\n")
            self.assertEqual(1, run())
            self.assertEqual(2, rebase.call_count)
            self.assertFalse((work_root / "zsvirt/generated-harness.groovy").exists())
            self.assertEqual("committed source\n", (work_root / "zsvirt/feature.txt").read_text())
            (upstreams[0] / "upstream.txt").write_text("new base\n")
            git(upstreams[0], "commit", "-am", "advance again")
            git(upstreams[0], "push", "origin", "main")
            self.assertEqual(1, run())
            self.assertEqual(4, rebase.call_count)
            self.assertEqual("new base\n", (work_root / "zsvirt/upstream.txt").read_text())
            (self.zsvirt_repo / "feature.txt").write_text("new committed source\n")
            git(self.zsvirt_repo, "commit", "-am", "new source input")
            self.assertEqual(1, run())
            self.assertEqual(6, rebase.call_count)
            self.assertEqual("new committed source\n", (work_root / "zsvirt/feature.txt").read_text())

    def test_reused_worktree_container_incrementally_compiles_changed_modules(self):
        runner = FakeRunner()
        work_root = self.root / "run"
        for module in ("storage", "premium/crypto", "test"):
            self._write_module_pom(self.zsvirt_repo / module / "pom.xml")
        for module in ("zvf", "tests-ee/test-ee"):
            self._write_module_pom(self.ee_repo / module / "pom.xml")

        def changed_paths(repo):
            if Path(repo).name == "zsvirt-ee":
                return ["zvf/src/main/java/Probe.java", "tests-ee/test-ee/src/test/groovy/ProbeCase.groovy"]
            return ["storage/src/main/java/Probe.java", "premium/crypto/src/main/java/Probe.java",
                    "test/src/test/groovy/ProbeCase.groovy", "tests/test-simple/src/test/groovy/ProbeCase.groovy"]

        with patch.object(compile_module, "changed_paths_from_worktree", side_effect=changed_paths), \
                patch.object(compile_module, "changed_paths_from_head_commit", return_value=[]):
            rc1 = groovy_test.run_groovy_test_flow(
                zsvirt_branch="feature-zsvirt",
                ee_branch="feature-ee",
                test_class="org.zstack.test.integration.core.MustPassCase",
                zsvirt_repo=str(self.zsvirt_repo),
                ee_repo=str(self.ee_repo),
                work_root=str(work_root),
                runner=runner,
            )
            rc2 = groovy_test.run_groovy_test_flow(
                zsvirt_branch="feature-zsvirt",
                ee_branch="feature-ee",
                test_class="org.zstack.test.integration.core.MustPassCase",
                zsvirt_repo=str(self.zsvirt_repo),
                ee_repo=str(self.ee_repo),
                work_root=str(work_root),
                runner=runner,
            )
        self.assertEqual(0, rc1)
        self.assertEqual(0, rc2)
        shell_scripts = self._shell_scripts(runner)
        self.assertEqual(1, sum("./runMavenProfile ee" in script for script in shell_scripts))
        self.assertTrue(any(
            "mvn -Pee -DskipTests clean install -pl storage,premium/crypto,zsvirt-ee/zvf\n" in script
            for script in shell_scripts
        ))

    def test_different_run_roots_reuse_source_worktree_container(self):
        runner = FakeRunner()
        original_auto_detect = groovy_test.auto_detect_modules
        groovy_test.auto_detect_modules = lambda _zsvirt, _ee, **_kwargs: (["premium/volumebackup"], ["rewrite-for-ee/core-ee"])
        try:
            rc1 = groovy_test.run_groovy_test_flow(
                zsvirt_branch="feature-zsvirt",
                ee_branch="feature-ee",
                test_class="org.zstack.test.integration.core.MustPassCase",
                zsvirt_repo=str(self.zsvirt_repo),
                ee_repo=str(self.ee_repo),
                work_root=str(self.root / "run-a"),
                runner=runner,
            )
            rc2 = groovy_test.run_groovy_test_flow(
                zsvirt_branch="feature-zsvirt",
                ee_branch="feature-ee",
                test_class="org.zstack.test.integration.core.MustPassCase",
                zsvirt_repo=str(self.zsvirt_repo),
                ee_repo=str(self.ee_repo),
                work_root=str(self.root / "run-b"),
                runner=runner,
            )
        finally:
            groovy_test.auto_detect_modules = original_auto_detect

        self.assertEqual(0, rc1)
        self.assertEqual(0, rc2)
        shell_scripts = self._shell_scripts(runner)
        self.assertEqual(1, sum("./runMavenProfile ee" in script for script in shell_scripts))
        self.assertEqual(1, sum("docker create" in script and "--name cbok-zsv-worktree" in script for script in shell_scripts))
        self.assertTrue(any(
            "mvn -Pee -DskipTests clean install -pl premium/volumebackup,zsvirt-ee/rewrite-for-ee/core-ee\n" in script
            for script in shell_scripts
        ))

    def test_authentication_case_runs_in_main_repository_module(self):
        runner = FakeRunner()
        work_root = self.root / "run"

        rc = groovy_test.run_groovy_test_flow(
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="org.zstack.test.integration.premium.logincontrol.LoginCase",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
            work_root=str(work_root),
            runner=runner,
        )

        self.assertEqual(0, rc)
        self.assertFalse(
            (
                work_root
                / "zsvirt/tests/test-authentication/src/test/groovy/org/zstack/test/integration/ContainerAuthenticationGroovyTest.groovy"
            ).exists()
        )
        run_script = (work_root / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("cd /work/zsvirt/tests/test-authentication", run_script)
        self.assertNotIn("cp /work/zsvirt/tests/test-simple/target/test-classes/", run_script)
        self.assertIn("-Dtest=LoginControlTest", run_script)
        self.assertIn("-DsubCaseCollectionStrategy=Designated", run_script)
        self.assertIn("-DcaseFilePath=/tmp/cbok-zsv-cases", run_script)
        self.assertNotIn("ContainerAuthenticationGroovyTest", run_script)

    def test_suite_mode_runs_requested_test_class_directly(self):
        runner = FakeRunner()

        rc = groovy_test.run_groovy_test_flow(
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="org.zstack.test.integration.core.CoreLibraryTest",
            test_mode="auto",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
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
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="TestGenerateApiHelper",
            test_mode="auto",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(0, rc)
        run_script = (self.root / "run" / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("cd /work/zsvirt/tests/test-simple", run_script)
        self.assertIn("-Dtest=TestGenerateApiHelper", run_script)
        self.assertNotIn("-DcaseFilePath", run_script)

    def test_extends_test_without_test_suffix_runs_directly(self):
        runner = FakeRunner()

        rc = groovy_test.run_groovy_test_flow(
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="Test3",
            test_mode="auto",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(0, rc)
        run_script = (self.root / "run" / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("-Dtest=Test3", run_script)
        self.assertNotIn("-DcaseFilePath", run_script)

    def test_authentication_java_junit_test_runs_directly(self):
        runner = FakeRunner()

        rc = groovy_test.run_groovy_test_flow(
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="org.zstack.test.unittest.check.RequestParamCheckCase",
            test_mode="auto",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(0, rc)
        run_script = (self.root / "run" / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("cd /work/zsvirt/tests/test-authentication", run_script)
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
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="org.zstack.test.integration.premium.ai.DeployModelCase",
            test_mode="auto",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(0, rc)
        run_script = (self.root / "run" / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("-Dtest=AITest", run_script)
        self.assertIn("-DsubCaseCollectionStrategy=Designated", run_script)
        self.assertIn("-DcaseFilePath=/tmp/cbok-zsv-cases", run_script)

    def test_package_mismatched_authentication_case_gets_package_local_harness(self):
        runner = FakeRunner()
        work_root = self.root / "run"

        rc = groovy_test.run_groovy_test_flow(
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="org.zstack.test.CheckAPIResponseCase",
            test_mode="auto",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
            work_root=str(work_root),
            runner=runner,
        )

        self.assertEqual(0, rc)
        harness = (
            work_root
            / "zsvirt/tests/test-authentication/src/test/groovy/org/zstack/test/ContainerAuthenticationGroovyTest.groovy"
        )
        self.assertTrue(harness.is_file())
        self.assertIn("package org.zstack.test", harness.read_text(encoding="utf-8"))
        run_script = (work_root / "remote-run.sh").read_text(encoding="utf-8")
        self.assertIn("cd /work/zsvirt/tests/test-authentication", run_script)
        self.assertIn("-Dtest=ContainerAuthenticationGroovyTest", run_script)
        self.assertIn("-DsubCaseCollectionStrategy=Designated", run_script)
        self.assertEqual(
            "org.zstack.test.CheckAPIResponseCase\n",
            (work_root / "cases.txt").read_text(encoding="utf-8"),
        )

    def test_stability_runner_runs_directly(self):
        runner = FakeRunner()

        rc = groovy_test.run_groovy_test_flow(
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="org.zstack.test.integration.stabilisation.StabilityTestCase",
            test_mode="auto",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
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
            zsvirt_branch="feature-zsvirt",
            ee_branch="feature-ee",
            test_class="MustPassCase",
            test_mode="case",
            zsvirt_repo=str(self.zsvirt_repo),
            ee_repo=str(self.ee_repo),
            work_root=str(self.root / "run"),
            runner=runner,
        )

        self.assertEqual(1, rc)
        self.assertEqual([], runner.commands)

    def test_ee_case_uses_ee_module_and_harness_without_package_heuristics(self):
        source = self.ee_repo / "tests-ee/test-ee/src/test/groovy/org/zstack/test/integration/agents/ProbeCase.groovy"
        self._write_file(source, "package org.zstack.test.integration.agents\nclass ProbeCase extends SubCaseEe {}\n")
        target = groovy_test._resolve_test_target(self.zsvirt_repo, self.ee_repo,
                                                 "org.zstack.test.integration.agents.ProbeCase", "auto")
        self.assertEqual("zsvirt-ee/tests-ee/test-ee", target.module)
        groovy_test._write_harnesses(self.zsvirt_repo, self.ee_repo, target)
        harness = source.parent / "ContainerEeGroovyTest.groovy"
        self.assertIn("extends TestEe", harness.read_text())
        self.assertIn("makeEeSpring()", harness.read_text())
        script = groovy_test.build_container_test_script(target)
        self.assertIn("cd /work/zsvirt/zsvirt-ee/tests-ee/test-ee", script)
        subprocess.run(["bash", "-n"], input=script, text=True, check=True)

    def test_main_premium_package_does_not_select_external_ee(self):
        source = self.zsvirt_repo / "tests/test-simple/src/test/groovy/org/zstack/test/integration/premium/ProbeCase.groovy"
        self._write_file(source, "package org.zstack.test.integration.premium\nclass ProbeCase extends SubCase {}\n")
        target = groovy_test._resolve_test_target(self.zsvirt_repo, self.ee_repo,
                                                 "org.zstack.test.integration.premium.ProbeCase", "auto")
        self.assertEqual("tests/test-simple", target.module)
        self.assertEqual("ContainerGroovyTest", target.surefire_test)

    def test_ee_link_preserves_builtin_premium_and_refuses_real_ee_directory(self):
        marker = self.zsvirt_repo / "premium/mevoco/pom.xml"
        self._write_file(marker, "<project/>")
        groovy_test._create_ee_link(self.zsvirt_repo)
        self.assertEqual("<project/>", marker.read_text())
        link = self.zsvirt_repo / "zsvirt-ee"
        self.assertEqual("../zsvirt-ee", os.readlink(link))
        link.unlink()
        link.mkdir()
        with self.assertRaises(ValueError):
            groovy_test._create_ee_link(self.zsvirt_repo)
        self.assertTrue(link.is_dir())

    def test_duplicate_or_missing_test_module_fails_before_build(self):
        with self.assertRaises(ValueError):
            groovy_test._resolve_test_target(self.zsvirt_repo, self.ee_repo, "MissingTest", "auto")
        self._write_file(self.ee_repo / "tests-ee/test-ee/src/test/groovy/Test3.groovy", "class Test3 extends TestEe {}")
        with self.assertRaises(ValueError):
            groovy_test._resolve_test_target(self.zsvirt_repo, self.ee_repo, "Test3", "auto")

    def test_root_test_module_remains_runnable_in_ee_reactor(self):
        source_root = self.zsvirt_repo / "test/src/test/groovy/org/zstack/test/integration/allocator/domain"
        self._write_module_pom(self.zsvirt_repo / "test/pom.xml")
        self._write_file(source_root / "AllocatorDomainCreateCase.groovy",
                         "package org.zstack.test.integration.allocator.domain\n"
                         "class AllocatorDomainCreateCase extends SubCase {}\n")
        self._write_file(source_root / "AllocatorDomainTest.groovy",
                         "package org.zstack.test.integration.allocator.domain\n"
                         "class AllocatorDomainTest extends Test {}\n")
        target = groovy_test._resolve_test_target(
            self.zsvirt_repo, self.ee_repo,
            "org.zstack.test.integration.allocator.domain.AllocatorDomainCreateCase", "auto")
        self.assertEqual("test", target.module)
        self.assertEqual("AllocatorDomainTest", target.surefire_test)
        self.assertTrue(target.needs_case_file)
        script = groovy_test.build_container_test_script(target)
        self.assertIn("cd /work/zsvirt/test\n", script)
        self.assertIn("/work/zsvirt/test/target/test-classes/zstack.properties", script)
        self.assertIn("/work/zsvirt/test/target/test-classes/tools/zskey-util", script)
        self.assertIn("test", groovy_test.GROOVY_TEST_AUTO_EXCLUDED_MODULES)
        subprocess.run(["bash", "-n"], input=script, text=True, check=True)

    def test_duplicate_suite_fqcn_reports_ambiguous_modules(self):
        test_class = "org.zstack.test.integration.stabilisation.StabilityTestCase"
        modules = ("tests/test-simple", "tests/test-authentication", "zsvirt-ee/tests-ee/test-ee")
        for module in modules:
            module_root = groovy_test._test_module_root(self.zsvirt_repo, self.ee_repo, module)
            self._write_module_pom(module_root / "pom.xml")
            self._write_file(module_root / "src/test/groovy/org/zstack/test/integration/stabilisation/StabilityTestCase.groovy",
                             "package org.zstack.test.integration.stabilisation\n"
                             "class StabilityTestCase extends StabilityTest {}\n")
        with self.assertRaises(ValueError) as raised:
            groovy_test._resolve_test_target(self.zsvirt_repo, self.ee_repo, test_class, "auto")
        for module in modules:
            self.assertIn(module, str(raised.exception))
        self.assertNotIn("--test-module", str(raised.exception))

    def test_cli_resolves_module_from_test_class(self):
        from cbok.cmd import zsv

        parser = argparse.ArgumentParser()
        for options, kwargs in zsv.ZSphereCommands.groovy_test._args:
            parser.add_argument(*options, **kwargs)
        argv = ["--zsvirt-repo", str(self.zsvirt_repo), "--ee-repo", str(self.ee_repo),
                "--zsvirt-branch", "zsv_5.2.0", "--ee-branch", "zsv_5.2.0",
                "--test-class", "org.zstack.test.integration.core.MustPassCase"]
        with patch.object(zsv, "run_groovy_test_flow", return_value=0) as run_flow:
            self.assertEqual(0, zsv.ZSphereCommands().groovy_test(**vars(parser.parse_args(argv))))
        self.assertNotIn("test_module", run_flow.call_args.kwargs)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(argv + ["--test-module", "tests/test-simple"])


if __name__ == "__main__":
    unittest.main()
