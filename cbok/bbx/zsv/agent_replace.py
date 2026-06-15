from __future__ import annotations

import collections
import logging
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


LOG = logging.getLogger(__name__)

DEFAULT_KVM_VIRTUALENV = "/var/lib/zstack/virtualenv/kvm"
DEFAULT_SITE_PACKAGES = "auto"
DEFAULT_BACKUP_ROOT = "/var/lib/zstack/agent-replace-backup"
REMOTE_AGENT_ARCHIVE = "/tmp/cbok-zsv-agent-replace.tar.gz"
REMOTE_AGENT_STAGING = "/tmp/cbok-zsv-agent-replace"

ChangedFile = collections.namedtuple(
    "ChangedFile",
    ["repo_path", "local_path", "remote_path", "package_name", "is_python"],
)
DiscoverResult = collections.namedtuple("DiscoverResult", ["paths", "base_ref"])

ALLOWED_ROOTS = (
    ("kvmagent/kvmagent/", "kvmagent"),
    ("zstacklib/zstacklib/", "zstacklib"),
)


class AgentReplaceError(Exception):
    pass


def default_utility_root() -> str:
    from cbok import settings

    return os.path.realpath(
        os.path.join(
            settings.Workspace,
            "Cursor",
            "zs",
            "zstack-workspace",
            "zstack-utility",
        )
    )


