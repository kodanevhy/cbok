from __future__ import annotations

import collections
import hashlib
import json
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
DEFAULT_SITE_PACKAGES = "/var/lib/zstack/virtualenv/kvm/lib/python2.7/site-packages"
DEFAULT_CEPH_PRIMARY_VIRTUALENV = "/var/lib/zstack/virtualenv/cephp"
DEFAULT_CEPH_PRIMARY_SITE_PACKAGES = "/var/lib/zstack/virtualenv/cephp/lib/python2.7/site-packages"
DEFAULT_ZBS_PRIMARY_VIRTUALENV = "/var/lib/zstack/virtualenv/zbsp"
DEFAULT_ZBS_PRIMARY_SITE_PACKAGES = "/var/lib/zstack/virtualenv/zbsp/lib/python2.7/site-packages"
DEFAULT_BACKUP_ROOT = "/var/lib/zstack/agent-replace-backup"
REMOTE_AGENT_ARCHIVE = "/tmp/cbok-zsv-agent-replace.tar.gz"
REMOTE_AGENT_STAGING = "/tmp/cbok-zsv-agent-replace"

ChangedFile = collections.namedtuple(
    "ChangedFile",
    ["repo_path", "local_path", "remote_path", "package_name", "runtime", "is_python"],
)
DiscoverResult = collections.namedtuple("DiscoverResult", ["paths", "change_scope"])
RuntimeDeployConfig = collections.namedtuple(
    "RuntimeDeployConfig",
    ["site_packages", "virtualenv", "service_name", "process_pattern"],
)

