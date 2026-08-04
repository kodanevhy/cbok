from __future__ import annotations

import logging
import os
import subprocess

from cbok.bbx.models import ZsvCompileState
from cbok.bbx.models import ZsvWorktreeContainerPullRequest
from cbok.bbx.models import ZsvWorktreeContainerState
from cbok.bbx.zsv.worktree_container import docker_shell_capture
from cbok.bbx.zsv.worktree_container import normalize_docker_host
from cbok.bbx.zsv.worktree_container import PR_REPOS


LOG = logging.getLogger(__name__)


def _dedupe(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        item = (item or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _git(repo_root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo_root, *args],
        capture_output=True,
        text=True,
    )


def _current_branch(repo_root: str) -> str:
    result = _git(repo_root, "branch", "--show-current")
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


class DjangoPruneContainerStore:
    def list_records(self):
        records = list(ZsvWorktreeContainerState.objects.all().order_by("container_name"))
        keys = [record.worktree_key for record in records]
        refs_by_key = {key: [] for key in keys}
        for ref in ZsvWorktreeContainerPullRequest.objects.filter(
                worktree_key__in=keys,
        ).order_by("repo", "pr_url"):
            refs_by_key.setdefault(ref.worktree_key, []).append(ref)
        for record in records:
            record.pr_refs = refs_by_key.get(record.worktree_key, [])
        return records

    def delete_records(self, record, delete_compile_state: bool = False) -> None:
        ZsvWorktreeContainerPullRequest.objects.filter(worktree_key=record.worktree_key).delete()
        ZsvWorktreeContainerState.objects.filter(worktree_key=record.worktree_key).delete()
        if delete_compile_state:
            ZsvCompileState.objects.filter(
                zstack_root=record.zstack_root,
                premium_root=record.premium_root or "",
            ).delete()


def _records_for_docker_host(records, docker_host: str):
    expected_host = normalize_docker_host(docker_host)
    for record in records:
        record_host = normalize_docker_host(record.docker_host)
        if expected_host and record_host != expected_host:
            continue
        yield record


def _print_container_record(record) -> None:
    print(f"CONTAINER {record.container_name}")
    print(f"  zstack: {record.zstack_root}")
    print(f"  zstack branch: {_branch_label(record.zstack_root)}")
    print(f"  premium: {record.premium_root or '-'}")
    print(f"  premium branch: {_branch_label(record.premium_root)}")
    print(f"  docker: {normalize_docker_host(record.docker_host) or 'local'}")
    print(f"  m2 volume: {record.m2_volume or '-'}")
    pr_refs = getattr(record, "pr_refs", []) or []
    urls_by_repo = {repo: [] for repo in PR_REPOS}
    for ref in pr_refs:
        repo = (getattr(ref, "repo", "") or "").strip()
        url = (getattr(ref, "pr_url", "") or "").strip()
        if repo and url:
            urls_by_repo.setdefault(repo, []).append(url)
    lines = [
        f"{repo} {url}"
        for repo, urls in urls_by_repo.items()
        for url in _dedupe(urls)
    ]
    if lines:
        for line in lines:
            repo, url = line.split(" ", 1)
            print(f"  {repo} PR/MR: {url}")
    else:
        print("  PR/MR: -")


def _branch_label(root: str) -> str:
    if not root or not os.path.isdir(root):
        return "-"
    return _current_branch(root) or "-"


def list_worktree_container_prs(
        *,
        docker_host: str = "",
        container_store=None,
) -> int:
    container_store = container_store or DjangoPruneContainerStore()
    records = list(_records_for_docker_host(container_store.list_records(), docker_host))
    if not records:
        print("No worktree containers found.")
        return 0

    for record in records:
        _print_container_record(record)
    return 0


def _returncode(result) -> int:
    return getattr(result, "returncode", 1) or 0


def _output(result) -> str:
    return ((getattr(result, "stdout", "") or "") + (getattr(result, "stderr", "") or "")).strip()


def _docker_remove_container(runner, docker_host: str, container_name: str) -> int:
    result = docker_shell_capture(runner, docker_host, ["rm", "-f", container_name])
    if _returncode(result) == 0:
        return 0
    text = _output(result)
    if "no such container" in text.lower():
        return 0
    LOG.error("Failed to remove Docker container %s: %s", container_name, text)
    return _returncode(result)


def _docker_remove_volume(runner, docker_host: str, volume: str) -> int:
    if not volume:
        return 0
    result = docker_shell_capture(runner, docker_host, ["volume", "rm", volume])
    if _returncode(result) == 0:
        return 0
    text = _output(result)
    if "no such volume" in text.lower():
        return 0
    LOG.error("Failed to remove Docker volume %s: %s", volume, text)
    return _returncode(result)


def _print_delete_target(record) -> None:
    print(f"DELETE {record.container_name}")
    print(f"  zstack: {record.zstack_root}")
    print(f"  premium: {record.premium_root or '-'}")
    print(f"  docker: {normalize_docker_host(record.docker_host) or 'local'}")
    print(f"  m2 volume: {record.m2_volume or '-'}")


def prune_worktree_containers(
        runner,
        *,
        container_names: list[str],
        dry_run: bool = True,
        docker_host: str = "",
        container_store=None,
) -> int:
    names = _dedupe(container_names or [])
    if not names:
        LOG.error("At least one --container-name is required.")
        return 1

    container_store = container_store or DjangoPruneContainerStore()
    records = list(_records_for_docker_host(container_store.list_records(), docker_host))
    by_name = {record.container_name: record for record in records}
    missing = [name for name in names if name not in by_name]
    if missing:
        LOG.error("No worktree container record found for: %s", ", ".join(missing))
        return 1

    selected = [by_name[name] for name in names]
    for record in selected:
        _print_delete_target(record)

    if dry_run:
        print("\n(dry-run) skipping Docker and database deletion.")
        return 0

    for record in selected:
        rc = _docker_remove_container(runner, record.docker_host, record.container_name)
        if rc != 0:
            return rc
        rc = _docker_remove_volume(runner, record.docker_host, record.m2_volume)
        if rc != 0:
            return rc
        container_store.delete_records(record, delete_compile_state=True)
    return 0
