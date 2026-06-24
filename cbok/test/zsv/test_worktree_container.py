import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbok.bbx.zsv import worktree_container


class FakeRunner:
    def __init__(self):
        self.commands = []
        self.containers = set()

    def run_command(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]:
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


class WorktreeContainerTest(unittest.TestCase):
    def _write_repo(self, root: Path):
        (root / "testlib").mkdir(parents=True)
        (root / "plugin/foo").mkdir(parents=True)
        (root / "pom.xml").write_text("<project/>", encoding="utf-8")

    def _write_premium(self, root: Path):
        (root / "testlib-premium").mkdir(parents=True)
        (root / "test-premium").mkdir(parents=True)

    def _shell_scripts(self, runner):
        return [
            cmd[-1] for cmd, _kwargs in runner.commands
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]

    def test_full_compile_runs_once_per_worktree_state(self):
        with tempfile.TemporaryDirectory() as td:
            zstack = Path(td) / "zstack"
            premium = Path(td) / "premium"
            self._write_repo(zstack)
            self._write_premium(premium)
            runner = FakeRunner()
            store = worktree_container.InMemoryWorktreeContainerStore()
            spec = worktree_container.WorktreeContainerSpec(
                zstack_root=str(zstack),
                premium_root=str(premium),
                docker_host="http://172.26.50.70:2375",
                image="compile-image:unit",
                platform="linux/amd64",
                workdir="/work",
                container_name="auto",
                m2_volume="zsv-m2",
            )

            rc, first = worktree_container.ensure_worktree_container(
                runner,
                spec,
                state_store=store,
            )
            rc2, second = worktree_container.ensure_worktree_container(
                runner,
                spec,
                state_store=store,
            )

        self.assertEqual(0, rc)
        self.assertEqual(0, rc2)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertTrue(first.full_compile_ran)
        self.assertFalse(second.full_compile_ran)
        self.assertEqual(first.container_name, second.container_name)
        shell_scripts = self._shell_scripts(runner)
        self.assertEqual(1, sum("./runMavenProfile premium" in script for script in shell_scripts))
        self.assertEqual(1, sum("mvn -T 12 -Dmaven.test.skip=true -P premium clean install" in script for script in shell_scripts))
        self.assertTrue(any("DOCKER_HOST=tcp://172.26.50.70:2375 docker create" in script for script in shell_scripts))
        self.assertTrue(any("-v zsv-m2:/var/maven/.m2" in script for script in shell_scripts))

    def test_full_compile_reruns_when_worktree_head_changes(self):
        with tempfile.TemporaryDirectory() as td:
            zstack = Path(td) / "zstack"
            premium = Path(td) / "premium"
            self._write_repo(zstack)
            self._write_premium(premium)
            runner = FakeRunner()
            store = worktree_container.InMemoryWorktreeContainerStore()
            spec = worktree_container.WorktreeContainerSpec(
                zstack_root=str(zstack),
                premium_root=str(premium),
                docker_host="",
                image="compile-image:unit",
            )
            heads = {
                str(zstack.resolve()): "zstack-old",
                str(premium.resolve()): "premium-old",
            }

            def fake_git_head(root):
                return heads[str(Path(root).resolve())]

            with patch.object(worktree_container, "_git_head", side_effect=fake_git_head):
                rc, first = worktree_container.ensure_worktree_container(
                    runner,
                    spec,
                    state_store=store,
                )
                heads[str(premium.resolve())] = "premium-new"
                rc2, second = worktree_container.ensure_worktree_container(
                    runner,
                    spec,
                    state_store=store,
                )

        self.assertEqual(0, rc)
        self.assertEqual(0, rc2)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertTrue(first.full_compile_ran)
        self.assertTrue(second.full_compile_ran)
        self.assertEqual(first.container_name, second.container_name)
        shell_scripts = self._shell_scripts(runner)
        self.assertEqual(2, sum("./runMavenProfile premium" in script for script in shell_scripts))

    def test_full_compile_patches_run_maven_profile_and_still_uses_it_as_entrypoint(self):
        with tempfile.TemporaryDirectory() as td:
            zstack = Path(td) / "zstack"
            premium = Path(td) / "premium"
            self._write_repo(zstack)
            self._write_premium(premium)
            runner = FakeRunner()
            store = worktree_container.InMemoryWorktreeContainerStore()
            spec = worktree_container.WorktreeContainerSpec(
                zstack_root=str(zstack),
                premium_root=str(premium),
                docker_host="",
                image="compile-image:unit",
            )

            rc, handle = worktree_container.ensure_worktree_container(
                runner,
                spec,
                state_store=store,
            )

        self.assertEqual(0, rc)
        self.assertTrue(handle.full_compile_ran)
        shell_scripts = self._shell_scripts(runner)
        full_compile_scripts = [
            script for script in shell_scripts
            if "testlib" in script and "./runMavenProfile premium" in script
        ]
        self.assertEqual(1, len(full_compile_scripts))
        self.assertIn("sed -i -E", full_compile_scripts[0])
        self.assertIn("mvn -T 12 -Dmaven.test.skip=true -P premium clean install", full_compile_scripts[0])
        self.assertIn("./runMavenProfile premium", full_compile_scripts[0])

    def test_source_sync_deletes_stale_sources_but_preserves_targets(self):
        with tempfile.TemporaryDirectory() as td:
            zstack = Path(td) / "zstack"
            premium = Path(td) / "premium"
            self._write_repo(zstack)
            self._write_premium(premium)
            runner = FakeRunner()
            store = worktree_container.InMemoryWorktreeContainerStore()
            spec = worktree_container.WorktreeContainerSpec(
                zstack_root=str(zstack),
                premium_root=str(premium),
                docker_host="",
                image="compile-image:unit",
            )

            rc, _handle = worktree_container.ensure_worktree_container(
                runner,
                spec,
                state_store=store,
            )

        self.assertEqual(0, rc)
        shell_scripts = self._shell_scripts(runner)
        zstack_archive = [
            script for script in shell_scripts
            if "tar -xzf - -C /tmp/cbok-zsv-src/zstack" in script
        ][0]
        self.assertIn("--exclude target", zstack_archive)
        self.assertIn("*/target", zstack_archive)
        self.assertIn("--exclude premium", zstack_archive)
        sync_script = [
            script for script in shell_scripts
            if "rsync -a --delete" in script and "/work/zstack/" in script
        ][0]
        self.assertIn("--exclude target", sync_script)
        self.assertIn("*/target", sync_script)
        self.assertIn("--exclude premium", sync_script)
        self.assertIn("rsync -a --delete", sync_script)
        self.assertIn("/work/zstack/premium/", sync_script)
        self.assertNotIn("ln -sfn ../premium", sync_script)

    def test_rejects_reusing_container_name_for_different_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            zstack_a = Path(td) / "task-a" / "zstack"
            premium_a = Path(td) / "task-a" / "premium"
            zstack_b = Path(td) / "task-b" / "zstack"
            premium_b = Path(td) / "task-b" / "premium"
            self._write_repo(zstack_a)
            self._write_premium(premium_a)
            self._write_repo(zstack_b)
            self._write_premium(premium_b)
            runner = FakeRunner()
            store = worktree_container.InMemoryWorktreeContainerStore()
            spec_a = worktree_container.WorktreeContainerSpec(
                zstack_root=str(zstack_a),
                premium_root=str(premium_a),
                docker_host="",
                image="compile-image:unit",
                container_name="shared-container",
            )
            spec_b = worktree_container.WorktreeContainerSpec(
                zstack_root=str(zstack_b),
                premium_root=str(premium_b),
                docker_host="",
                image="compile-image:unit",
                container_name="shared-container",
            )

            rc, handle = worktree_container.ensure_worktree_container(
                runner,
                spec_a,
                state_store=store,
            )
            commands_after_first = len(runner.commands)
            with self.assertLogs(worktree_container.LOG.name, level="ERROR") as logs:
                rc2, handle2 = worktree_container.ensure_worktree_container(
                    runner,
                    spec_b,
                    state_store=store,
                )

        self.assertEqual(0, rc)
        self.assertIsNotNone(handle)
        self.assertEqual(1, rc2)
        self.assertIsNone(handle2)
        self.assertEqual(commands_after_first, len(runner.commands))
        self.assertIn("already bound to another worktree", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
