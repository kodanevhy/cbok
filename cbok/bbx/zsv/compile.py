"""
ZSvirt: build changed modules from explicit main and zsvirt-ee worktree roots.
"""
from __future__ import annotations

from collections.abc import Collection
import hashlib
import json
import logging
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.apps import apps
from django.utils import timezone

from cbok import settings
from cbok.bbx.models import ZsvCompileState
from cbok.bbx.zsv import base_ref as zsv_base_ref
from cbok.bbx.zsv import config as zsv_config
from cbok.bbx.zsv.worktree_container import DEFAULT_MIN_FREE_GB
from cbok.bbx.zsv.worktree_container import WorktreeContainerSpec
from cbok.bbx.zsv.worktree_container import ensure_worktree_container
from cbok.bbx.zsv.worktree_container import parse_worktree_pr_refs
from cbok.bbx.zsv.worktree_container import worktree_key_for_spec


LOG = logging.getLogger(__name__)

DEFAULT_REMOTE_LIB = (
    "/usr/local/zstack/apache-tomcat/webapps/zstack/WEB-INF/lib"
)
REMOTE_JAR_STAGING = "/tmp/cbok-zsv-compile-jars"

_SKIP_JAR_SUFFIXES = (
    "-sources.jar",
    "-javadoc.jar",
    "-tests.jar",
    "-fat.jar",
    "-all.jar",
    "-with-dependencies.jar",
    "-shaded.jar",
)
DEPLOY_AUTO_EXCLUDED_MODULES = frozenset(
    ("test", "testlib", "test-premium", "testlib-premium", "tests", "tests-ee", "test-ee", "testlib-ee")
)
MAVEN_PROFILE_PREPARE_CMD = "./runMavenProfile ee"
RSYNC_SOURCE_EXCLUDES = "--exclude .git --exclude target --exclude '*/target' --exclude '._*' --exclude '.DS_Store' --exclude '__MACOSX'"
SPRING_CONFIG_PREFIX = "conf/springConfigXml/"


@dataclass(frozen=True)
class MavenBuildPlan:
    modules: list[str]
    profiles: list[str]


@dataclass(frozen=True)
class RemoteDockerCompileConfig:
    image: str
    platform: str
    docker_host: str
    workdir: str
    container_name: str
    m2_volume: str
    min_free_gb: int = DEFAULT_MIN_FREE_GB


@dataclass(frozen=True)
class WebClassesFile:
    source: str
    relative_path: str


@dataclass(frozen=True)
class CompileWebClassesState:
    repo: str
    source_relative_path: str
    relative_path: str


@dataclass(frozen=True)
class CompileDeploySelection:
    main_modules: list[str]
    ee_modules: list[str]
    web_classes: list[CompileWebClassesState]


@dataclass(frozen=True)
class JavaInterfaceChange:
    name: str
    package: str

    @property
    def fqn(self) -> str:
        return f"{self.package}.{self.name}" if self.package else self.name


def _conf_get(section: str, option: str, default: str) -> str:
    conf = settings.CONF
    if conf.has_section(section) and conf.has_option(section, option):
        return conf.get(section, option).strip()
    return default


def _conf_int(section: str, option: str, default: int) -> int:
    value = _conf_get(section, option, str(default))
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        LOG.warning("Invalid [%s] %s=%r; using %s.", section, option, value, default)
        return default


def _normalize_docker_host(raw: str | None) -> str:
    host = (raw or "").strip()
    if host.startswith("http://"):
        return "tcp://" + host[len("http://"):]
    if host.startswith("https://"):
        return "tcp://" + host[len("https://"):]
    return host


def remote_docker_compile_from_conf() -> RemoteDockerCompileConfig:
    return RemoteDockerCompileConfig(
        image=_conf_get("zsv_compile", "remote_docker_image", "registry.docker.zstack.io:80/buildbin:debug9-zsvirt"),
        platform=_conf_get("zsv_compile", "remote_docker_platform", "linux/amd64"),
        docker_host=_normalize_docker_host(_conf_get("zsv_compile", "remote_docker_host", "")),
        workdir=_conf_get("zsv_compile", "remote_docker_workdir", "/work").rstrip("/"),
        container_name="auto",
        m2_volume=_conf_get("zsv_compile", "remote_docker_m2_volume", "auto"),
        min_free_gb=_conf_int("zsv_compile", "remote_docker_min_free_gb", DEFAULT_MIN_FREE_GB),
    )


def _git(root: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", root, *args],
        capture_output=True,
        text=True,
    )


def git_summary(root: str) -> tuple[str, str]:
    r = _git(root, "log", "-1", "--oneline")
    head = (r.stdout or "").strip() if r.returncode == 0 else f"(git error: {r.stderr})"
    r2 = _git(root, "rev-parse", "HEAD")
    full = (r2.stdout or "").strip() if r2.returncode == 0 else ""
    return head, full


def git_branch_name(root: str) -> str:
    r = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if r.returncode != 0:
        LOG.debug("Failed to read git branch in %s: %s", root, (r.stderr or "").strip())
        return ""
    return (r.stdout or "").strip()


def is_git_worktree(root: str) -> bool:
    r = _git(root, "rev-parse", "--is-inside-work-tree")
    return r.returncode == 0 and (r.stdout or "").strip() == "true"


def validate_same_branch(zsvirt_root: str, ee_root: str) -> bool:
    zsvirt_branch = git_branch_name(zsvirt_root)
    ee_branch = git_branch_name(ee_root)
    if not zsvirt_branch or not ee_branch:
        return True
    if zsvirt_branch == ee_branch:
        return True

    LOG.error(
        "zsvirt and ee branch names must be the same (zsvirt: %s, ee: %s)",
        zsvirt_branch,
        ee_branch,
    )
    return False


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


class CompileDeployStateError(Exception):
    pass


