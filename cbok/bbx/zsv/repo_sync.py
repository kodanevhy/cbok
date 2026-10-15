from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess


class RepositorySyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Repository:
    name: str
    root: Path
    branch: str


@dataclass(frozen=True)
class _SyncPlan:
    repository: _Repository
    target: str


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
    )


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


def _run(repository: str, root: Path, *args: str) -> str:
    result = _git(root, *args)
    if result.returncode != 0:
        detail = _output(result)
        suffix = f": {detail}" if detail else ""
        raise RepositorySyncError(f"{repository}: git {' '.join(args)} failed{suffix}")
    return (result.stdout or "").strip()


def _validate_name(name: str) -> None:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise RepositorySyncError(f"invalid sync repository name: {name}")


def _inspect_repository(workspace_root: Path, name: str) -> _Repository:
    _validate_name(name)
    root = workspace_root / name
    if not root.is_dir():
        raise RepositorySyncError(f"{name}: repository directory does not exist: {root}")

    git_root = _run(name, root, "rev-parse", "--show-toplevel")
    if os.path.realpath(git_root) != os.path.realpath(root):
        raise RepositorySyncError(f"{name}: path is not an independent Git repository: {root}")

    for operation in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        git_path = _run(name, root, "rev-parse", "--git-path", operation)
        if (root / git_path).exists():
            raise RepositorySyncError(f"{name}: unfinished Git operation; finish or abort it before syncing")

    status = _run(name, root, "status", "--porcelain")
    if status:
        raise RepositorySyncError(f"{name}: repository has uncommitted changes")

    branch = _run(name, root, "symbolic-ref", "--quiet", "--short", "HEAD")
    _run(name, root, "remote", "get-url", "upstream")
    return _Repository(name, root, branch)


def _build_plan(repository: _Repository) -> _SyncPlan:
    remote_ref = f"refs/remotes/upstream/{repository.branch}"
    _run(
        repository.name,
        repository.root,
        "fetch",
        "upstream",
        f"+refs/heads/{repository.branch}:{remote_ref}",
    )
    target = _run(repository.name, repository.root, "rev-parse", remote_ref)
    ancestor = _git(repository.root, "merge-base", "--is-ancestor", "HEAD", target)
    if ancestor.returncode != 0:
        raise RepositorySyncError(
            f"{repository.name}: current branch has local commits or diverged from "
            f"upstream/{repository.branch}"
        )
    return _SyncPlan(repository, target)


def sync_repositories(
    zstack_workspace_root: str | Path,
    repository_names: tuple[str, ...],
) -> list[tuple[str, str]]:
    if not repository_names:
        raise RepositorySyncError("[zsv] sync_repos is empty")
    if len(set(repository_names)) != len(repository_names):
        raise RepositorySyncError("[zsv] sync_repos contains duplicate repositories")

    workspace_root = Path(zstack_workspace_root).resolve()
    repositories = [
        _inspect_repository(workspace_root, name)
        for name in repository_names
    ]
    plans = [_build_plan(repository) for repository in repositories]

    results = []
    for plan in plans:
        repository = plan.repository
        _run(repository.name, repository.root, "merge", "--ff-only", plan.target)
        head = _run(repository.name, repository.root, "rev-parse", "HEAD")
        if head != plan.target:
            raise RepositorySyncError(
                f"{repository.name}: HEAD does not match upstream/{repository.branch}"
            )
        results.append((repository.name, plan.target))
    return results
