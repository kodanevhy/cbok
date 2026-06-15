"""
ZStack: build changed modules under $Workspace/Cursor/zs/zstack, deploy JARs.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cbok import settings


LOG = logging.getLogger(__name__)

DEFAULT_REMOTE_LIB = (
    "/usr/local/zstack/apache-tomcat/webapps/zstack/WEB-INF/lib"
)
DEFAULT_DOCKER_ZSTACK_ROOT = "/root/zstack"
REMOTE_JAR_STAGING = "/tmp/cbok-zsv-compile-jars"

_SKIP_JAR_SUFFIXES = (
    "-sources.jar",
    "-javadoc.jar",
    "-tests.jar",
)
_AUTO_EXCLUDED_MODULES = frozenset(
    ("test", "testlib", "test-premium", "testlib-premium")
)


@dataclass(frozen=True)
class MavenBuildPlan:
    modules: list[str]
    profiles: list[str]


def default_zstack_root() -> str:
    return os.path.join(settings.Workspace, "Cursor", "zs", "zstack")


def zstack_root_from_workspace() -> str:
    return os.path.realpath(default_zstack_root())


_DOCKER_DISABLED = frozenset(
    ("", "none", "-", "disabled", "off", "false", "0"),
)


def docker_compile_from_conf() -> tuple[str | None, str]:
    """
    Read [zsv_compile] from cbok.conf.

    Returns (docker_container_id_or_name, zstack_root_inside_container).
    """
    conf = settings.CONF
    if not conf.has_section("zsv_compile"):
        return None, DEFAULT_DOCKER_ZSTACK_ROOT
    raw = conf.get("zsv_compile", "docker_container").strip()
    if raw.lower() in _DOCKER_DISABLED:
        return None, DEFAULT_DOCKER_ZSTACK_ROOT
    root = (
        conf.get("zsv_compile", "docker_zstack_root").strip()
        or DEFAULT_DOCKER_ZSTACK_ROOT
    )
    return raw, root


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
) -> tuple[list[str], list[str]]:
    main: list[str] = []
    for path in main_paths:
        module = module_for_changed_path(zstack_root, path)
        if module:
            main.append(module)

    premium: list[str] = []
    premium_root = os.path.join(zstack_root, "premium")
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


def auto_detect_modules(zstack_root: str) -> tuple[list[str], list[str]]:
    main_paths = changed_paths_from_head_commit(zstack_root)
    premium_root = os.path.join(zstack_root, "premium")
    premium_paths: list[str] = []
    if os.path.isdir(premium_root):
        premium_paths = changed_paths_from_head_commit(premium_root)
    return modules_from_changed_paths(zstack_root, main_paths, premium_paths)


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


def _artifact_jars(module_dir: Path) -> list[str]:
    target = module_dir / "target"
    if not target.is_dir():
        return []
    out: list[str] = []
    for p in sorted(target.glob("*.jar")):
        name = p.name
        if any(name.endswith(s) for s in _SKIP_JAR_SUFFIXES):
            continue
        out.append(str(p))
    return out


def collect_built_jars(
    zstack_root: str,
    main_mods: list[str],
    prem_mods: list[str],
) -> list[str]:
    root = Path(zstack_root)
    jars: list[str] = []
    for m in main_mods:
        jars.extend(_artifact_jars(root / m))
    pr = root / "premium"
    for m in prem_mods:
        jars.extend(_artifact_jars(pr / m))
    by_base: dict[str, str] = {}
    for j in jars:
        by_base[os.path.basename(j)] = j
    return list(by_base.values())


def run_mvn(
    cwd: str,
    modules: list[str],
    runner,
    *,
    profiles: list[str] | None = None,
    docker_container: str | None = None,
) -> int:
    if not modules:
        return 0
    profiles = profiles or []
    cmd = ["mvn"]
    if profiles:
        cmd.append("-P" + ",".join(profiles))
    cmd.extend(["-DskipTests", "clean", "install", "-pl", ",".join(modules)])
    inner = " ".join(shlex.quote(c) for c in cmd)
    if docker_container:
        cmd = [
            "docker", "exec", "-w", cwd, docker_container, "bash", "-lc", inner,
        ]
        LOG.info("docker exec -w %s %s: %s", cwd, docker_container, inner)
        r = runner.run_command(cmd, cmd_purge_output=False)
    else:
        LOG.info("Running in %s: %s", cwd, " ".join(shlex.quote(c) for c in cmd))
        r = runner.run_command(cmd, cwd=cwd, cmd_purge_output=False)
    return getattr(r, "returncode", 1) or 0


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


def scriptlet_ensure_backup(address: str, remote_lib: str, runner) -> int:
    a = shlex.quote(address)
    lib = shlex.quote(remote_lib)
    r = runner.run_command(
        _bash_scriptlet(f"zsv_tomcat_lib_ensure_backup {a} {lib}"),
        cmd_purge_output=False,
    )
    return getattr(r, "returncode", 1) or 0


def scriptlet_scp_jars(address: str, local_jars: list[str], runner) -> int:
    if not local_jars:
        return 0
    parts = ["zsv_scp_jars_to_remote", shlex.quote(address), shlex.quote(REMOTE_JAR_STAGING)]
    parts.extend(shlex.quote(j) for j in local_jars)
    r = runner.run_command(
        _bash_scriptlet(" ".join(parts)),
        cmd_purge_output=False,
    )
    return getattr(r, "returncode", 1) or 0


def scriptlet_install_jars(address: str, remote_lib: str, runner) -> int:
    a = shlex.quote(address)
    st = shlex.quote(REMOTE_JAR_STAGING)
    lib = shlex.quote(remote_lib)
    r = runner.run_command(
        _bash_scriptlet(f"zsv_remote_install_jars_from_staging {a} {st} {lib}"),
        cmd_purge_output=False,
    )
    return getattr(r, "returncode", 1) or 0


def run_compile_flow(
    *,
    address: str | None,
    remote_lib: str,
    no_deploy: bool,
    zstack_root: str | None = None,
    docker_container_override: str | None = None,
    docker_zstack_root_override: str | None = None,
    runner,
) -> int:
    root = os.path.realpath(zstack_root) if zstack_root else zstack_root_from_workspace()
    pom = os.path.join(root, "pom.xml")
    if not os.path.isfile(pom):
        LOG.error("Not a ZStack Maven root (missing pom.xml): %s", root)
        return 1

    user_main, user_prem = auto_detect_modules(root)
    if not user_main and not user_prem:
        LOG.error("No changed Maven modules found from current HEAD commit.")
        return 1

    grouped = {
        "main": list(user_main),
        "premium": list(user_prem),
    }
    plan = maven_build_plan(grouped["main"], grouped["premium"])

    conf_docker_container, conf_docker_root = docker_compile_from_conf()
    if docker_container_override is None:
        docker_container = conf_docker_container
    elif docker_container_override.strip().lower() in _DOCKER_DISABLED:
        docker_container = None
    else:
        docker_container = docker_container_override.strip()
    docker_root_raw = docker_zstack_root_override or conf_docker_root
    docker_root = docker_root_raw.strip().rstrip("/")
    if not docker_root:
        docker_root = DEFAULT_DOCKER_ZSTACK_ROOT
    if not docker_root.startswith("/"):
        docker_root = "/" + docker_root

    head_line, full_hash = git_summary(root)
    print_plan(root, head_line, full_hash, grouped, plan)

    prem_host = os.path.join(root, "premium")
    if grouped["premium"] and not (docker_container or os.path.isdir(prem_host)):
        LOG.error(
            "Premium modules requested but %s is not a directory (and no Docker). "
            "Use [zsv_compile] docker_container or clone premium/.",
            prem_host,
        )
        return 1

    build_cwd = docker_root if docker_container else root
    rc = run_mvn(
        build_cwd, plan.modules, runner,
        profiles=plan.profiles,
        docker_container=docker_container,
    )
    if rc != 0:
        return rc

    if docker_container:
        LOG.info(
            "Collecting JARs from local tree %s (use the same checkout mounted in %s).",
            root, docker_container,
        )
    jars = collect_built_jars(root, grouped["main"], grouped["premium"])
    if not jars:
        LOG.warning("Build finished but no JARs found under target/ for selected modules.")
    print("\n== Built JARs to sync ==")
    for j in jars:
        print(j)

    if no_deploy:
        print("\n(no-deploy) skipping remote backup and copy.")
        return 0

    if not address:
        LOG.error("Deploy requires --address.")
        return 1

    rc = scriptlet_ensure_backup(address, remote_lib, runner)
    if rc != 0:
        return rc
    rc = scriptlet_scp_jars(address, jars, runner)
    if rc != 0:
        return rc
    rc = scriptlet_install_jars(address, remote_lib, runner)
    return rc