def _compile_worktree_spec(
    zsvirt_root: str,
    ee_root: str | None,
    remote: RemoteDockerCompileConfig,
    pr_refs=(),
) -> WorktreeContainerSpec:
    return WorktreeContainerSpec(
        zsvirt_root=zsvirt_root,
        ee_root=ee_root,
        docker_host=_normalize_docker_host(remote.docker_host),
        image=remote.image,
        platform=remote.platform,
        workdir=remote.workdir or "/work",
        container_name=remote.container_name,
        m2_volume=remote.m2_volume,
        pr_refs=tuple(pr_refs or ()),
        min_free_gb=remote.min_free_gb,
    )


def compile_worktree_key(
    zsvirt_root: str,
    ee_root: str | None,
    remote: RemoteDockerCompileConfig,
) -> str:
    container_key = worktree_key_for_spec(
        _compile_worktree_spec(zsvirt_root, ee_root, remote)
    )
    base_ref = zsv_config.zsv_base_ref()
    return hashlib.sha256(f"{container_key}\0{base_ref}".encode("utf-8")).hexdigest()


def _encode_list(items: list[str]) -> str:
    return json.dumps(_dedupe(items), sort_keys=True)


def _decode_list(value: str) -> list[str]:
    if not value:
        return []
    try:
        items = json.loads(value)
    except ValueError as exc:
        raise CompileDeployStateError("invalid compile deploy DB state: %s" % exc)
    if not isinstance(items, list):
        raise CompileDeployStateError("invalid compile deploy DB state: expected list")
    return _dedupe([str(item) for item in items if str(item)])


def _encode_web_classes(items: list[CompileWebClassesState]) -> str:
    encoded = [
        {
            "repo": item.repo,
            "source_relative_path": item.source_relative_path,
            "relative_path": item.relative_path,
        }
        for item in _dedupe_web_classes_state(items)
    ]
    return json.dumps(encoded, sort_keys=True)


def _decode_web_classes(value: str) -> list[CompileWebClassesState]:
    if not value:
        return []
    try:
        items = json.loads(value)
    except ValueError as exc:
        raise CompileDeployStateError("invalid compile deploy web classes DB state: %s" % exc)
    if not isinstance(items, list):
        raise CompileDeployStateError("invalid compile deploy web classes DB state: expected list")
    out: list[CompileWebClassesState] = []
    for item in items:
        if not isinstance(item, dict):
            raise CompileDeployStateError("invalid compile deploy web classes DB state: expected object")
        repo = str(item.get("repo") or "")
        source_relative_path = str(item.get("source_relative_path") or "")
        relative_path = str(item.get("relative_path") or "")
        if repo not in ("zsvirt", "ee") or not source_relative_path or not relative_path:
            raise CompileDeployStateError("invalid compile deploy web classes DB state: missing fields")
        out.append(CompileWebClassesState(repo, source_relative_path, relative_path))
    return _dedupe_web_classes_state(out)


def _dedupe_web_classes_state(items: list[CompileWebClassesState]) -> list[CompileWebClassesState]:
    out: list[CompileWebClassesState] = []
    seen: set[str] = set()
    for item in items:
        if item.relative_path in seen:
            continue
        seen.add(item.relative_path)
        out.append(item)
    return out


def _dedupe_web_classes_files(items: list[WebClassesFile]) -> list[WebClassesFile]:
    out: list[WebClassesFile] = []
    seen: set[str] = set()
    for item in items:
        if item.relative_path in seen:
            continue
        seen.add(item.relative_path)
        out.append(item)
    return out


