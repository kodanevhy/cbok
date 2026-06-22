"""
ZStack: build changed modules from explicit zstack/premium worktree roots.
"""
from __future__ import annotations

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

from cbok import settings
from cbok.bbx.zsv.worktree_container import WorktreeContainerSpec
from cbok.bbx.zsv.worktree_container import ensure_worktree_container


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
_AUTO_EXCLUDED_MODULES = frozenset(
    ("test", "testlib", "test-premium", "testlib-premium")
)
MAVEN_PROFILE_PREPARE_CMD = "./runMavenProfile premium"
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


@dataclass(frozen=True)
class WebClassesFile:
    source: str
    relative_path: str


@dataclass(frozen=True)
class JavaInterfaceChange:
    name: str
    package: str

    @property
    def fqn(self) -> str:
        return f"{self.package}.{self.name}" if self.package else self.name


def default_zstack_root() -> str:
    return os.path.join(settings.Workspace, "Cursor", "zs", "zstack")


def zstack_root_from_workspace() -> str:
    return os.path.realpath(default_zstack_root())


_DOCKER_DISABLED = frozenset(
    ("", "none", "-", "disabled", "off", "false", "0"),
)


def _conf_get(section: str, option: str, default: str) -> str:
    conf = settings.CONF
    if conf.has_section(section) and conf.has_option(section, option):
        return conf.get(section, option).strip()
    return default


def _normalize_docker_host(raw: str | None) -> str:
    host = (raw or "").strip()
    if host.startswith("http://"):
        return "tcp://" + host[len("http://"):]
    if host.startswith("https://"):
        return "tcp://" + host[len("https://"):]
    return host


