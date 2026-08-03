import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from dataclasses import dataclass

from cbok.bbx.zsv import worktree_prune


@dataclass
class FakePrRef:
    repo: str
    pr_url: str


@dataclass
class FakeRecord:
    worktree_key: str
    zstack_root: str
    premium_root: str
    docker_host: str
    container_name: str
    m2_volume: str
    pr_refs: tuple[FakePrRef, ...] = ()


class FakeRunner:
    def __init__(self):
        self.commands = []

    def run_command(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


class MissingVolumeRunner(FakeRunner):
    def run_command(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        if "docker volume rm zsv-m2-1234" in cmd[-1]:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout="",
                stderr="Error response from daemon: get zsv-m2-1234: no such volume",
            )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


class FakeContainerStore:
    def __init__(self, records):
        self.records = records
        self.deleted = []

    def list_records(self):
        return list(self.records)

    def delete_records(self, record, delete_compile_state=False):
        self.deleted.append((record.worktree_key, delete_compile_state))


class WorktreePruneTest(unittest.TestCase):
    def _record(
            self,
            zstack_root="/worktrees/fix-a/zstack",
            premium_root="/worktrees/fix-a/premium",
            pr_refs=(),
    ):
        return FakeRecord(
            worktree_key="key-1",
            zstack_root=zstack_root,
            premium_root=premium_root,
            docker_host="tcp://172.26.50.70:2375",
            container_name="cbok-zsv-worktree-fix-a-1234",
            m2_volume="zsv-m2-1234",
            pr_refs=tuple(pr_refs),
        )

    def _record_with_existing_roots(self, work_root):
        zstack_root = os.path.join(work_root, "zstack")
        premium_root = os.path.join(work_root, "premium")
        os.makedirs(zstack_root)
        os.makedirs(premium_root)
        return self._record(zstack_root, premium_root)

    def _capture(self, func, *args, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = func(*args, **kwargs)
        return rc, output.getvalue()

    def test_list_worktree_container_prs_prints_container_metadata(self):
        with tempfile.TemporaryDirectory() as work_root:
            record = self._record_with_existing_roots(work_root)
            record.pr_refs = (
                FakePrRef("zstack", "https://github.com/kodanevhy/cbok/pull/1"),
                FakePrRef("premium", "https://dev.zstack.io/zstackio/premium/-/merge_requests/2"),
            )
            container_store = FakeContainerStore([record])

            rc, output = self._capture(
                worktree_prune.list_worktree_container_prs,
                container_store=container_store,
            )

            self.assertEqual(0, rc)
            self.assertIn("CONTAINER cbok-zsv-worktree-fix-a-1234", output)
            self.assertIn(f"zstack: {record.zstack_root}", output)
            self.assertIn(f"premium: {record.premium_root}", output)
            self.assertIn("m2 volume: zsv-m2-1234", output)
            self.assertIn("zstack PR/MR: https://github.com/kodanevhy/cbok/pull/1", output)
            self.assertIn("premium PR/MR: https://dev.zstack.io/zstackio/premium/-/merge_requests/2", output)

    def test_list_worktree_container_prs_prints_missing_worktree_branches(self):
        record = self._record()
        container_store = FakeContainerStore([record])

        rc, output = self._capture(
            worktree_prune.list_worktree_container_prs,
            container_store=container_store,
        )

        self.assertEqual(0, rc)
        self.assertIn("zstack branch: -", output)
        self.assertIn("premium branch: -", output)
        self.assertIn("PR/MR: -", output)

    def test_prune_requires_container_names(self):
        rc, _output = self._capture(
            worktree_prune.prune_worktree_containers,
            FakeRunner(),
            container_names=[],
            container_store=FakeContainerStore([]),
        )

        self.assertEqual(1, rc)

    def test_prune_dry_run_does_not_delete_selected_container(self):
        record = self._record()
        runner = FakeRunner()
        container_store = FakeContainerStore([record])

        rc, output = self._capture(
            worktree_prune.prune_worktree_containers,
            runner,
            container_names=[record.container_name],
            dry_run=True,
            container_store=container_store,
        )

        self.assertEqual(0, rc)
        self.assertIn("DELETE cbok-zsv-worktree-fix-a-1234", output)
        self.assertEqual([], runner.commands)
        self.assertEqual([], container_store.deleted)

    def test_prune_execute_removes_container_volume_and_db(self):
        record = self._record()
        runner = FakeRunner()
        container_store = FakeContainerStore([record])

        rc, _output = self._capture(
            worktree_prune.prune_worktree_containers,
            runner,
            container_names=[record.container_name],
            dry_run=False,
            container_store=container_store,
        )

        self.assertEqual(0, rc)
        shell_scripts = [cmd[-1] for cmd, _kwargs in runner.commands]
        self.assertTrue(any("docker rm -f cbok-zsv-worktree-fix-a-1234" in script for script in shell_scripts))
        self.assertTrue(any("docker volume rm zsv-m2-1234" in script for script in shell_scripts))
        self.assertEqual([("key-1", True)], container_store.deleted)

    def test_prune_execute_treats_missing_volume_as_deleted(self):
        record = self._record()
        runner = MissingVolumeRunner()
        container_store = FakeContainerStore([record])

        rc, _output = self._capture(
            worktree_prune.prune_worktree_containers,
            runner,
            container_names=[record.container_name],
            dry_run=False,
            container_store=container_store,
        )

        self.assertEqual(0, rc)
        self.assertEqual([("key-1", True)], container_store.deleted)

    def test_prune_execute_rejects_unknown_container(self):
        runner = FakeRunner()
        container_store = FakeContainerStore([self._record()])

        rc, _output = self._capture(
            worktree_prune.prune_worktree_containers,
            runner,
            container_names=["cbok-zsv-worktree-missing"],
            dry_run=False,
            container_store=container_store,
        )

        self.assertEqual(1, rc)
        self.assertEqual([], runner.commands)
        self.assertEqual([], container_store.deleted)

    def test_prune_filters_configured_docker_host(self):
        record = self._record()
        runner = FakeRunner()
        container_store = FakeContainerStore([record])

        rc, _output = self._capture(
            worktree_prune.prune_worktree_containers,
            runner,
            container_names=[record.container_name],
            dry_run=False,
            docker_host="tcp://172.26.50.71:2375",
            container_store=container_store,
        )

        self.assertEqual(1, rc)
        self.assertEqual([], runner.commands)
        self.assertEqual([], container_store.deleted)

if __name__ == "__main__":
    unittest.main()