def _relative_to_root(path: Path, root: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def web_classes_state_from_files(
    files: list[WebClassesFile],
    zsvirt_root: str,
    ee_root: str | None,
) -> list[CompileWebClassesState]:
    zsvirt_path = Path(zsvirt_root).resolve()
    ee_path = Path(ee_root).resolve() if ee_root else None
    out: list[CompileWebClassesState] = []
    for item in files:
        source = Path(item.source).resolve()
        repo = "zsvirt"
        source_relative_path = _relative_to_root(source, zsvirt_path)
        if ee_path:
            ee_relative = _relative_to_root(source, ee_path)
            if ee_relative is not None:
                repo = "ee"
                source_relative_path = ee_relative
        if source_relative_path is None:
            raise CompileDeployStateError("web classes source is outside zsvirt/ee roots: %s" % item.source)
        out.append(CompileWebClassesState(repo, source_relative_path, item.relative_path))
    return _dedupe_web_classes_state(out)


def web_classes_files_from_state(
    selection: CompileDeploySelection,
    zsvirt_root: str,
    ee_root: str | None,
) -> list[WebClassesFile]:
    out: list[WebClassesFile] = []
    for item in selection.web_classes:
        if item.repo == "ee":
            if not ee_root:
                raise CompileDeployStateError("previous ee web classes deploy requires ee root")
            root = Path(ee_root)
        else:
            root = Path(zsvirt_root)
        source = root / item.source_relative_path
        if not source.is_file():
            raise CompileDeployStateError("previous web classes source is missing: %s" % source)
        out.append(WebClassesFile(str(source), item.relative_path))
    return _dedupe_web_classes_files(out)


def current_compile_deploy_selection(
    main_modules: list[str],
    ee_modules: list[str],
    web_classes_files: list[WebClassesFile],
    zsvirt_root: str,
    ee_root: str | None,
) -> CompileDeploySelection:
    return CompileDeploySelection(
        _dedupe(main_modules),
        _dedupe(ee_modules),
        web_classes_state_from_files(web_classes_files, zsvirt_root, ee_root),
    )


def merge_compile_deploy_selection(
    current: CompileDeploySelection,
    previous: CompileDeploySelection,
    zsvirt_root: str,
    ee_root: str | None,
) -> tuple[CompileDeploySelection, list[WebClassesFile]]:
    current_web_files = web_classes_files_from_state(current, zsvirt_root, ee_root)
    previous_web_files = web_classes_files_from_state(previous, zsvirt_root, ee_root)
    merged_web_files = _dedupe_web_classes_files(current_web_files + previous_web_files)
    return CompileDeploySelection(
        _dedupe(current.main_modules + previous.main_modules),
        _dedupe(current.ee_modules + previous.ee_modules),
        web_classes_state_from_files(merged_web_files, zsvirt_root, ee_root),
    ), merged_web_files


class InMemoryCompileDeployStateStore:
    def __init__(self):
        self.selections_by_key: dict[str, CompileDeploySelection] = {}

    def load_selection(self, worktree_key: str) -> CompileDeploySelection:
        return self.selections_by_key.get(worktree_key, CompileDeploySelection([], [], []))

    def save_selection(
        self,
        worktree_key: str,
        zsvirt_root: str,
        ee_root: str | None,
        selection: CompileDeploySelection,
    ) -> None:
        self.selections_by_key[worktree_key] = selection


class DjangoCompileDeployStateStore:
    def load_selection(self, worktree_key: str) -> CompileDeploySelection:
        obj = ZsvCompileState.objects.filter(worktree_key=worktree_key).first()
        if not obj:
            return CompileDeploySelection([], [], [])
        return CompileDeploySelection(
            _decode_list(obj.last_main_modules),
            _decode_list(obj.last_ee_modules),
            _decode_web_classes(obj.last_web_classes),
        )

    def save_selection(
        self,
        worktree_key: str,
        zsvirt_root: str,
        ee_root: str | None,
        selection: CompileDeploySelection,
    ) -> None:
        obj, _created = ZsvCompileState.objects.get_or_create(
            worktree_key=worktree_key,
            defaults={
                "zsvirt_root": zsvirt_root,
                "ee_root": ee_root or "",
            },
        )
        obj.zsvirt_root = zsvirt_root
        obj.ee_root = ee_root or ""
        obj.last_main_modules = _encode_list(selection.main_modules)
        obj.last_ee_modules = _encode_list(selection.ee_modules)
        obj.last_web_classes = _encode_web_classes(selection.web_classes)
        obj.last_deployed_at = timezone.now()
        obj.save(update_fields=[
            "zsvirt_root",
            "ee_root",
            "last_main_modules",
            "last_ee_modules",
            "last_web_classes",
            "last_deployed_at",
        ])


def default_compile_deploy_state_store():
    if not apps.ready:
        raise CompileDeployStateError("Django app registry is not ready for zsv compile deploy state")
    return DjangoCompileDeployStateStore()


def _is_auto_excluded(
    module: str,
    excluded_modules: Collection[str] = DEPLOY_AUTO_EXCLUDED_MODULES,
) -> bool:
    return any(part in excluded_modules for part in module.split("/"))


def module_for_changed_path(
    repo_root: str,
    rel_path: str,
    excluded_modules: Collection[str] = DEPLOY_AUTO_EXCLUDED_MODULES,
) -> str | None:
    path = Path(str(rel_path).replace("\\", "/"))
    if path.is_absolute() or not path.parts:
        return None

    root = Path(repo_root)
    current = root.joinpath(*path.parts)
    candidate = current if current.is_dir() else current.parent
    while candidate != root and root in candidate.parents:
        if (candidate / "pom.xml").is_file():
            module = candidate.relative_to(root).as_posix()
            if _is_auto_excluded(module, excluded_modules):
                return None
            return module
        candidate = candidate.parent
    return None


def modules_from_changed_paths(
    zsvirt_root: str,
    main_paths: list[str],
    external_paths: list[str],
    external_root: str | None = None,
    excluded_modules: Collection[str] = DEPLOY_AUTO_EXCLUDED_MODULES,
) -> tuple[list[str], list[str]]:
    main: list[str] = []
    for path in main_paths:
        module = module_for_changed_path(zsvirt_root, path, excluded_modules)
        if module:
            main.append(module)

    external: list[str] = []
    external_root = external_root or os.path.join(zsvirt_root, "zsvirt-ee")
    for path in external_paths:
        module = module_for_changed_path(external_root, path, excluded_modules)
        if module:
            external.append(module)

    return _dedupe(main), _dedupe(external)


def _remote_base_ref_fetch_spec(repo_root: str, base_ref: str) -> tuple[str, str, str] | None:
    return zsv_base_ref.remote_base_ref_fetch_spec(repo_root, base_ref, git_runner=_git)


def sync_changed_paths_base_ref(repo_root: str) -> bool:
    return zsv_base_ref.sync_base_ref(repo_root, git_runner=_git)


def validate_changed_paths_base_ref(repo_root: str) -> bool:
    base_ref = zsv_config.zsv_base_ref()
    if not base_ref:
        LOG.error("ZSV base_ref is not configured; set [zsv] base_ref in cbok.conf.")
        return False

    if not sync_changed_paths_base_ref(repo_root):
        return False

    ancestor = _git(repo_root, "merge-base", "--is-ancestor", base_ref, "HEAD")
    if ancestor.returncode == 0:
        return True
    if ancestor.returncode == 1:
        LOG.error("Configured base ref %s is not an ancestor of HEAD in %s",
                  base_ref, repo_root)
    else:
        LOG.error("Failed to check base ref %s in %s: %s",
                  base_ref, repo_root, (ancestor.stderr or "").strip())
    return False


def changed_paths_from_head_commit(repo_root: str) -> list[str]:
    base_ref = zsv_config.zsv_base_ref()
    if base_ref:
        r = _git(repo_root, "diff", "--name-only", base_ref, "HEAD")
        if r.returncode == 0:
            return [line.strip() for line in (r.stdout or "").splitlines() if line.strip()]
        LOG.warning("Failed to read changed files since %s in %s: %s",
                    base_ref, repo_root, (r.stderr or "").strip())

    parent = _git(repo_root, "rev-parse", "--verify", "HEAD^")
    if parent.returncode == 0:
        r = _git(repo_root, "diff", "--name-only", "HEAD^", "HEAD")
    else:
        r = _git(repo_root, "diff-tree", "--root", "--no-commit-id",
                 "--name-only", "-r", "HEAD")
    if r.returncode != 0:
        LOG.warning("Failed to read HEAD changed files in %s: %s",
                    repo_root, (r.stderr or "").strip())
        return []
    return [line.strip() for line in (r.stdout or "").splitlines() if line.strip()]


def changed_paths_from_worktree(repo_root: str) -> list[str]:
    paths: list[str] = []
    for args in (
        ("diff", "--name-only", "HEAD"),
        ("ls-files", "--others", "--exclude-standard"),
    ):
        r = _git(repo_root, *args)
        if r.returncode != 0:
            LOG.warning("Failed to read worktree changed files in %s: %s",
                        repo_root, (r.stderr or "").strip())
            continue
        paths.extend(line.strip() for line in (r.stdout or "").splitlines() if line.strip())
    return _dedupe(paths)


def _web_classes_files_from_paths(repo_root: str, rel_paths: list[str]) -> list[WebClassesFile]:
    root = Path(repo_root)
    files: dict[str, WebClassesFile] = {}
    for rel_path in rel_paths:
        normalized = str(rel_path).replace("\\", "/")
        prefix = "premium/" + SPRING_CONFIG_PREFIX if normalized.startswith("premium/") else SPRING_CONFIG_PREFIX
        if not normalized.startswith(prefix):
            continue
        source = root / normalized
        if not source.is_file():
            continue
        target = normalized[len(prefix):].strip("/")
        if not target:
            continue
        files[f"springConfigXml/{target}"] = WebClassesFile(
            source=str(source),
            relative_path=f"springConfigXml/{target}",
        )
    return list(files.values())


def collect_web_classes_files(
    zsvirt_root: str,
    main_paths: list[str],
    ee_paths: list[str],
    ee_root: str | None = None,
) -> list[WebClassesFile]:
    files: dict[str, WebClassesFile] = {}
    for item in _web_classes_files_from_paths(zsvirt_root, main_paths):
        files[item.relative_path] = item
    if ee_root and os.path.isdir(ee_root):
        for item in _web_classes_files_from_paths(ee_root, ee_paths):
            files[item.relative_path] = item
    # Match the WAR overlay order even when only a lower-priority file changed.
    for target in list(files):
        relative = "conf/" + target
        for base in (Path(zsvirt_root) / "premium", Path(ee_root) if ee_root else None):
            if base is not None and (base / relative).is_file():
                files[target] = WebClassesFile(str(base / relative), target)
    return list(files.values())


def collect_changed_web_classes_files(zsvirt_root: str, ee_root: str | None = None) -> list[WebClassesFile]:
    ee_root = ee_root or os.path.join(zsvirt_root, "zsvirt-ee")
    main_paths: list[str] = []
    if is_git_worktree(zsvirt_root):
        main_paths = _dedupe(
            changed_paths_from_worktree(zsvirt_root) + changed_paths_from_head_commit(zsvirt_root)
        )
    ee_paths: list[str] = []
    if os.path.isdir(ee_root) and is_git_worktree(ee_root):
        ee_paths = _dedupe(
            changed_paths_from_worktree(ee_root) + changed_paths_from_head_commit(ee_root)
        )
    return collect_web_classes_files(zsvirt_root, main_paths, ee_paths, ee_root)


def collect_explicit_web_classes_files(
    zsvirt_root: str,
    ee_root: str | None,
    paths: list[str] | None,
) -> list[WebClassesFile]:
    if not paths:
        return []

    zsvirt_base = Path(zsvirt_root).resolve()
    ee_base = Path(ee_root).resolve() if ee_root else None
    out: dict[str, WebClassesFile] = {}

    for raw_path in paths:
        value = str(raw_path or "").strip()
        if not value:
            continue

        repo_base = zsvirt_base
        if value.startswith("zsvirt:"):
            value = value[len("zsvirt:"):]
            repo_base = zsvirt_base
        elif value.startswith("ee:"):
            value = value[len("ee:"):]
            if not ee_base:
                raise CompileDeployStateError("explicit ee web class requires ee root")
            repo_base = ee_base

        source = Path(value)
        if not source.is_absolute():
            source = repo_base / value
        source = source.resolve()

        zsvirt_relative = _relative_to_root(source, zsvirt_base)
        ee_relative = _relative_to_root(source, ee_base) if ee_base else None
        source_relative = ee_relative or zsvirt_relative
        if source_relative is None:
            raise CompileDeployStateError("explicit web class is outside zsvirt/ee roots: %s" % raw_path)
        prefix = "premium/" + SPRING_CONFIG_PREFIX if source_relative.startswith("premium/") else SPRING_CONFIG_PREFIX
        if not source_relative.startswith(prefix):
            raise CompileDeployStateError("explicit web class must be under conf/springConfigXml/: %s" % raw_path)
        if not source.is_file():
            raise CompileDeployStateError("explicit web class source is missing: %s" % source)

        target = source_relative[len(prefix):].strip("/")
        if not target:
            raise CompileDeployStateError("explicit web class target is empty: %s" % raw_path)
        relative_path = f"springConfigXml/{target}"
        out[relative_path] = WebClassesFile(str(source), relative_path)

    return list(out.values())


_JAVA_SCAN_SKIP_DIRS = frozenset(
    (".git", ".idea", ".gradle", "target", "node_modules", "__pycache__")
)
_JAVA_PACKAGE_RE = re.compile(r"(?m)^\s*package\s+([A-Za-z_][\w.]*)\s*;")
_JAVA_INTERFACE_RE = re.compile(r"\binterface\s+([A-Za-z_]\w*)\b")


def _read_java_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _java_package(source: str) -> str:
    match = _JAVA_PACKAGE_RE.search(source)
    return match.group(1) if match else ""


def _java_interfaces_from_changed_paths(
    repo_root: str,
    rel_paths: list[str],
) -> list[JavaInterfaceChange]:
    interfaces: list[JavaInterfaceChange] = []
    seen: set[str] = set()
    root = Path(repo_root)
    for rel_path in rel_paths:
        normalized = str(rel_path).replace("\\", "/")
        if not normalized.endswith(".java"):
            continue
        path = root / normalized
        if not path.is_file():
            continue
        source = _read_java_source(path)
        if not source:
            continue
        package = _java_package(source)
        for match in _JAVA_INTERFACE_RE.finditer(source):
            interface = JavaInterfaceChange(match.group(1), package)
            if interface.fqn in seen:
                continue
            seen.add(interface.fqn)
            interfaces.append(interface)
    return interfaces


def _java_implements_interface(source: str, interface: JavaInterfaceChange) -> bool:
    fqn_pattern = re.escape(interface.fqn)
    simple_pattern = re.escape(interface.name)
    if re.search(rf"\bimplements\b[^\{{;]*\b{fqn_pattern}\b", source, re.DOTALL):
        return True
    if not re.search(rf"\bimplements\b[^\{{;]*\b{simple_pattern}\b", source, re.DOTALL):
        return False

    if re.search(rf"(?m)^\s*import\s+{fqn_pattern}\s*;", source):
        return True
    if interface.package and re.search(
        rf"(?m)^\s*import\s+{re.escape(interface.package)}\.\*\s*;",
        source,
    ):
        return True
    return _java_package(source) == interface.package


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _iter_java_files(root: str, excluded_roots: list[str] | None = None):
    root_path = Path(root)
    excluded = [Path(p).resolve() for p in (excluded_roots or [])]
    for dirpath, dirnames, filenames in os.walk(root_path):
        current = Path(dirpath).resolve()
        if any(_is_under(current, excluded_root) for excluded_root in excluded):
            dirnames[:] = []
            continue
        dirnames[:] = [
            dirname for dirname in dirnames
            if dirname not in _JAVA_SCAN_SKIP_DIRS
            and not any(_is_under((Path(dirpath) / dirname).resolve(), excluded_root) for excluded_root in excluded)
        ]
        for filename in filenames:
            if filename.endswith(".java"):
                yield Path(dirpath) / filename


def _modules_implementing_interfaces(
    repo_root: str,
    interfaces: list[JavaInterfaceChange],
    excluded_roots: list[str] | None = None,
    excluded_modules: Collection[str] = DEPLOY_AUTO_EXCLUDED_MODULES,
) -> list[str]:
    if not interfaces or not os.path.isdir(repo_root):
        return []
    modules: list[str] = []
    root = Path(repo_root)
    for path in _iter_java_files(repo_root, excluded_roots):
        source = _read_java_source(path)
        if not source or "implements" not in source:
            continue
        if not any(_java_implements_interface(source, interface) for interface in interfaces):
            continue
        rel_path = path.relative_to(root).as_posix()
        module = module_for_changed_path(repo_root, rel_path, excluded_modules)
        if module:
            modules.append(module)
    return _dedupe(modules)


def infer_interface_implementation_modules(
    zsvirt_root: str,
    external_root: str | None,
    main_paths: list[str],
    external_paths: list[str],
    excluded_modules: Collection[str] = DEPLOY_AUTO_EXCLUDED_MODULES,
) -> tuple[list[str], list[str]]:
    interfaces = _java_interfaces_from_changed_paths(zsvirt_root, main_paths)
    if external_root and os.path.isdir(external_root):
        interfaces.extend(_java_interfaces_from_changed_paths(external_root, external_paths))
    interfaces = _dedupe(interfaces)
    if not interfaces:
        return [], []

    excluded_from_main: list[str] = []
    if external_root and os.path.isdir(external_root):
        main_root = Path(zsvirt_root).resolve()
        external_path = Path(external_root).resolve()
        if _is_under(external_path, main_root):
            excluded_from_main.append(str(external_path))

    main = _modules_implementing_interfaces(
        zsvirt_root,
        interfaces,
        excluded_from_main,
        excluded_modules,
    )
    external: list[str] = []
    if external_root and os.path.isdir(external_root):
        external = _modules_implementing_interfaces(
            external_root,
            interfaces,
            excluded_modules=excluded_modules,
        )
    return _dedupe(main), _dedupe(external)


def auto_detect_modules(
    zsvirt_root: str,
    external_root: str | None = None,
    excluded_modules: Collection[str] = DEPLOY_AUTO_EXCLUDED_MODULES,
) -> tuple[list[str], list[str]]:
    external_root = external_root or os.path.join(zsvirt_root, "zsvirt-ee")
    main_worktree_paths = changed_paths_from_worktree(zsvirt_root)
    external_worktree_paths: list[str] = []
    if os.path.isdir(external_root):
        external_worktree_paths = changed_paths_from_worktree(external_root)
    main, external = modules_from_changed_paths(
        zsvirt_root,
        main_worktree_paths,
        external_worktree_paths,
        external_root,
        excluded_modules,
    )

    main_paths = changed_paths_from_head_commit(zsvirt_root)
    external_paths: list[str] = []
    if os.path.isdir(external_root):
        external_paths = changed_paths_from_head_commit(external_root)
    head_main, head_external = modules_from_changed_paths(
        zsvirt_root,
        main_paths,
        external_paths,
        external_root,
        excluded_modules,
    )
    inferred_main, inferred_external = infer_interface_implementation_modules(
        zsvirt_root,
        external_root,
        _dedupe(main_worktree_paths + main_paths),
        _dedupe(external_worktree_paths + external_paths),
        excluded_modules,
    )
    return _dedupe(main + head_main + inferred_main), _dedupe(external + head_external + inferred_external)


def _normalize_ee_module(module: str) -> str:
    module = module.strip().replace("\\", "/").strip("/")
    if module.startswith("zsvirt-ee/"):
        module = module[len("zsvirt-ee/"):]
    return module.strip("/")


def maven_build_plan(main_mods: list[str], external_mods: list[str]) -> MavenBuildPlan:
    ee = [_normalize_ee_module(m) for m in external_mods]
    ee = [m for m in ee if m]
    modules = list(main_mods)
    modules.extend(f"zsvirt-ee/{m}" for m in ee)
    return MavenBuildPlan(
        modules=_dedupe(modules),
        profiles=["ee"],
    )


def _maven_pl_lines(grouped: dict) -> tuple[str, str]:
    return (
        ",".join(grouped["main"]) or "(none)",
        ",".join(grouped["ee"]) or "(none)",
    )


def _read_maven_main_artifact(target: Path) -> str | None:
    props_file = target / "maven-archiver" / "pom.properties"
    if not props_file.is_file():
        return None

    props: dict[str, str] = {}
    for line in props_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()

    artifact_id = props.get("artifactId")
    version = props.get("version")
    if not artifact_id or not version:
        return None

    jar = target / f"{artifact_id}-{version}.jar"
    if jar.is_file():
        return str(jar)

    LOG.warning("Maven main artifact metadata found but jar is missing: %s", jar)
    return None


def _artifact_jars(module_dir: Path) -> list[str]:
    target = module_dir / "target"
    if not target.is_dir():
        return []
    main_artifact = _read_maven_main_artifact(target)
    if main_artifact:
        return [main_artifact]

    out: list[str] = []
    for p in sorted(target.glob("*.jar")):
        name = p.name
        if name.startswith("original-"):
            continue
        if any(name.endswith(s) for s in _SKIP_JAR_SUFFIXES):
            continue
        out.append(str(p))
    if len(out) > 1:
        LOG.warning("Multiple deployable jar candidates found under %s: %s", target, out)
    return out


def collect_built_jars(
    zsvirt_root: str,
    main_mods: list[str],
    external_mods: list[str],
    ee_root: str | None = None,
) -> list[str]:
    root = Path(zsvirt_root)
    jars: list[str] = []
    for m in main_mods:
        jars.extend(_artifact_jars(root / m))
    pr = Path(ee_root) if ee_root else root / "zsvirt-ee"
    for m in external_mods:
        jars.extend(_artifact_jars(pr / m))
    by_base: dict[str, str] = {}
    for j in jars:
        by_base[os.path.basename(j)] = j
    return list(by_base.values())


def _stage_web_classes_archive(local_copy_root: str, files: list[WebClassesFile]) -> str | None:
    if not files:
        return None
    stage_root = Path(local_copy_root) / "web-classes"
    archive = Path(local_copy_root) / "web-classes.tar.gz"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)
    for item in files:
        target = stage_root / item.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.source, target)
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(stage_root.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(stage_root).as_posix())
    return str(archive)