def remote_docker_compile_from_conf(container_name: str) -> RemoteDockerCompileConfig:
    return RemoteDockerCompileConfig(
        image=_conf_get("zsv_compile", "remote_docker_image", "registry.docker.zstack.io:80/buildbin:debug7"),
        platform=_conf_get("zsv_compile", "remote_docker_platform", "linux/amd64"),
        docker_host=_normalize_docker_host(_conf_get("zsv_compile", "remote_docker_host", "")),
        workdir=_conf_get("zsv_compile", "remote_docker_workdir", "/work").rstrip("/"),
        container_name=container_name.strip(),
        m2_volume=_conf_get("zsv_compile", "remote_docker_m2_volume", "zsv-m2"),
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


def validate_same_branch(zstack_root: str, premium_root: str) -> bool:
    zstack_branch = git_branch_name(zstack_root)
    premium_branch = git_branch_name(premium_root)
    if not zstack_branch or not premium_branch:
        return True
    if zstack_branch == premium_branch:
        return True

    LOG.error(
        "zstack and premium branch names must be the same (zstack: %s, premium: %s)",
        zstack_branch,
        premium_branch,
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


def _is_auto_excluded(module: str) -> bool:
    head = module.split("/", 1)[0]
    return head in _AUTO_EXCLUDED_MODULES


def module_for_changed_path(repo_root: str, rel_path: str) -> str | None:
    path = Path(str(rel_path).replace("\\", "/"))
    if path.is_absolute() or not path.parts:
        return None

    root = Path(repo_root)
    current = root.joinpath(*path.parts)
    candidate = current if current.is_dir() else current.parent
    while candidate != root and root in candidate.parents:
        if (candidate / "pom.xml").is_file():
            module = candidate.relative_to(root).as_posix()
            if _is_auto_excluded(module):
                return None
            return module
        candidate = candidate.parent
    return None


def modules_from_changed_paths(
    zstack_root: str,
    main_paths: list[str],
    premium_paths: list[str],
    premium_root: str | None = None,
) -> tuple[list[str], list[str]]:
    main: list[str] = []
    for path in main_paths:
        module = module_for_changed_path(zstack_root, path)
        if module:
            main.append(module)

    premium: list[str] = []
    premium_root = premium_root or os.path.join(zstack_root, "premium")
    for path in premium_paths:
        module = module_for_changed_path(premium_root, path)
        if module:
            premium.append(module)

    return _dedupe(main), _dedupe(premium)


def changed_paths_from_head_commit(repo_root: str) -> list[str]:
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
        if not normalized.startswith(SPRING_CONFIG_PREFIX):
            continue
        source = root / normalized
        if not source.is_file():
            continue
        target = normalized[len(SPRING_CONFIG_PREFIX):].strip("/")
        if not target:
            continue
        files[f"springConfigXml/{target}"] = WebClassesFile(
            source=str(source),
            relative_path=f"springConfigXml/{target}",
        )
    return list(files.values())


def collect_web_classes_files(
    zstack_root: str,
    main_paths: list[str],
    premium_paths: list[str],
    premium_root: str | None = None,
) -> list[WebClassesFile]:
    files: dict[str, WebClassesFile] = {}
    for item in _web_classes_files_from_paths(zstack_root, main_paths):
        files[item.relative_path] = item
    if premium_root and os.path.isdir(premium_root):
        for item in _web_classes_files_from_paths(premium_root, premium_paths):
            files[item.relative_path] = item
    return list(files.values())


def collect_changed_web_classes_files(zstack_root: str, premium_root: str | None = None) -> list[WebClassesFile]:
    premium_root = premium_root or os.path.join(zstack_root, "premium")
    main_paths: list[str] = []
    if is_git_worktree(zstack_root):
        main_paths = _dedupe(
            changed_paths_from_worktree(zstack_root) + changed_paths_from_head_commit(zstack_root)
        )
    premium_paths: list[str] = []
    if os.path.isdir(premium_root) and is_git_worktree(premium_root):
        premium_paths = _dedupe(
            changed_paths_from_worktree(premium_root) + changed_paths_from_head_commit(premium_root)
        )
    return collect_web_classes_files(zstack_root, main_paths, premium_paths, premium_root)


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
        module = module_for_changed_path(repo_root, rel_path)
        if module:
            modules.append(module)
    return _dedupe(modules)


def infer_interface_implementation_modules(
    zstack_root: str,
    premium_root: str | None,
    main_paths: list[str],
    premium_paths: list[str],
) -> tuple[list[str], list[str]]:
    interfaces = _java_interfaces_from_changed_paths(zstack_root, main_paths)
    if premium_root and os.path.isdir(premium_root):
        interfaces.extend(_java_interfaces_from_changed_paths(premium_root, premium_paths))
    interfaces = _dedupe(interfaces)
    if not interfaces:
        return [], []

    excluded_from_main: list[str] = []
    if premium_root and os.path.isdir(premium_root):
        main_root = Path(zstack_root).resolve()
        premium_path = Path(premium_root).resolve()
        if _is_under(premium_path, main_root):
            excluded_from_main.append(str(premium_path))

    main = _modules_implementing_interfaces(zstack_root, interfaces, excluded_from_main)
    premium: list[str] = []
    if premium_root and os.path.isdir(premium_root):
        premium = _modules_implementing_interfaces(premium_root, interfaces)
    return _dedupe(main), _dedupe(premium)


def auto_detect_modules(
    zstack_root: str,
    premium_root: str | None = None,
) -> tuple[list[str], list[str]]:
    premium_root = premium_root or os.path.join(zstack_root, "premium")
    main_worktree_paths = changed_paths_from_worktree(zstack_root)
    premium_worktree_paths: list[str] = []
    if os.path.isdir(premium_root):
        premium_worktree_paths = changed_paths_from_worktree(premium_root)
    main, premium = modules_from_changed_paths(
        zstack_root,
        main_worktree_paths,
        premium_worktree_paths,
        premium_root,
    )

    main_paths = changed_paths_from_head_commit(zstack_root)
    premium_paths: list[str] = []
    if os.path.isdir(premium_root):
        premium_paths = changed_paths_from_head_commit(premium_root)
    head_main, head_premium = modules_from_changed_paths(
        zstack_root,
        main_paths,
        premium_paths,
        premium_root,
    )
    inferred_main, inferred_premium = infer_interface_implementation_modules(
        zstack_root,
        premium_root,
        _dedupe(main_worktree_paths + main_paths),
        _dedupe(premium_worktree_paths + premium_paths),
    )
    return _dedupe(main + head_main + inferred_main), _dedupe(premium + head_premium + inferred_premium)


def _normalize_premium_module(module: str) -> str:
    module = module.strip().replace("\\", "/").strip("/")
    if module.startswith("premium/"):
        module = module[len("premium/"):]
    return module.strip("/")


def maven_build_plan(main_mods: list[str], prem_mods: list[str]) -> MavenBuildPlan:
    premium = [_normalize_premium_module(m) for m in prem_mods]
    premium = [m for m in premium if m]
    modules = list(main_mods)
    modules.extend(f"premium/{m}" for m in premium)
    return MavenBuildPlan(
        modules=_dedupe(modules),
        profiles=["premium"] if premium else [],
    )


def _maven_pl_lines(grouped: dict) -> tuple[str, str]:
    return (
        ",".join(grouped["main"]) or "(none)",
        ",".join(grouped["premium"]) or "(none)",
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
    zstack_root: str,
    main_mods: list[str],
    prem_mods: list[str],
    premium_root: str | None = None,
) -> list[str]:
    root = Path(zstack_root)
    jars: list[str] = []
    for m in main_mods:
        jars.extend(_artifact_jars(root / m))
    pr = Path(premium_root) if premium_root else root / "premium"
    for m in prem_mods:
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
        work_zstack: str,
        work_premium: str,
        out_root: str = "/out",
) -> str:
    lines: list[str] = []
    for module in plan.modules:
        if module.startswith("premium/"):
            lines.append(
                f"sync_target {shlex.quote(work_premium)} {shlex.quote(out_root + '/premium')} "
                f"{shlex.quote(module[len('premium/'):])}"
            )
        else:
            lines.append(
                f"sync_target {shlex.quote(work_zstack)} {shlex.quote(out_root + '/zstack')} {shlex.quote(module)}"
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
    zstack_root: str,
    premium_root: str | None,
    plan: MavenBuildPlan,
    remote: RemoteDockerCompileConfig,
    local_jar_copy_root: str,
    runner,
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
    spec = WorktreeContainerSpec(
        zstack_root=zstack_root,
        premium_root=premium_root,
        docker_host=docker_host,
        image=remote.image,
        platform=remote.platform,
        workdir=workdir,
        container_name=remote.container_name,
        m2_volume=remote.m2_volume,
    )
    rc, handle = ensure_worktree_container(
        runner,
        spec,
        require_full_compile=True,
    )
    if rc != 0 or handle is None:
        return rc or 1

    work_zstack = handle.work_zstack
    work_premium = handle.work_premium
    out_root = "/tmp/cbok-zsv-out"
    sync_targets = _docker_sync_target_lines(plan, work_zstack, work_premium, out_root)
    build_script = f"""
set -euo pipefail
rm -rf {out_root}
mkdir -p {out_root}/zstack {out_root}/premium
cd {shlex.quote(work_zstack)}
{mvn_inner}
{_docker_sync_target_function()}
{sync_targets}
"""

    LOG.info(
        "remote docker worktree compile on %s in %s with image %s: %s",
        docker_host,
        workdir,
        remote.image,
        mvn_inner,
    )
    rc = _docker_shell(
        runner,
        docker_host,
        ["exec", handle.container_name, "bash", "-lc", build_script],
    )
    if rc != 0:
        return rc
    local_zstack_jars = os.path.join(local_jar_copy_root, "zstack")
    local_premium_jars = os.path.join(local_jar_copy_root, "premium")
    Path(local_zstack_jars).mkdir(parents=True, exist_ok=True)
    Path(local_premium_jars).mkdir(parents=True, exist_ok=True)

    rc = _docker_cp_from_container(
        runner,
        docker_host,
        handle.container_name,
        f"{out_root}/zstack/.",
        local_zstack_jars,
    )
    if rc != 0:
        return rc
    if premium_root:
        rc = _docker_cp_from_container(
            runner,
            docker_host,
            handle.container_name,
            f"{out_root}/premium/.",
            local_premium_jars,
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
    print("== Git (zstack repo) ==")
    print(f"HEAD: {head_line}")
    if full_hash:
        print(f"Full: {full_hash}")
    g_m, g_p = _maven_pl_lines(grouped)
    print("\n== Maven -pl (auto-detected) ==")
    print("main (zstack/):", g_m)
    print("premium (premium/):", g_p)
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
    zstack_root: str | None = None,
    premium_root: str | None = None,
    docker_container_override: str | None = None,
    runner,
) -> int:
    if not zstack_root:
        LOG.error("--zstack-root is required for remote Docker compile.")
        return 1
    root = os.path.realpath(zstack_root)
    pom = os.path.join(root, "pom.xml")
    if not os.path.isfile(pom):
        LOG.error("Not a ZStack Maven root (missing pom.xml): %s", root)
        return 1

    if docker_container_override is None or docker_container_override.strip().lower() in _DOCKER_DISABLED:
        LOG.error("--docker-container is required for remote Docker compile.")
        return 1
    remote_docker = remote_docker_compile_from_conf(docker_container_override)
    if not remote_docker.docker_host:
        LOG.error("remote Docker compile requires [zsv_compile] remote_docker_host.")
        return 1
    if not premium_root:
        LOG.error("--premium-root is required for remote Docker compile.")
        return 1
    remote_premium = os.path.realpath(premium_root)
    if not remote_premium:
        LOG.error("Remote Docker compile requires premium source for ./runMavenProfile premium.")
        return 1
    if not os.path.isdir(remote_premium):
        LOG.error("premium root is not a directory: %s", remote_premium)
        return 1
    if not validate_same_branch(root, remote_premium):
        return 1

    user_main, user_prem = auto_detect_modules(root, remote_premium)
    web_classes_files = collect_changed_web_classes_files(root, remote_premium)
    if not user_main and not user_prem and not web_classes_files:
        LOG.error("No changed Maven modules or deployable web classes found from current HEAD commit.")
        return 1

    grouped = {
        "main": list(user_main),
        "premium": list(user_prem),
    }
    plan = maven_build_plan(grouped["main"], grouped["premium"])
    head_line, full_hash = git_summary(root)
    print_plan(root, head_line, full_hash, grouped, plan)

    if grouped["premium"]:
        if not remote_premium:
            LOG.error("Premium modules requested but premium source is not a directory.")
            return 1

    local_jar_copy_root = _local_jar_copy_root_for_root(root)
    print(f"\n== Local JAR copy dir ==\n{local_jar_copy_root}")

    rc = run_mvn_in_remote_docker(
        root,
        remote_premium,
        plan,
        remote_docker,
        local_jar_copy_root,
        runner,
    )
    if rc != 0:
        return rc

    local_zstack_jars = os.path.join(local_jar_copy_root, "zstack")
    local_premium_jars = os.path.join(local_jar_copy_root, "premium")
    jars = collect_built_jars(
        local_zstack_jars,
        grouped["main"],
        grouped["premium"],
        local_premium_jars,
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
    return 0