def run_git(cmd: list[str], cwd: str | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AgentReplaceError(
            "command failed: %s\nreturn code: %s\nstdout: %s\nstderr: %s"
            % (
                " ".join(cmd),
                proc.returncode,
                (proc.stdout or "").strip(),
                (proc.stderr or "").strip(),
            )
        )
    return (proc.stdout or "").strip()


def resolve_default_base_ref(repo: str, command_runner=run_git) -> str | None:
    try:
        upstream = command_runner(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
            cwd=repo,
        ).strip()
        if upstream:
            return upstream
    except AgentReplaceError:
        pass

    try:
        branch = command_runner(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).strip()
        if branch and branch != "HEAD":
            candidate = "origin/%s" % branch
            command_runner(["git", "rev-parse", "--verify", candidate], cwd=repo)
            return candidate
    except AgentReplaceError:
        pass

    return None


def _append_paths(paths: list[str], output: str) -> None:
    for line in (output or "").splitlines():
        path = line.strip()
        if path and path not in paths:
            paths.append(path)


def discover_changed_files(
    repo: str,
    base_ref: str | None = None,
    command_runner=run_git,
) -> DiscoverResult:
    effective_base = base_ref or resolve_default_base_ref(repo, command_runner)
    paths: list[str] = []

    if effective_base:
        _append_paths(
            paths,
            command_runner(
                [
                    "git",
                    "diff",
                    "--name-only",
                    "--diff-filter=ACMRTD",
                    "%s...HEAD" % effective_base,
                ],
                cwd=repo,
            ),
        )

    _append_paths(
        paths,
        command_runner(["git", "diff", "--name-only", "--diff-filter=ACMRTD"], cwd=repo),
    )
    _append_paths(
        paths,
        command_runner(
            ["git", "diff", "--name-only", "--cached", "--diff-filter=ACMRTD"],
            cwd=repo,
        ),
    )
    _append_paths(
        paths,
        command_runner(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo),
    )
    return DiscoverResult(paths=paths, base_ref=effective_base)


def parse_nodes(nodes) -> list[str]:
    if not nodes:
        return []
    if isinstance(nodes, str):
        raw = nodes.replace(",", " ").split()
    else:
        raw = []
        for node in nodes:
            raw.extend(str(node).replace(",", " ").split())

    out: list[str] = []
    for node in raw:
        node = node.strip()
        if node and node not in out:
            out.append(node)
    return out


def normalize_repo_path(path: str) -> str:
    normalized = str(path).replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        raise AgentReplaceError("empty changed file path")
    if normalized.startswith("/") or normalized == ".." or normalized.startswith("../") or "/../" in normalized:
        raise AgentReplaceError("unsafe changed file path: %s" % normalized)
    if "\n" in normalized or "\r" in normalized:
        raise AgentReplaceError("unsafe changed file path: %s" % normalized)
    return normalized


def _local_path(repo: str, repo_path: str) -> str:
    root = os.path.abspath(repo)
    local_path = os.path.abspath(os.path.join(root, *repo_path.split("/")))
    if local_path != root and not local_path.startswith(root + os.sep):
        raise AgentReplaceError("unsafe changed file path: %s" % repo_path)
    return local_path


def map_changed_file(repo: str, path: str) -> ChangedFile:
    repo_path = normalize_repo_path(path)
    for root, package_name in ALLOWED_ROOTS:
        if repo_path.startswith(root):
            suffix = repo_path[len(root):]
            if not suffix:
                break
            local_path = _local_path(repo, repo_path)
            if not os.path.isfile(local_path):
                raise AgentReplaceError("changed file does not exist locally: %s" % repo_path)
            remote_path = "%s/%s" % (package_name, suffix)
            return ChangedFile(
                repo_path=repo_path,
                local_path=local_path,
                remote_path=remote_path,
                package_name=package_name,
                is_python=remote_path.endswith(".py"),
            )
    raise AgentReplaceError(
        "changed file is outside kvmagent/zstacklib runtime scope: %s" % repo_path
    )


def validate_changed_files(repo: str, paths: list[str]) -> list[ChangedFile]:
    out: list[ChangedFile] = []
    seen: set[str] = set()
    for path in paths:
        changed = map_changed_file(repo, path)
        if changed.remote_path in seen:
            continue
        seen.add(changed.remote_path)
        out.append(changed)
    return out


def unique_packages(files: list[ChangedFile]) -> list[str]:
    out: list[str] = []
    for file in files:
        if file.package_name not in out:
            out.append(file.package_name)
    return out


def create_agent_archive(files: list[ChangedFile]) -> str:
    fd, archive_path = tempfile.mkstemp(prefix="cbok-zsv-agent-", suffix=".tar.gz")
    os.close(fd)
    with tarfile.open(archive_path, "w:gz") as tar:
        for file in files:
            tar.add(file.local_path, arcname=file.remote_path)
    return archive_path


def build_remote_apply_script(
    staging_dir: str,
    files: list[ChangedFile],
    *,
    site_packages: str = DEFAULT_SITE_PACKAGES,
    kvm_virtualenv: str = DEFAULT_KVM_VIRTUALENV,
    backup_root: str = DEFAULT_BACKUP_ROOT,
    restart_agent: bool = True,
) -> str:
    package_args = " ".join(shlex.quote(pkg) for pkg in unique_packages(files))
    restart_value = "true" if restart_agent else "false"
    return f"""set -euo pipefail
STAGE_DIR={shlex.quote(staging_dir)}
SITE_PACKAGES={shlex.quote(site_packages)}
KVM_VIRTUALENV={shlex.quote(kvm_virtualenv)}
BACKUP_ROOT={shlex.quote(backup_root)}
RESTART_AGENT={restart_value}
PYTHON="$KVM_VIRTUALENV/bin/python"
if [[ ! -x "$PYTHON" ]]; then PYTHON=python; fi
if [[ "$SITE_PACKAGES" == "auto" ]]; then
  SITE_PACKAGES=$("$PYTHON" - <<'PYEOF'
from distutils.sysconfig import get_python_lib
print(get_python_lib())
PYEOF
)
fi
[[ -d "$STAGE_DIR" ]] || die "agent staging dir missing: $STAGE_DIR"
[[ -d "$SITE_PACKAGES" ]] || die "site-packages missing: $SITE_PACKAGES"
BACKUP_DIR="$BACKUP_ROOT/$(date +%Y%m%d%H%M%S)-$$"
mkdir -p "$BACKUP_DIR"
packages=({package_args})
backup_package() {{
  local pkg="$1"
  [[ -d "$SITE_PACKAGES/$pkg" ]] || die "remote package missing: $SITE_PACKAGES/$pkg"
  rm -rf "$BACKUP_DIR/$pkg"
  cp -a "$SITE_PACKAGES/$pkg" "$BACKUP_DIR/$pkg"
}}
restore_package() {{
  local pkg="$1"
  if [[ -d "$BACKUP_DIR/$pkg" ]]; then
    rm -rf "$SITE_PACKAGES/$pkg"
    cp -a "$BACKUP_DIR/$pkg" "$SITE_PACKAGES/$pkg"
  fi
}}
restart_kvmagent() {{
  if [[ -x /etc/init.d/zstack-kvmagent ]]; then
    /etc/init.d/zstack-kvmagent restart
  elif command -v systemctl >/dev/null 2>&1; then
    systemctl restart zstack-kvmagent
  else
    service zstack-kvmagent restart
  fi
}}
check_kvmagent() {{
  if [[ -x /etc/init.d/zstack-kvmagent ]]; then
    /etc/init.d/zstack-kvmagent status
  elif command -v systemctl >/dev/null 2>&1; then
    systemctl is-active zstack-kvmagent
  else
    service zstack-kvmagent status
  fi
}}
restore_on_error() {{
  local rc=$?
  trap - ERR
  log_warn "zsv agent replace failed, restoring from $BACKUP_DIR"
  local pkg
  for pkg in "${{packages[@]}}"; do
    restore_package "$pkg"
  done
  if [[ "$RESTART_AGENT" == "true" ]]; then
    restart_kvmagent || true
  fi
  exit "$rc"
}}
for pkg in "${{packages[@]}}"; do
  backup_package "$pkg"
done
trap restore_on_error ERR
while IFS= read -r -d '' src; do
  rel="${{src#"$STAGE_DIR"/}}"
  dst="$SITE_PACKAGES/$rel"
  mkdir -p "$(dirname "$dst")"
  cp -f "$src" "$dst"
done < <(find "$STAGE_DIR" -type f -print0)
for pkg in "${{packages[@]}}"; do
  "$PYTHON" -m compileall -q "$SITE_PACKAGES/$pkg"
done
PYTHONPATH="$SITE_PACKAGES${{PYTHONPATH:+:$PYTHONPATH}}" "$PYTHON" - <<'PYEOF'
import kvmagent
import zstacklib
PYEOF
if [[ "$RESTART_AGENT" == "true" ]]; then
  restart_kvmagent
  sleep 2
  check_kvmagent
fi
trap - ERR
rm -rf "$STAGE_DIR"
log_info "zsv agent replace backup: $BACKUP_DIR"
"""


def _bash_scriptlet(expr: str) -> list[str]:
    return ["bash", "-lc", "source scriptlet/bootstrap.sh; %s" % expr]


def scriptlet_stage_agent_archive(
    address: str,
    archive_path: str,
    remote_archive: str,
    staging_dir: str,
    runner,
) -> int:
    expr = "zsv_agent_stage_archive %s %s %s %s" % (
        shlex.quote(address),
        shlex.quote(archive_path),
        shlex.quote(remote_archive),
        shlex.quote(staging_dir),
    )
    result = runner.run_command(_bash_scriptlet(expr), cmd_purge_output=False)
    return getattr(result, "returncode", 1) or 0


def scriptlet_apply_agent_staging(
    address: str,
    staging_dir: str,
    files: list[ChangedFile],
    site_packages: str,
    kvm_virtualenv: str,
    backup_root: str,
    restart_agent: bool,
    runner,
) -> int:
    script = build_remote_apply_script(
        staging_dir,
        files,
        site_packages=site_packages,
        kvm_virtualenv=kvm_virtualenv,
        backup_root=backup_root,
        restart_agent=restart_agent,
    )
    expr = "zsv_agent_apply_staging %s %s" % (
        shlex.quote(address),
        shlex.quote(script),
    )
    result = runner.run_command(_bash_scriptlet(expr), cmd_purge_output=False)
    return getattr(result, "returncode", 1) or 0


def print_plan(
    utility_root: str,
    discovery: DiscoverResult,
    files: list[ChangedFile],
    nodes: list[str],
    dry_run: bool,
) -> None:
    print("== ZSV agent replace ==")
    print("utility:", utility_root)
    print("base:", discovery.base_ref or "(none; worktree/index/untracked only)")
    print("mode:", "dry-run" if dry_run else "apply")
    print("\n== Files ==")
    for file in files:
        print("%s -> %s" % (file.repo_path, file.remote_path))
    print("\n== Nodes ==")
    for node in nodes:
        print(node)
    sys.stdout.flush()


def run_agent_replace_flow(
    *,
    utility_root: str | None,
    nodes,
    base_ref: str | None = None,
    site_packages: str = DEFAULT_SITE_PACKAGES,
    kvm_virtualenv: str = DEFAULT_KVM_VIRTUALENV,
    backup_root: str = DEFAULT_BACKUP_ROOT,
    dry_run: bool = False,
    no_restart: bool = False,
    runner,
    ensure_remote_scriptlet=None,
    changed_paths: list[str] | None = None,
) -> int:
    root = os.path.realpath(utility_root or default_utility_root())
    node_list = parse_nodes(nodes)
    if not node_list:
        LOG.error("No ZSV nodes specified.")
        return 1
    if not os.path.isdir(root):
        LOG.error("utility root not found: %s", root)
        return 1

    try:
        if changed_paths is None:
            discovery = discover_changed_files(root, base_ref=base_ref)
            changed_paths = discovery.paths
        else:
            discovery = DiscoverResult(paths=list(changed_paths), base_ref=base_ref)
        if not changed_paths:
            LOG.error("No changed files found in utility root.")
            return 1
        files = validate_changed_files(root, changed_paths)
    except AgentReplaceError as exc:
        LOG.error("%s", exc)
        return 1

    print_plan(root, discovery, files, node_list, dry_run)
    if dry_run:
        return 0

    archive_path = create_agent_archive(files)
    try:
        for node in node_list:
            if ensure_remote_scriptlet:
                ensured = ensure_remote_scriptlet(node)
                if getattr(ensured, "returncode", 0) != 0:
                    return getattr(ensured, "returncode", 1) or 1
            rc = scriptlet_stage_agent_archive(
                node,
                archive_path,
                REMOTE_AGENT_ARCHIVE,
                REMOTE_AGENT_STAGING,
                runner,
            )
            if rc != 0:
                return rc
            rc = scriptlet_apply_agent_staging(
                node,
                REMOTE_AGENT_STAGING,
                files,
                site_packages,
                kvm_virtualenv,
                backup_root,
                not no_restart,
                runner,
            )
            if rc != 0:
                return rc
    finally:
        Path(archive_path).unlink(missing_ok=True)
    return 0