def _remote_classes_from_lib(remote_lib: str) -> str:
    return posixpath.join(posixpath.dirname(remote_lib.rstrip("/")), "classes")


def _run_shell(runner, script: str) -> int:
    r = runner.run_command(["bash", "-lc", script], cmd_purge_output=False)
    return getattr(r, "returncode", 1) or 0


def _docker_env_prefix(docker_host: str) -> str:
    docker_host = _normalize_docker_host(docker_host)
    if not docker_host:
        return ""
    return f"DOCKER_HOST={shlex.quote(docker_host)} "


def _docker_shell(runner, docker_host: str, args: list[str]) -> int:
    command = "docker " + " ".join(shlex.quote(arg) for arg in args)
    return _run_shell(runner, _docker_env_prefix(docker_host) + command)


def _docker_rm_container(runner, docker_host: str, container_name: str) -> int:
    command = (
        f"{_docker_env_prefix(docker_host)}docker rm -f "
        f"{shlex.quote(container_name)} >/dev/null 2>&1 || true"
    )
    return _run_shell(runner, command)


def _docker_cp_from_container(
    runner,
    docker_host: str,
    container_name: str,
    source_dir: str,
    dest_dir: str,
) -> int:
    return _docker_shell(
        runner,
        docker_host,
        ["cp", f"{container_name}:{source_dir}", dest_dir],
    )