ALLOWED_ROOTS = (
    ("kvmagent/kvmagent/", "kvmagent", "kvm"),
    ("zstacklib/zstacklib/", "zstacklib", "kvm"),
    ("cephprimarystorage/cephprimarystorage/", "cephprimarystorage", "ceph-primary"),
    ("zbsprimarystorage/zbsprimarystorage/", "zbsprimarystorage", "zbs-primary"),
)
IGNORED_RUNTIME_ROOTS = (
    "kvmagent/kvmagent/test/",
    "zstacklib/zstacklib/test/",
    "cephprimarystorage/cephprimarystorage/test/",
    "zbsprimarystorage/zbsprimarystorage/test/",
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


def _append_paths(paths: list[str], output: str) -> None:
    for line in (output or "").splitlines():
        path = line.strip()
        if path and not is_ignored_runtime_path(path) and path not in paths:
            paths.append(path)


def discover_changed_files(
    repo: str,
    command_runner=run_git,
) -> DiscoverResult:
    effective_base = "HEAD^..HEAD"
    paths: list[str] = []

    _append_paths(
        paths,
        command_runner(
            [
                "git",
                "diff",
                "--name-only",
                "--diff-filter=ACMRTD",
                "HEAD^",
                "HEAD",
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
    return DiscoverResult(paths=paths, change_scope=effective_base)


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


def is_ignored_runtime_path(path: str) -> bool:
    repo_path = normalize_repo_path(path)
    return any(repo_path.startswith(root) for root in IGNORED_RUNTIME_ROOTS)


def _local_path(repo: str, repo_path: str) -> str:
    root = os.path.abspath(repo)
    local_path = os.path.abspath(os.path.join(root, *repo_path.split("/")))
    if local_path != root and not local_path.startswith(root + os.sep):
        raise AgentReplaceError("unsafe changed file path: %s" % repo_path)
    return local_path


def map_changed_file(repo: str, path: str) -> ChangedFile:
    repo_path = normalize_repo_path(path)
    if is_ignored_runtime_path(repo_path):
        raise AgentReplaceError("changed file is in ignored test scope: %s" % repo_path)
    for root, package_name, runtime in ALLOWED_ROOTS:
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
                runtime=runtime,
                is_python=remote_path.endswith(".py"),
            )
    raise AgentReplaceError(
        "changed file is outside kvmagent/zstacklib/cephprimarystorage/zbsprimarystorage runtime scope: %s" % repo_path
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


def _dedupe_paths(paths: list[str]) -> list[str]:
    out: list[str] = []
    for path in paths:
        repo_path = normalize_repo_path(path)
        if is_ignored_runtime_path(repo_path):
            continue
        if repo_path not in out:
            out.append(repo_path)
    return out


def agent_replace_worktree_key(repo: str) -> str:
    return hashlib.sha256(os.path.realpath(repo).encode("utf-8")).hexdigest()


def _encode_paths(paths: list[str]) -> str:
    return json.dumps(_dedupe_paths(paths), sort_keys=True)


def _decode_paths(value: str) -> list[str]:
    if not value:
        return []
    try:
        paths = json.loads(value)
    except ValueError as exc:
        raise AgentReplaceError("invalid agent replace DB state: %s" % exc)
    if not isinstance(paths, list):
        raise AgentReplaceError("invalid agent replace DB state: paths must be a list")
    return _dedupe_paths(paths)


class InMemoryAgentReplaceStateStore:
    def __init__(self):
        self.paths_by_key: dict[str, list[str]] = {}

    def load_paths(self, worktree_key: str) -> list[str]:
        return list(self.paths_by_key.get(worktree_key, []))

    def save_paths(self, worktree_key: str, utility_root: str, paths: list[str]) -> None:
        self.paths_by_key[worktree_key] = _dedupe_paths(paths)


class DjangoAgentReplaceStateStore:
    def load_paths(self, worktree_key: str) -> list[str]:
        from cbok.bbx.models import ZsvAgentReplaceState

        obj = ZsvAgentReplaceState.objects.filter(worktree_key=worktree_key).first()
        return _decode_paths(obj.last_deployed_paths) if obj else []

    def save_paths(self, worktree_key: str, utility_root: str, paths: list[str]) -> None:
        from django.utils import timezone

        from cbok.bbx.models import ZsvAgentReplaceState

        obj, _created = ZsvAgentReplaceState.objects.get_or_create(
            worktree_key=worktree_key,
            defaults={
                "utility_root": utility_root,
            },
        )
        obj.utility_root = utility_root
        obj.last_deployed_paths = _encode_paths(paths)
        obj.last_deployed_at = timezone.now()
        obj.save(update_fields=["utility_root", "last_deployed_paths", "last_deployed_at"])


def default_agent_replace_state_store():
    try:
        from django.apps import apps
    except Exception as exc:
        raise AgentReplaceError("Django app registry is required for zsv agent replace state") from exc

    if not apps.ready:
        raise AgentReplaceError("Django app registry is not ready for zsv agent replace state")
    return DjangoAgentReplaceStateStore()


def load_last_deployed_paths(worktree_key: str, state_store) -> list[str]:
    return state_store.load_paths(worktree_key)


def save_last_deployed_paths(worktree_key: str, utility_root: str, paths: list[str], state_store) -> None:
    state_store.save_paths(worktree_key, utility_root, _dedupe_paths(paths))


def merge_current_and_last_paths(current_paths: list[str], last_paths: list[str]) -> list[str]:
    return _dedupe_paths(current_paths + last_paths)


def unique_packages(files: list[ChangedFile]) -> list[str]:
    out: list[str] = []
    for file in files:
        if file.package_name not in out:
            out.append(file.package_name)
    return out


def group_files_by_runtime(files: list[ChangedFile]) -> dict[str, list[ChangedFile]]:
    out: dict[str, list[ChangedFile]] = collections.OrderedDict()
    for file in files:
        out.setdefault(file.runtime, []).append(file)
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
    virtualenv: str = DEFAULT_KVM_VIRTUALENV,
    backup_root: str = DEFAULT_BACKUP_ROOT,
    restart_agent: bool = True,
    service_name: str = "zstack-kvmagent",
    process_pattern: str = "from kvmagent import kdaemon",
) -> str:
    package_args = " ".join(shlex.quote(pkg) for pkg in unique_packages(files))
    restart_value = "true" if restart_agent else "false"
    import_lines = "\n".join("import %s" % pkg for pkg in unique_packages(files))
    return f"""set -euo pipefail
STAGE_DIR={shlex.quote(staging_dir)}
SITE_PACKAGES={shlex.quote(site_packages)}
AGENT_VIRTUALENV={shlex.quote(virtualenv)}
BACKUP_ROOT={shlex.quote(backup_root)}
RESTART_AGENT={restart_value}
SERVICE_NAME={shlex.quote(service_name)}
PROCESS_PATTERN={shlex.quote(process_pattern)}
PYTHON="$AGENT_VIRTUALENV/bin/python"
if [[ ! -x "$PYTHON" ]]; then PYTHON=python; fi
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
restart_agent() {{
  if [[ -x "/etc/init.d/$SERVICE_NAME" ]]; then
    "/etc/init.d/$SERVICE_NAME" restart
  elif command -v systemctl >/dev/null 2>&1; then
    systemctl restart "$SERVICE_NAME"
  else
    service "$SERVICE_NAME" restart
  fi
}}
check_agent() {{
  if [[ -x "/etc/init.d/$SERVICE_NAME" ]]; then
    "/etc/init.d/$SERVICE_NAME" status && return 0
  elif command -v systemctl >/dev/null 2>&1; then
    systemctl is-active "$SERVICE_NAME" && return 0
  else
    service "$SERVICE_NAME" status && return 0
  fi
  pgrep -f "$PROCESS_PATTERN" >/dev/null
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
    restart_agent || true
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
{import_lines}
PYEOF
if [[ "$RESTART_AGENT" == "true" ]]; then
  restart_agent
  sleep 2
  check_agent
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
    config: RuntimeDeployConfig,
    backup_root: str,
    restart_agent: bool,
    runner,
) -> int:
    script = build_remote_apply_script(
        staging_dir,
        files,
        site_packages=config.site_packages,
        virtualenv=config.virtualenv,
        backup_root=backup_root,
        restart_agent=restart_agent,
        service_name=config.service_name,
        process_pattern=config.process_pattern,
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
    nodes_by_runtime: dict[str, list[str]],
    dry_run: bool,
    replayed_paths: list[str] | None = None,
) -> None:
    print("== ZSV agent replace ==")
    print("utility:", utility_root)
    print("changes:", "%s + worktree" % discovery.change_scope)
    print("mode:", "dry-run" if dry_run else "apply")
    print("\n== Files ==")
    for file in files:
        print("%s -> %s [%s]" % (file.repo_path, file.remote_path, file.runtime))
    if replayed_paths:
        print("\n== Replayed from previous deploy ==")
        for path in replayed_paths:
            print(path)
    print("\n== Nodes ==")
    for runtime, runtime_nodes in nodes_by_runtime.items():
        print("%s:" % runtime)
        for node in runtime_nodes:
            print("  %s" % node)
    sys.stdout.flush()


def run_agent_replace_flow(
    *,
    utility_root: str | None,
    nodes,
    site_packages: str = DEFAULT_SITE_PACKAGES,
    kvm_virtualenv: str = DEFAULT_KVM_VIRTUALENV,
    ceph_primary_nodes=None,
    ceph_primary_site_packages: str = DEFAULT_CEPH_PRIMARY_SITE_PACKAGES,
    ceph_primary_virtualenv: str = DEFAULT_CEPH_PRIMARY_VIRTUALENV,
    zbs_primary_nodes=None,
    zbs_primary_site_packages: str = DEFAULT_ZBS_PRIMARY_SITE_PACKAGES,
    zbs_primary_virtualenv: str = DEFAULT_ZBS_PRIMARY_VIRTUALENV,
    backup_root: str = DEFAULT_BACKUP_ROOT,
    dry_run: bool = False,
    no_restart: bool = False,
    runner,
    ensure_remote_scriptlet=None,
    changed_paths: list[str] | None = None,
    command_runner=run_git,
    state_store=None,
) -> int:
    root = os.path.realpath(utility_root or default_utility_root())
    node_list = parse_nodes(nodes)
    ceph_primary_node_list = parse_nodes(ceph_primary_nodes)
    zbs_primary_node_list = parse_nodes(zbs_primary_nodes)
    if not os.path.isdir(root):
        LOG.error("utility root not found: %s", root)
        return 1

    try:
        auto_discovery = changed_paths is None
        if changed_paths is None:
            discovery = discover_changed_files(root, command_runner=command_runner)
            changed_paths = discovery.paths
        else:
            discovery = DiscoverResult(
                paths=list(changed_paths),
                change_scope="explicit changed paths",
            )
        current_paths = _dedupe_paths(changed_paths)
        worktree_key = agent_replace_worktree_key(root)
        store = (state_store or default_agent_replace_state_store()) if auto_discovery else None
        last_paths = load_last_deployed_paths(worktree_key, store) if auto_discovery else []
        deploy_paths = merge_current_and_last_paths(current_paths, last_paths)
        replayed_paths = [path for path in deploy_paths if path not in current_paths]
        if not deploy_paths:
            LOG.error("No changed runtime files found in utility root.")
            return 1
        files = validate_changed_files(root, deploy_paths)
    except AgentReplaceError as exc:
        LOG.error("%s", exc)
        return 1

    files_by_runtime = group_files_by_runtime(files)
    nodes_by_runtime = {
        "kvm": node_list,
        "ceph-primary": ceph_primary_node_list,
        "zbs-primary": zbs_primary_node_list,
    }
    required_runtimes = set(files_by_runtime)
    if "kvm" in required_runtimes and not node_list:
        LOG.error("No ZSV nodes specified for kvmagent/zstacklib files.")
        return 1
    if "ceph-primary" in required_runtimes and not ceph_primary_node_list:
        LOG.error("No Ceph primary storage mon nodes specified for cephprimarystorage files.")
        return 1
    if "zbs-primary" in required_runtimes and not zbs_primary_node_list:
        LOG.error("No ZBS primary storage nodes specified for zbsprimarystorage files.")
        return 1

    print_plan(root, discovery, files, nodes_by_runtime, dry_run, replayed_paths)
    if dry_run:
        return 0

    configs = {
        "kvm": RuntimeDeployConfig(
            site_packages,
            kvm_virtualenv,
            "zstack-kvmagent",
            "from kvmagent import kdaemon",
        ),
        "ceph-primary": RuntimeDeployConfig(
            ceph_primary_site_packages,
            ceph_primary_virtualenv,
            "zstack-ceph-primarystorage",
            "from cephprimarystorage import cdaemon",
        ),
        "zbs-primary": RuntimeDeployConfig(
            zbs_primary_site_packages,
            zbs_primary_virtualenv,
            "zstack-zbs-primarystorage",
            "from zbsprimarystorage import zdaemon",
        ),
    }
    for runtime, runtime_files in files_by_runtime.items():
        archive_path = create_agent_archive(runtime_files)
        try:
            for node in nodes_by_runtime[runtime]:
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
                    runtime_files,
                    configs[runtime],
                    backup_root,
                    not no_restart,
                    runner,
                )
                if rc != 0:
                    return rc
        finally:
            Path(archive_path).unlink(missing_ok=True)
    if auto_discovery:
        try:
            save_last_deployed_paths(worktree_key, root, current_paths, store)
        except AgentReplaceError as exc:
            LOG.error("%s", exc)
            return 1
    return 0
