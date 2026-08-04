from __future__ import annotations

import logging
import subprocess

from cbok.bbx.zsv.config import zsv_base_ref


LOG = logging.getLogger(__name__)


def _git(root: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", root, *args],
        capture_output=True,
        text=True,
    )


def remote_base_ref_fetch_spec(
    repo_root: str,
    base_ref: str,
    git_runner=_git,
) -> tuple[str, str, str] | None:
    if "/" not in base_ref:
        return None

    remote, branch = base_ref.split("/", 1)
    if not remote or not branch:
        return None

    result = git_runner(repo_root, "remote", "get-url", remote)
    if result.returncode != 0:
        return None

    return remote, f"refs/heads/{branch}", f"refs/remotes/{remote}/{branch}"


def sync_base_ref(repo_root: str, git_runner=_git) -> bool:
    base_ref = zsv_base_ref()
    if not base_ref:
        return True

    fetch_spec = remote_base_ref_fetch_spec(repo_root, base_ref, git_runner=git_runner)
    if fetch_spec is None:
        LOG.error("Configured base ref %s must be a remote branch such as origin/<branch>", base_ref)
        return False

    remote, remote_ref, local_ref = fetch_spec
    result = git_runner(repo_root, "fetch", remote, f"+{remote_ref}:{local_ref}")
    if result.returncode == 0:
        return True

    LOG.error(
        "Failed to fetch upstream base ref %s from %s in %s: %s",
        base_ref,
        remote,
        repo_root,
        (result.stderr or "").strip(),
    )
    return False