def _local_jar_copy_root_for_root(root: str) -> str:
    root_name = _safe_name_token(os.path.basename(os.path.realpath(root)))
    return tempfile.mkdtemp(prefix=f"cbok-zsv-jars-{root_name}-")


def _docker_sync_target_lines(
        plan: MavenBuildPlan,
        work_zsvirt: str,
        work_ee: str,
        out_root: str = "/out",
) -> str:
    lines: list[str] = []
    for module in plan.modules:
        if module.startswith("zsvirt-ee/"):
            lines.append(
                f"sync_target {shlex.quote(work_ee)} {shlex.quote(out_root + '/ee')} "
                f"{shlex.quote(module[len('zsvirt-ee/'):])}"
            )
        else:
            lines.append(
                f"sync_target {shlex.quote(work_zsvirt)} {shlex.quote(out_root + '/zsvirt')} {shlex.quote(module)}"
            )
    return "\n".join(lines)


def _docker_sync_target_function() -> str:
    return r"""
sync_target() {
  local work_root="$1"
  local out_root="$2"
  local module="$3"
  local target="$work_root/$module/target"
  [ -d "$target" ] || return 0
  local dest="$out_root/$module/target"
  rm -rf "$dest"
  mkdir -p "$dest"

  local props="$target/maven-archiver/pom.properties"
  if [ -f "$props" ]; then
    local artifact_id version jar
    artifact_id=$(awk -F= '$1 == "artifactId" {print $2}' "$props" | tail -n1)
    version=$(awk -F= '$1 == "version" {print $2}' "$props" | tail -n1)
    jar="$target/${artifact_id}-${version}.jar"
    if [ -n "$artifact_id" ] && [ -n "$version" ] && [ -f "$jar" ]; then
      mkdir -p "$dest/maven-archiver"
      cp "$props" "$dest/maven-archiver/pom.properties"
      cp "$jar" "$dest/"
      return 0
    fi
  fi

  find "$target" -maxdepth 1 -type f -name '*.jar' \
    ! -name 'original-*' \
    ! -name '*-sources.jar' \
    ! -name '*-javadoc.jar' \
    ! -name '*-tests.jar' \
    ! -name '*-fat.jar' \
    ! -name '*-all.jar' \
    ! -name '*-with-dependencies.jar' \
    ! -name '*-shaded.jar' \
    -exec cp {} "$dest/" \;
}
"""


