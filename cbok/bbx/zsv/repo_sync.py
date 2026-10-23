from __future__ import annotations

from dataclasses import dataclass, replace
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
    head: str | None
    current_branch: str
    current_head: str


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
    return (result.stdout or "").rstrip("\n")


def _validate_name(name: str) -> None:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise RepositorySyncError(f"invalid sync repository name: {name}")


def _parse_targets(workspace_root: Path, entries: tuple[str, ...]) -> list[tuple[str, str]]:
    if not entries:
        raise RepositorySyncError("[zsv] sync_repos is empty")

    targets = []
    names = set()
    for entry in entries:
        name, separator, branch = entry.partition(":")
        name, branch = name.strip(), branch.strip()
        if not separator or not name or not branch:
            raise RepositorySyncError(f"invalid sync repository entry: {entry}; expected project:branch")
        _validate_name(name)
        if name in names:
            raise RepositorySyncError("[zsv] sync_repos contains duplicate repositories")
        result = _git(workspace_root, "check-ref-format", "--branch", branch)
        if result.returncode != 0 or result.stdout.strip() != branch:
            raise RepositorySyncError(f"{name}: invalid sync branch: {branch}")
        names.add(name)
        targets.append((name, branch))
    return targets


def _only_expected_submodule_changes(name: str, root: Path, status: str, before_head: str) -> bool:
    for entry in filter(None, status.split("\0")):
        fields = entry.split(" ", 8)
        if len(fields) != 9 or fields[:3] != ["1", ".M", "SC.."]:
            return False
        path = fields[8]
        previous = _run(name, root, "--literal-pathspecs", "ls-tree", "-z", before_head, "--", path)
        metadata = previous.partition("\t")[0].split()
        if len(metadata) != 3 or metadata[:2] != ["160000", "commit"]:
            return False
        if _run(name, root / path, "rev-parse", "HEAD") != metadata[2]:
            return False
    return True


def _inspect_repository(
    workspace_root: Path, name: str, branch: str, submodule_base: str | None = None,
) -> _Repository:
    root = workspace_root / name
    if not root.is_dir():
        raise RepositorySyncError(f"{name}: repository directory does not exist: {root}")

    git_root = _run(name, root, "rev-parse", "--show-toplevel")
    if os.path.realpath(git_root) != os.path.realpath(root):
        raise RepositorySyncError(f"{name}: path is not an independent Git repository: {root}")

    for operation in ("rebase-merge", "rebase-apply", "sequencer", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        git_path = _run(name, root, "rev-parse", "--git-path", operation)
        if (root / git_path).exists():
            raise RepositorySyncError(f"{name}: unfinished Git operation; finish or abort it before syncing")

    status = _run(name, root, "status", "--porcelain=v2", "-z", "--untracked-files=all", "--ignore-submodules=none")
    if status and not (
        submodule_base and _only_expected_submodule_changes(name, root, status, submodule_base)
    ):
        raise RepositorySyncError(f"{name}: repository has uncommitted changes")

    current_branch = _run(name, root, "symbolic-ref", "--quiet", "HEAD")
    current_head = _run(name, root, "rev-parse", "HEAD")
    target_ref = f"refs/heads/{branch}"
    result = _git(root, "rev-parse", "--verify", "--quiet", target_ref)
    if result.returncode not in (0, 1):
        raise RepositorySyncError(f"{name}: failed to inspect local branch {branch}: {_output(result)}")
    head = result.stdout.strip() if result.returncode == 0 else None
    worktree = _run(name, root, "for-each-ref", "--format=%(worktreepath)", target_ref)
    if worktree and os.path.realpath(worktree) != os.path.realpath(root):
        raise RepositorySyncError(f"{name}: configured branch {branch} is checked out in another worktree")
    _run(name, root, "remote", "get-url", "upstream")
    return _Repository(name, root, branch, head, current_branch, current_head)


def _build_plan(repository: _Repository) -> _SyncPlan:
    remote_ref = f"refs/remotes/upstream/{repository.branch}"
    _run(
        repository.name,
        repository.root,
        "fetch",
        "--no-recurse-submodules",
        "--prune",
        "upstream",
        "+refs/heads/*:refs/remotes/upstream/*",
    )
    target = _run(repository.name, repository.root, "rev-parse", "--verify", remote_ref)
    if repository.head is not None:
        ancestor = _git(repository.root, "merge-base", "--is-ancestor", repository.head, target)
        if ancestor.returncode != 0:
            raise RepositorySyncError(
                f"{repository.name}: configured branch {repository.branch} has local commits or diverged from "
                f"upstream/{repository.branch}"
            )
    return _SyncPlan(repository, target)


def _validate_plan(plan: _SyncPlan, submodule_base: str | None = None) -> None:
    repository = plan.repository
    if _inspect_repository(
        repository.root.parent, repository.name, repository.branch, submodule_base,
    ) != repository:
        raise RepositorySyncError(f"{repository.name}: branch or HEAD changed while preparing synchronization")

    ignored_paths = _run(
        repository.name, repository.root,
        "ls-files", "--others", "--ignored", "--exclude-standard", "-z",
    ).split("\0")
    for target in (repository.head, plan.target):
        if target is None or target == repository.current_head:
            continue
        changed_paths = _run(
            repository.name, repository.root,
            "diff", "--name-only", "--no-renames", "--diff-filter=ACMRT", "-z",
            repository.current_head, target, "--",
        ).split("\0")
        for ignored in filter(None, ignored_paths):
            for changed in filter(None, changed_paths):
                if ignored == changed or ignored.startswith(changed + "/") or changed.startswith(ignored + "/"):
                    raise RepositorySyncError(
                        f"{repository.name}: ignored local file would be overwritten: {ignored}"
                    )


def sync_repositories(
    zstack_workspace_root: str | Path,
    repository_entries: tuple[str, ...],
) -> list[tuple[str, str, str]]:
    workspace_root = Path(zstack_workspace_root).resolve()
    targets = _parse_targets(workspace_root, repository_entries)
    repositories = [
        _inspect_repository(workspace_root, name, branch)
        for name, branch in targets
    ]
    plans = [_build_plan(repository) for repository in repositories]
    for plan in plans:
        _validate_plan(plan)

    results = []
    for plan in plans:
        repository = plan.repository
        _validate_plan(plan)
        branch_ref = f"refs/heads/{repository.branch}"
        if repository.current_branch != branch_ref:
            checkout_args = (
                (repository.branch,) if repository.head is not None
                else ("--no-track", "-b", repository.branch, plan.target)
            )
            _run(
                repository.name, repository.root,
                "checkout", "--no-guess", "--no-recurse-submodules", "--no-overwrite-ignore",
                *checkout_args,
            )
            checked_out = replace(
                repository,
                head=repository.head or plan.target,
                current_branch=branch_ref,
                current_head=repository.head or plan.target,
            )
            _validate_plan(_SyncPlan(checked_out, plan.target), submodule_base=repository.current_head)
        _run(
            repository.name, repository.root, "-c", "submodule.recurse=false",
            "merge", "--ff-only", "--no-overwrite-ignore", plan.target,
        )
        head = _run(repository.name, repository.root, "rev-parse", "HEAD")
        branch = _run(repository.name, repository.root, "symbolic-ref", "--quiet", "HEAD")
        if head != plan.target or branch != branch_ref:
            raise RepositorySyncError(
                f"{repository.name}: HEAD does not match upstream/{repository.branch}"
            )
        results.append((repository.name, repository.branch, plan.target))
    return results