def run_mvn_in_remote_docker(
    zsvirt_root: str,
    ee_root: str | None,
    plan: MavenBuildPlan,
    remote: RemoteDockerCompileConfig,
    local_jar_copy_root: str,
    runner,
    pr_refs=(),
) -> int:
    if not plan.modules:
        return 0

    docker_host = _normalize_docker_host(remote.docker_host)
    mvn_cmd = ["mvn"]
    if plan.profiles:
        mvn_cmd.append("-P" + ",".join(plan.profiles))
    mvn_cmd.extend(["-DskipTests", "clean", "install", "-pl", ",".join(plan.modules)])
    mvn_inner = " ".join(shlex.quote(c) for c in mvn_cmd)

    workdir = remote.workdir or "/work"
    spec = _compile_worktree_spec(
        zsvirt_root,
        ee_root,
        RemoteDockerCompileConfig(
            image=remote.image,
            platform=remote.platform,
            docker_host=docker_host,
            workdir=workdir,
            container_name=remote.container_name,
            m2_volume=remote.m2_volume,
            min_free_gb=remote.min_free_gb,
        ),
        pr_refs=pr_refs,
    )
    rc, handle = ensure_worktree_container(
        runner,
        spec,
        require_full_compile=True,
    )
    if rc != 0 or handle is None:
        return rc or 1

    work_zsvirt = handle.work_zsvirt
    work_ee = handle.work_ee
    out_root = "/tmp/cbok-zsv-out"
    sync_targets = _docker_sync_target_lines(plan, work_zsvirt, work_ee, out_root)
    compile_line = "" if handle.full_compile_ran else mvn_inner
    build_script = f"""
set -euo pipefail
rm -rf {out_root}
mkdir -p {out_root}/zsvirt {out_root}/ee
cd {shlex.quote(work_zsvirt)}
{compile_line}
{_docker_sync_target_function()}
{sync_targets}
"""

    LOG.info(
        "remote docker worktree compile on %s in %s with image %s: %s",
        docker_host,
        workdir,
        remote.image,
        "full compile already ran; syncing selected targets" if handle.full_compile_ran else mvn_inner,
    )
    rc = _docker_shell(
        runner,
        docker_host,
        ["exec", handle.container_name, "bash", "-lc", build_script],
    )
    if rc != 0:
        return rc
    local_zsvirt_jars = os.path.join(local_jar_copy_root, "zsvirt")
    local_ee_jars = os.path.join(local_jar_copy_root, "ee")
    Path(local_zsvirt_jars).mkdir(parents=True, exist_ok=True)
    Path(local_ee_jars).mkdir(parents=True, exist_ok=True)

    rc = _docker_cp_from_container(
        runner,
        docker_host,
        handle.container_name,
        f"{out_root}/zsvirt/.",
        local_zsvirt_jars,
    )
    if rc != 0:
        return rc
    if ee_root:
        rc = _docker_cp_from_container(
            runner,
            docker_host,
            handle.container_name,
            f"{out_root}/ee/.",
            local_ee_jars,
        )
        if rc != 0:
            return rc
    return 0


def print_plan(
    root: str,
    head_line: str,
    full_hash: str,
    grouped: dict,
    plan: MavenBuildPlan,
) -> None:
    print("== Git (zsvirt repo) ==")
    print(f"HEAD: {head_line}")
    if full_hash:
        print(f"Full: {full_hash}")
    g_m, g_p = _maven_pl_lines(grouped)
    print("\n== Maven -pl (auto-detected) ==")
    print("main (zsvirt/):", g_m)
    print("EE (zsvirt-ee/):", g_p)
    print("combined -pl:", ",".join(plan.modules) or "(none)")
    print("profiles:", ",".join(plan.profiles) or "(none)")
    sys.stdout.flush()


def _bash_scriptlet(expr: str) -> list[str]:
    return ["bash", "-lc", f"source scriptlet/bootstrap.sh; {expr}"]


def _safe_name_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return token or "item"


def _remote_jar_staging_for_root(root: str) -> str:
    root_name = _safe_name_token(os.path.basename(os.path.realpath(root)))
    return f"{REMOTE_JAR_STAGING}-{root_name}-{os.getpid()}"


def scriptlet_ensure_backup(address: str, remote_lib: str, runner) -> int:
    a = shlex.quote(address)
    lib = shlex.quote(remote_lib)
    r = runner.run_command(
        _bash_scriptlet(f"zsv_tomcat_lib_ensure_backup {a} {lib}"),
        cmd_purge_output=False,
    )
    return getattr(r, "returncode", 1) or 0


def scriptlet_scp_jars(address: str, remote_staging: str, local_jars: list[str], runner) -> int:
    if not local_jars:
        return 0
    parts = ["zsv_scp_jars_to_remote", shlex.quote(address), shlex.quote(remote_staging)]
    parts.extend(shlex.quote(j) for j in local_jars)
    r = runner.run_command(
        _bash_scriptlet(" ".join(parts)),
        cmd_purge_output=False,
    )
    return getattr(r, "returncode", 1) or 0


def scriptlet_install_jars(address: str, remote_staging: str, remote_lib: str, runner) -> int:
    a = shlex.quote(address)
    st = shlex.quote(remote_staging)
    lib = shlex.quote(remote_lib)
    r = runner.run_command(
        _bash_scriptlet(f"zsv_remote_install_jars_from_staging {a} {st} {lib}"),
        cmd_purge_output=False,
    )
    return getattr(r, "returncode", 1) or 0


def scriptlet_scp_web_classes_archive(address: str, remote_archive: str, local_archive: str, runner) -> int:
    if not local_archive:
        return 0
    a = shlex.quote(address)
    remote = shlex.quote(remote_archive)
    local = shlex.quote(local_archive)
    r = runner.run_command(
        _bash_scriptlet(f"zsv_scp_web_classes_archive_to_remote {a} {remote} {local}"),
        cmd_purge_output=False,
    )
    return getattr(r, "returncode", 1) or 0


def scriptlet_install_web_classes_archive(address: str, remote_archive: str, remote_classes: str, runner) -> int:
    a = shlex.quote(address)
    remote = shlex.quote(remote_archive)
    classes = shlex.quote(remote_classes)
    r = runner.run_command(
        _bash_scriptlet(f"zsv_remote_install_web_classes_archive {a} {remote} {classes}"),
        cmd_purge_output=False,
    )
    return getattr(r, "returncode", 1) or 0


def run_compile_flow(
    *,
    address: str | None,
    remote_lib: str,
    no_deploy: bool,
    zsvirt_root: str | None = None,
    ee_root: str | None = None,
    extra_web_classes: list[str] | None = None,
    pr_url: str | None = None,
    runner,
    compile_state_store=None,
) -> int:
    if not zsvirt_root:
        LOG.error("--zsvirt-root is required for remote Docker compile.")
        return 1
    root = os.path.realpath(zsvirt_root)
    pom = os.path.join(root, "pom.xml")
    if not os.path.isfile(pom):
        LOG.error("Not a ZStack Maven root (missing pom.xml): %s", root)
        return 1

    remote_docker = remote_docker_compile_from_conf()
    try:
        pr_refs = parse_worktree_pr_refs(pr_url or "")
    except ValueError as exc:
        LOG.error("%s", exc)
        return 1
    if not remote_docker.docker_host:
        LOG.error("remote Docker compile requires [zsv_compile] remote_docker_host.")
        return 1
    if not ee_root:
        LOG.error("--ee-root is required for remote Docker compile.")
        return 1
    ee_real_root = os.path.realpath(ee_root)
    if not ee_real_root:
        LOG.error("Remote Docker compile requires ee source for ./runMavenProfile ee.")
        return 1
    if not os.path.isdir(ee_real_root):
        LOG.error("ee root is not a directory: %s", ee_real_root)
        return 1
    if ee_real_root in (root, os.path.realpath(os.path.join(root, "premium"))):
        LOG.error("--ee-root must point to the independent zsvirt-ee checkout, not the main repository or its premium directory.")
        return 1
    if not validate_same_branch(root, ee_real_root):
        return 1
    if not zsv_base_ref.check_worktree_clean(root):
        return 1
    if not zsv_base_ref.check_worktree_clean(ee_real_root):
        return 1
    if not zsv_base_ref.rebase_worktree(root):
        return 1
    if not zsv_base_ref.rebase_worktree(ee_real_root):
        return 1

    user_main, user_ee = auto_detect_modules(root, ee_real_root)
    try:
        web_classes_files = _dedupe_web_classes_files(
            collect_explicit_web_classes_files(root, ee_real_root, extra_web_classes) +
            collect_changed_web_classes_files(root, ee_real_root)
        )
    except CompileDeployStateError as exc:
        LOG.error("%s", exc)
        return 1
    current_selection: CompileDeploySelection | None = None
    state_store = None
    worktree_key = ""
    if not no_deploy:
        try:
            worktree_key = compile_worktree_key(root, ee_real_root, remote_docker)
            state_store = compile_state_store or default_compile_deploy_state_store()
            previous_selection = state_store.load_selection(worktree_key)
            current_selection = current_compile_deploy_selection(
                user_main,
                user_ee,
                web_classes_files,
                root,
                ee_real_root,
            )
            merged_selection, web_classes_files = merge_compile_deploy_selection(
                current_selection,
                previous_selection,
                root,
                ee_real_root,
            )
            user_main = merged_selection.main_modules
            user_ee = merged_selection.ee_modules
        except CompileDeployStateError as exc:
            LOG.error("%s", exc)
            return 1
    if not user_main and not user_ee and not web_classes_files:
        LOG.error("No changed Maven modules or deployable web classes found from current HEAD commit.")
        return 1

    grouped = {
        "main": list(user_main),
        "ee": list(user_ee),
    }
    plan = maven_build_plan(grouped["main"], grouped["ee"])
    head_line, full_hash = git_summary(root)
    print_plan(root, head_line, full_hash, grouped, plan)

    if grouped["ee"]:
        if not ee_real_root:
            LOG.error("EE modules requested but ee source is not a directory.")
            return 1

    local_jar_copy_root = _local_jar_copy_root_for_root(root)
    print(f"\n== Local JAR copy dir ==\n{local_jar_copy_root}")

    rc = run_mvn_in_remote_docker(
        root,
        ee_real_root,
        plan,
        remote_docker,
        local_jar_copy_root,
        runner,
        pr_refs=pr_refs,
    )
    if rc != 0:
        return rc

    local_zsvirt_jars = os.path.join(local_jar_copy_root, "zsvirt")
    local_ee_jars = os.path.join(local_jar_copy_root, "ee")
    jars = collect_built_jars(
        local_zsvirt_jars,
        grouped["main"],
        grouped["ee"],
        local_ee_jars,
    )
    if not jars:
        LOG.warning("Build finished but no JARs found under target/ for selected modules.")
    print("\n== Built JARs to sync ==")
    for j in jars:
        print(j)
    print("\n== Web classes to sync ==")
    for item in web_classes_files:
        print(f"{item.source} -> WEB-INF/classes/{item.relative_path}")
    web_classes_archive = _stage_web_classes_archive(local_jar_copy_root, web_classes_files)

    if no_deploy:
        print("\n(no-deploy) skipping remote backup and copy.")
        return 0

    if not address:
        LOG.error("Deploy requires --address.")
        return 1

    remote_staging = _remote_jar_staging_for_root(root)
    if jars:
        rc = scriptlet_ensure_backup(address, remote_lib, runner)
        if rc != 0:
            return rc
        rc = scriptlet_scp_jars(address, remote_staging, jars, runner)
        if rc != 0:
            return rc
        rc = scriptlet_install_jars(address, remote_staging, remote_lib, runner)
        if rc != 0:
            return rc
    if web_classes_archive:
        remote_archive = posixpath.join(remote_staging, "web-classes.tar.gz")
        rc = scriptlet_scp_web_classes_archive(address, remote_archive, web_classes_archive, runner)
        if rc != 0:
            return rc
        rc = scriptlet_install_web_classes_archive(
            address,
            remote_archive,
            _remote_classes_from_lib(remote_lib),
            runner,
        )
        if rc != 0:
            return rc
    if state_store and current_selection is not None:
        try:
            state_store.save_selection(worktree_key, root, ee_real_root, current_selection)
        except CompileDeployStateError as exc:
            LOG.error("%s", exc)
            return 1
    print(f"\nWARNING: compile finished but MN has not been restarted. Run: cbok zsv restart_mn --address {address}")
    return 0
