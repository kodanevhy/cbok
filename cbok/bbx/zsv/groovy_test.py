from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from cbok import utils as cbok_utils
from cbok.bbx.zsv.base_ref import check_worktree_clean, rebase_worktree, sync_base_ref
from cbok.bbx.zsv.config import zsv_base_ref
from cbok.bbx.zsv.compile import RemoteDockerCompileConfig
from cbok.bbx.zsv.compile import _docker_env_prefix
from cbok.bbx.zsv.compile import _docker_rm_container
from cbok.bbx.zsv.compile import _docker_shell
from cbok.bbx.zsv.compile import _normalize_docker_host
from cbok.bbx.zsv.compile import auto_detect_modules
from cbok.bbx.zsv.compile import maven_build_plan
from cbok.bbx.zsv.compile import remote_docker_compile_from_conf
from cbok.bbx.zsv.compile import validate_changed_paths_base_ref
from cbok.bbx.zsv.worktree_container import WorktreeContainerSpec
from cbok.bbx.zsv.worktree_container import ensure_worktree_container


LOG = logging.getLogger(__name__)

FALLBACK_IMAGE = "registry.docker.zstack.io:80/buildbin:debug9-zsvirt"
MAVEN_REPO = "/var/maven/.m2/repository"
CASE_FILE_IN_CONTAINER = "/tmp/cbok-zsv-cases"
DOCKER_WORK_ROOT = "/work"
ORIGINAL_TEST_SOURCES = "target/cbok-original-test-sources"
REMOTE_RUN_SCRIPT = "/tmp/cbok-zsv-groovy-run.sh"
REMOTE_RUN_LOG = "/tmp/cbok-zsv-groovy-run.log"
REMOTE_RUN_EXIT = "/tmp/cbok-zsv-groovy-run.exit"
REMOTE_POLL_INTERVAL_SECONDS = 15
TEST_MODULES = ("test", "tests/test-simple", "tests/test-authentication", "zsvirt-ee/tests-ee/test-ee")
GROOVY_TEST_AUTO_EXCLUDED_MODULES = frozenset(module.rsplit("/", 1)[-1] for module in TEST_MODULES)
PREPARED_DB_SCHEMA_FAILURE_PATTERNS = (
    re.compile(r"Table 'zstack(?:_rest)?\.[^']+' doesn't exist", re.IGNORECASE),
    re.compile(r"Unknown database 'zstack(?:_rest)?'", re.IGNORECASE),
    re.compile(r"Unknown column '[^']+'", re.IGNORECASE),
    re.compile(r"org\.hibernate\.exception\.SQLGrammarException", re.IGNORECASE),
    re.compile(r"java\.sql\.SQLSyntaxErrorException", re.IGNORECASE),
)


CORE_HARNESS_BODY = """\
import org.zstack.core.StartMode
import org.zstack.testlib.Test

class ContainerGroovyTest extends Test {
    @Override
    void setup() {
        if (Boolean.getBoolean("cbokReuseDeployDb")) {
            DEPLOY_DB = false
        }
        API_PORTAL = false
        INCLUDE_CORE_SERVICES = false
        spring {
            include("AccountManager.xml")
            include("identity.xml")
        }
    }

    @Override
    void environment() {
    }

    @Override
    void test() {
        runSubCases()
    }

    @Override
    StartMode getCaseMode() {
        return StartMode.SIMULATOR
    }
}
"""


AUTHENTICATION_HARNESS_BODY = """\
import org.zstack.core.StartMode
import org.zstack.testlib.Test
import org.zstack.testlib.premium.PremiumEnv

class ContainerAuthenticationGroovyTest extends Test {
    @Override
    void setup() {
        if (Boolean.getBoolean("cbokReuseDeployDb")) {
            DEPLOY_DB = false
        }
        useSpring(PremiumEnv.makeSpring())
    }

    @Override
    void environment() {
    }

    @Override
    void test() {
        runSubCases()
    }

    @Override
    StartMode getCaseMode() {
        return StartMode.SIMULATOR
    }
}
"""


EE_HARNESS_BODY = """\
import org.zstack.core.StartMode
import org.zstack.testlib.ee.TestEe

class ContainerEeGroovyTest extends TestEe {
    @Override
    void setup() {
        if (Boolean.getBoolean("cbokReuseDeployDb")) {
            DEPLOY_DB = false
        }
        useSpring(makeEeSpring())
    }

    @Override
    void environment() {}

    @Override
    void test() { runSubCases() }

    @Override
    StartMode getCaseMode() { return StartMode.SIMULATOR }
}
"""


@dataclass(frozen=True)
class TestTarget:
    module: str
    mode: str
    surefire_test: str
    needs_case_file: bool
    needs_harness: bool = False
    harness_class: str = ""


def default_test_image() -> str:
    image = remote_docker_compile_from_conf().image.strip()
    return image or FALLBACK_IMAGE


def default_test_platform() -> str:
    return remote_docker_compile_from_conf().platform.strip()


def default_test_docker_host() -> str:
    return remote_docker_compile_from_conf().docker_host.strip()


def _safe_run_id(raw: str | None = None) -> str:
    value = raw or str(int(time.time()))
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return (value or "run")[:48]


def _simple_class_name(test_class: str) -> str:
    return test_class.rsplit(".", 1)[-1].strip()


def _class_source_candidates(root: Path, test_class: str) -> list[Path]:
    if "." in test_class:
        stem = root.joinpath(Path(*test_class.split(".")))
        return [stem.with_suffix(".groovy"), stem.with_suffix(".java")]

    direct = [root / f"{test_class}.groovy", root / f"{test_class}.java"]
    matches = sorted(root.rglob(f"{test_class}.groovy")) + sorted(root.rglob(f"{test_class}.java"))
    out: list[Path] = []
    seen: set[Path] = set()
    for candidate in direct + matches:
        if candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def _class_source_file(root: Path, test_class: str) -> Path | None:
    matches = [candidate for candidate in _class_source_candidates(root, test_class) if candidate.is_file()]
    if not matches and "." in test_class:
        simple = _simple_class_name(test_class)
        fallback = sorted(root.rglob(f"{simple}.groovy")) + sorted(root.rglob(f"{simple}.java"))
        matches = [candidate for candidate in fallback if _groovy_fqcn(candidate) == test_class]
    if len(matches) == 1:
        return matches[0]
    direct_matches = [
        candidate for candidate in matches
        if candidate.parent.resolve() == root.resolve()
    ]
    if len(direct_matches) == 1:
        return direct_matches[0]
    return None


def _class_source_path(root: Path, test_class: str) -> Path:
    return _class_source_file(root, test_class) or _class_source_candidates(root, test_class)[0]


def _class_source_exists(root: Path, test_class: str) -> bool:
    return _class_source_file(root, test_class) is not None


def _source_without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    return text


def _groovy_fqcn(source: Path) -> str:
    text = _source_without_comments(source.read_text(encoding="utf-8", errors="ignore"))
    package_match = re.search(r"^\s*package\s+([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s*;?\s*$", text, re.M)
    package = package_match.group(1) if package_match else ""
    class_name = source.stem
    class_match = re.search(r"\bclass\s+([A-Za-z_][\w]*)\b", text)
    if class_match:
        class_name = class_match.group(1)
    return f"{package}.{class_name}" if package else class_name


def _source_text(source: Path | None) -> str:
    if not source or not source.is_file():
        return ""
    return source.read_text(encoding="utf-8", errors="ignore")


def _extends_name(source: Path | None) -> str:
    text = _source_without_comments(_source_text(source))
    match = re.search(r"\bclass\s+[A-Za-z_][\w]*\s+extends\s+([A-Za-z_][\w.]*)", text)
    if not match:
        return ""
    return match.group(1).rsplit(".", 1)[-1]


def _is_case_source(source: Path | None) -> bool:
    base = _extends_name(source)
    if not base:
        return False
    if base in ("SubCase", "SubCaseEe"):
        return True
    return (
        base.endswith("CaseStub")
        or base.endswith("CaseSub")
        or base.endswith("TestBase")
        or base in ("AllowedDBRemaining", "SnapShotCaseSub")
    )


def _is_direct_test_source(source: Path | None) -> bool:
    text = _source_text(source)
    base = _extends_name(source)
    if base in ("Test", "TestEe", "KvmTest", "StabilityTest", "StabilityTestEe"):
        return True
    return "@Test" in text


def _nearest_suite_class(source_root: Path, test_class: str) -> str | None:
    source = _class_source_file(source_root, test_class)
    if not source or not source.is_file():
        return None

    current = source.parent
    source_root = source_root.resolve()
    while True:
        candidates = sorted(
            p for p in list(current.glob("*Test.groovy")) + list(current.glob("*Test.java"))
            if p.is_file() and p.resolve() != source.resolve()
        )
        if candidates:
            return _groovy_fqcn(candidates[0])
        if current.resolve() == source_root:
            return None
        if source_root not in current.resolve().parents:
            return None
        current = current.parent


def _test_module_root(work_zsvirt: Path, work_ee: Path, module: str) -> Path:
    if module.startswith("zsvirt-ee/"):
        return work_ee / module.removeprefix("zsvirt-ee/")
    return work_zsvirt / module


def _find_test_module(work_zsvirt: Path, work_ee: Path, test_class: str) -> str:
    modules = TEST_MODULES
    matches = [module for module in modules
               if _class_source_exists(_test_module_root(work_zsvirt, work_ee, module) / "src/test/groovy", test_class)]
    if len(matches) > 1:
        raise ValueError(f"Test class {test_class} exists in {matches}; class must identify a unique test module")
    if len(matches) != 1:
        raise ValueError(f"Test class {test_class} not found in {modules}")
    return matches[0]


def _package_for_source_or_class(source: Path | None, test_class: str) -> str:
    fqcn = _groovy_fqcn(source) if source and source.is_file() else test_class
    if "." not in fqcn:
        return ""
    return fqcn.rsplit(".", 1)[0]


def _resolve_test_target(
        work_zsvirt: Path,
        work_ee: Path,
        test_class: str,
        test_mode: str,
) -> TestTarget:
    mode = test_mode
    module = _find_test_module(work_zsvirt, work_ee, test_class)
    source_root = _test_module_root(work_zsvirt, work_ee, module) / "src/test/groovy"
    source = _class_source_file(source_root, test_class)
    if mode == "auto":
        if _is_case_source(source):
            mode = "case"
        elif _is_direct_test_source(source) or _simple_class_name(test_class).endswith("Test"):
            mode = "suite"
        else:
            mode = "case"
    if mode == "case":
        suite_class = _nearest_suite_class(source_root, test_class)
        if suite_class:
            return TestTarget(
                module=module,
                mode=mode,
                surefire_test=_simple_class_name(suite_class),
                needs_case_file=True,
            )
        harness_package = _package_for_source_or_class(source, test_class)
        harness_class = _harness_class_for_module(module, harness_package)
        return TestTarget(
            module=module,
            mode=mode,
            surefire_test=_simple_class_name(harness_class),
            needs_case_file=True,
            needs_harness=True,
            harness_class=harness_class,
        )
    return TestTarget(
        module=module,
        mode=mode,
        surefire_test=_simple_class_name(test_class),
        needs_case_file=False,
    )


def _returncode(result) -> int:
    return getattr(result, "returncode", 1) or 0


def _run(runner, cmd: list[str], **kwargs) -> int:
    return _returncode(runner.run_command(cmd, cmd_purge_output=False, **kwargs))


def _capture(runner, cmd: list[str]) -> tuple[int, str]:
    result = runner.run_command(cmd, cmd_purge_output=False)
    return _returncode(result), (getattr(result, "stdout", "") or "").strip()


def _run_shell(runner, script: str) -> int:
    return _run(runner, ["bash", "-lc", script])


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _ensure_repo(path: str, label: str) -> bool:
    if os.path.isdir(path):
        return True
    LOG.error("%s repo is not a directory: %s", label, path)
    return False


def _create_ee_link(work_zsvirt: Path) -> None:
    link = work_zsvirt / "zsvirt-ee"
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise ValueError(f"Cannot replace existing EE directory: {link}")
    os.symlink("../zsvirt-ee", link)


def _write_harnesses(work_zsvirt: Path, work_ee: Path, target: TestTarget) -> None:
    if not target.needs_harness:
        return
    harness_class = _harness_class(target)
    harness_path = Path(*harness_class.split(".")).with_suffix(".groovy")
    package = harness_class.rsplit(".", 1)[0] if "." in harness_class else ""
    package_line = f"package {package}\n\n" if package else ""
    body = CORE_HARNESS_BODY
    if target.module == "tests/test-authentication":
        body = AUTHENTICATION_HARNESS_BODY
    elif target.module.startswith("zsvirt-ee/"):
        body = EE_HARNESS_BODY
    _write_file(_module_source_root(work_zsvirt, work_ee, target) / harness_path, package_line + body)


def _module_source_root(work_zsvirt: Path, work_ee: Path, target: TestTarget) -> Path:
    return _module_root(work_zsvirt, work_ee, target) / "src/test/groovy"


def _module_root(work_zsvirt: Path, work_ee: Path, target: TestTarget) -> Path:
    return _test_module_root(work_zsvirt, work_ee, target.module)


def _harness_class(target: TestTarget) -> str:
    return target.harness_class or _harness_class_for_module(target.module)


def _harness_class_for_module(module: str, package: str = "org.zstack.test.integration") -> str:
    prefix = f"{package}." if package else ""
    if module == "tests/test-authentication":
        return f"{prefix}ContainerAuthenticationGroovyTest"
    if module.startswith("zsvirt-ee/"):
        return f"{prefix}ContainerEeGroovyTest"
    return f"{prefix}ContainerGroovyTest"


def _local_imports(source: Path, source_root: Path) -> set[Path]:
    imports: set[Path] = set()
    if not source.is_file():
        return imports
    for line in source.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*import\s+(?!static\b)([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+)\s*$", line)
        if not match:
            continue
        candidate = source_root.joinpath(Path(*match.group(1).split(".")).with_suffix(".groovy"))
        if candidate.is_file():
            imports.add(candidate)
    return imports


def _collect_selected_sources(source_root: Path, test_class: str, target: TestTarget) -> set[Path]:
    pending = [
        _class_source_path(source_root, test_class),
        _class_source_path(source_root, _harness_class(target)),
    ]
    selected: set[Path] = set()
    while pending:
        source = pending.pop()
        if source in selected or not source.is_file():
            continue
        selected.add(source)
        pending.extend(_local_imports(source, source_root) - selected)
    return selected


def _patch_module_sources(module_root: Path, selected_root: Path) -> None:
    pom = module_root / "pom.xml"
    text = pom.read_text(encoding="utf-8")
    rel = selected_root.relative_to(module_root).as_posix()
    text = re.sub(
        r"<sourceDirectory>[^<]+</sourceDirectory>",
        f"<sourceDirectory>{rel}</sourceDirectory>",
        text,
        count=1,
    )
    text = re.sub(
        r"<testSourceDirectory>[^<]+</testSourceDirectory>",
        f"<testSourceDirectory>{rel}</testSourceDirectory>",
        text,
        count=1,
    )
    pom.write_text(text, encoding="utf-8")


def _prepare_selected_test_sources(
        work_zsvirt: Path,
        work_ee: Path,
        test_class: str,
        target: TestTarget,
) -> None:
    if not target.needs_harness:
        return
    source_root = _module_source_root(work_zsvirt, work_ee, target)
    module_root = _module_root(work_zsvirt, work_ee, target)
    selected = _collect_selected_sources(source_root, test_class, target)
    if not _class_source_path(source_root, test_class) in selected:
        raise FileNotFoundError(f"Test class source not found under {source_root}: {test_class}")
    original_root = module_root / ORIGINAL_TEST_SOURCES
    if original_root.exists():
        shutil.rmtree(original_root)
    source_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_root), str(original_root))
    source_root.mkdir(parents=True, exist_ok=True)
    for source in selected:
        rel = source.relative_to(source_root)
        target_file = source_root / rel
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original_root / rel, target_file)
    _patch_module_sources(module_root, source_root)


def _mvn_base(offline: bool = False) -> str:
    parts = ["mvn", "-Pee"]
    if offline:
        parts.append("-o")
    parts.extend([
        f"-Dmaven.repo.local={MAVEN_REPO}",
        "-Djacoco.skip=true",
        "-DskipJacoco=true",
    ])
    return " ".join(parts)


def _tool_wrapper_script() -> str:
    return """\
mkdir -p /usr/local/bin /sbin
cat >/usr/local/bin/sudo <<'EOF'
#!/bin/sh
exec "$@"
EOF
chmod +x /usr/local/bin/sudo
cat >/sbin/iptables <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x /sbin/iptables
cat >/sbin/iptables-save <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x /sbin/iptables-save
export PATH="/usr/local/bin:/sbin:$PATH"
"""


def _properties_patch_script(work_root: str = DOCKER_WORK_ROOT) -> str:
    return f"""\
patch_zstack_properties() {{
  for props in \\
    {work_root}/zsvirt/test/target/test-classes/zstack.properties \\
    {work_root}/zsvirt/tests/test-simple/target/test-classes/zstack.properties \\
    {work_root}/zsvirt/tests/test-authentication/target/test-classes/zstack.properties \\
    {work_root}/zsvirt/zsvirt-ee/tests-ee/test-ee/target/test-classes/zstack.properties
  do
    if [ -f "$props" ]; then
      sed -i \\
        -e 's|^DB.url=.*|DB.url=jdbc:mysql://localhost:3306/|' \\
        -e 's|^DB.user=.*|DB.user=root|' \\
        -e 's|^DB.password=.*|DB.password=|' \\
        "$props"
    fi
  done
}}
"""


def _ukey_patch_script(work_root: str = DOCKER_WORK_ROOT) -> str:
    return f"""\
disable_ukey_util() {{
  for util in \\
    {work_root}/zsvirt/test/target/test-classes/tools/zskey-util \\
    {work_root}/zsvirt/test/target/test-classes/tools/zskey-util-aarch64 \\
    {work_root}/zsvirt/tests/test-simple/target/test-classes/tools/zskey-util \\
    {work_root}/zsvirt/tests/test-simple/target/test-classes/tools/zskey-util-aarch64 \\
    {work_root}/zsvirt/tests/test-authentication/target/test-classes/tools/zskey-util \\
    {work_root}/zsvirt/tests/test-authentication/target/test-classes/tools/zskey-util-aarch64 \\
    {work_root}/zsvirt/zsvirt-ee/tests-ee/test-ee/target/test-classes/tools/zskey-util \\
    {work_root}/zsvirt/zsvirt-ee/tests-ee/test-ee/target/test-classes/tools/zskey-util-aarch64
  do
    rm -f "$util"
  done
}}
"""


def _mysql_script() -> str:
    return """\
start_mysql() {
  if mysqladmin ping -uroot --silent >/dev/null 2>&1; then
    setup_mysql
    return
  fi
  mkdir -p /run/mysqld
  chown -R mysql:mysql /run/mysqld /var/lib/mysql || true
  if [ ! -d /var/lib/mysql/mysql ] && command -v mysql_install_db >/dev/null 2>&1; then
    mysql_install_db --user=mysql --datadir=/var/lib/mysql >/tmp/cbok-mysql-install.log 2>&1 || cat /tmp/cbok-mysql-install.log
  fi
  mysqld_safe --datadir=/var/lib/mysql --bind-address=127.0.0.1 --skip-networking=0 >/tmp/cbok-mysqld.log 2>&1 &
  ready=
  for _ in $(seq 1 60); do
    if mysqladmin ping -uroot --silent >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [ "$ready" != "1" ]; then
    cat /tmp/cbok-mysqld.log || true
    exit 1
  fi
  setup_mysql
}

setup_mysql() {
  mysql -uroot -e "CREATE DATABASE IF NOT EXISTS zstack DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci;"
  mysql -uroot -e "GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' IDENTIFIED BY '' WITH GRANT OPTION;"
  mysql -uroot -e "GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' IDENTIFIED BY '' WITH GRANT OPTION;"
  mysql -uroot -e "GRANT ALL PRIVILEGES ON *.* TO 'root'@'localhost' IDENTIFIED BY '' WITH GRANT OPTION;"
  mysql -uroot -e "GRANT ALL PRIVILEGES ON *.* TO 'zstack'@'%' IDENTIFIED BY 'zstack';"
  mysql -uroot -e "GRANT ALL PRIVILEGES ON *.* TO 'zstack'@'localhost' IDENTIFIED BY 'zstack';"
  mysql -uroot -e "FLUSH PRIVILEGES;"
}
"""


def _surefire_command(target: TestTarget, reuse_deploy_db: bool = False) -> str:
    args = [
        _mvn_base(),
        "-DDB.url=jdbc:mysql://localhost:3306/",
        "-DDB.user=root",
        "-DDB.password=",
        "-DsurefireArgLine=",
        "-Dsurefire.useFile=false",
        "-DtrimStackTrace=false",
        f"-Dtest={target.surefire_test}",
    ]
    if reuse_deploy_db:
        args.append("-DcbokReuseDeployDb=true")
    if target.needs_case_file:
        args.extend([
            "-DsubCaseCollectionStrategy=Designated",
            f"-DcaseFilePath={CASE_FILE_IN_CONTAINER}",
        ])
    args.append("surefire:test")
    return " ".join(args)


def _test_compile_command() -> str:
    return " ".join([
        _mvn_base(),
        "-DskipTests",
        "test-compile",
    ])


def _reuse_deploy_db_patch_script(target: TestTarget, reuse_deploy_db: bool) -> str:
    if not reuse_deploy_db:
        return ""
    return f"""\
python - <<'PY'
from __future__ import print_function
import io
import os

suite = {target.surefire_test!r}
marker = 'if (Boolean.getBoolean("cbokReuseDeployDb"))'
target_name = suite + ".groovy"
for root, _dirs, files in os.walk("src/test/groovy"):
    if target_name not in files:
        continue
    path = os.path.join(root, target_name)
    with io.open(path, encoding="utf-8") as fp:
        text = fp.read()
    if marker in text:
        break
    needle = "void setup() {{"
    if needle not in text:
        break
    replacement = needle + '\\n        if (Boolean.getBoolean("cbokReuseDeployDb")) {{\\n            DEPLOY_DB = false\\n        }}'
    with io.open(path, "w", encoding="utf-8") as fp:
        fp.write(text.replace(needle, replacement, 1))
    print("patched reuse deploy DB for", path)
    break
PY
"""


def build_container_test_script(
        target: TestTarget,
        work_root: str = DOCKER_WORK_ROOT,
        reuse_deploy_db: bool = False,
) -> str:
    test_dir = f"{work_root}/zsvirt/{target.module}"
    return f"""\
set -euo pipefail
dump_failure_context() {{
  rc=$?
  if [ "$rc" != "0" ]; then
    echo "==== cbok zsv groovy_test failure context ===="
    for dir in \\
      {test_dir}/target/surefire-reports \\
      {test_dir}/zstack-integration-test-result
    do
      if [ -d "$dir" ]; then
        echo "---- files under $dir ----"
        find "$dir" -maxdepth 3 -type f -print | sort | while read -r file; do
          echo "---- $file ----"
          tail -n 240 "$file" || true
        done
      fi
    done
    for file in \\
      {test_dir}/management-server.log \\
      {test_dir}/test.log \\
      {test_dir}/zstack.log
    do
      if [ -f "$file" ]; then
        echo "---- tail $file ----"
        tail -n 300 "$file" || true
      fi
    done
    echo "==== end cbok zsv groovy_test failure context ===="
  fi
  exit "$rc"
}}
trap dump_failure_context EXIT
{_tool_wrapper_script()}
{_mysql_script()}
start_mysql
cd {test_dir}
{_reuse_deploy_db_patch_script(target, reuse_deploy_db)}
{_test_compile_command()}
{_properties_patch_script(work_root)}
patch_zstack_properties
{_ukey_patch_script(work_root)}
disable_ukey_util
{_surefire_command(target, reuse_deploy_db)}
"""


def _container_db_is_ready(runner, docker_host: str, container_name: str) -> bool:
    script = r"""mysql -uroot -N -e "
SELECT COUNT(*) FROM zstack.schema_version WHERE success = 1;
SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='zstack' AND table_name='ResourceVO';
SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='zstack_rest' AND table_name='schema_version';
" 2>/dev/null"""
    result = _docker_shell_capture(
        runner,
        docker_host,
        ["exec", container_name, "bash", "-lc", script],
    )
    if _returncode(result) != 0:
        return False
    values = [
        int(line.strip())
        for line in (result.stdout or "").splitlines()
        if line.strip().isdigit()
    ]
    return len(values) == 3 and values[0] > 100 and values[1] == 1 and values[2] == 1


def _looks_like_prepared_db_schema_failure(log_text: str) -> bool:
    if not log_text:
        return False
    return any(pattern.search(log_text) for pattern in PREPARED_DB_SCHEMA_FAILURE_PATTERNS)


def _cleanup_worktrees(
        runner,
        zsvirt_repo: str,
        ee_repo: str,
        work_zsvirt: Path,
        work_ee: Path,
        work_root: Path,
) -> None:
    _run(runner, ["git", "-C", zsvirt_repo, "worktree", "remove", "-f", str(work_zsvirt)])
    _run(runner, ["git", "-C", ee_repo, "worktree", "remove", "-f", str(work_ee)])
    shutil.rmtree(work_root, ignore_errors=True)


def _git_ref(runner, repo: str | Path, ref: str) -> str:
    rc, stdout = _capture(runner, ["git", "-C", str(repo), "rev-parse", ref])
    if rc != 0:
        return ""
    return stdout.splitlines()[-1].strip() if stdout else ""


def _worktrees_match_requested_refs(runner, metadata_path: Path, inputs: list[dict], worktrees: tuple[Path, Path]) -> bool:
    try:
        recorded = json.loads(metadata_path.read_text())
    except (OSError, ValueError):
        return False
    heads = [_git_ref(runner, worktree, "HEAD") for worktree in worktrees]
    return bool(all(heads) and recorded == {"inputs": inputs, "heads": heads})


def _reset_test_worktree(runner, target_worktree: Path) -> int:
    script = f"""
set -euo pipefail
target_worktree={shlex.quote(str(target_worktree))}
git -C "$target_worktree" reset --hard HEAD >/dev/null
git -C "$target_worktree" clean -fd >/dev/null
"""
    return _run_shell(runner, script)


def _incremental_compile_changed_modules(runner, docker_host: str, handle, work_zsvirt: Path, work_ee: Path) -> int:
    if not validate_changed_paths_base_ref(str(work_zsvirt)):
        return 1
    if work_ee.is_dir() and not validate_changed_paths_base_ref(str(work_ee)):
        return 1

    main_mods, ee_mods = auto_detect_modules(
        str(work_zsvirt),
        str(work_ee),
        excluded_modules=GROOVY_TEST_AUTO_EXCLUDED_MODULES,
    )
    plan = maven_build_plan(main_mods, ee_mods)
    if not plan.modules:
        return 0

    mvn_cmd = ["mvn"]
    if plan.profiles:
        mvn_cmd.append("-P" + ",".join(plan.profiles))
    mvn_cmd.extend(["-DskipTests", "clean", "install", "-pl", ",".join(plan.modules)])
    mvn_inner = " ".join(shlex.quote(c) for c in mvn_cmd)
    LOG.info("Running incremental compile in %s: %s", handle.container_name, mvn_inner)
    script = f"""
set -euo pipefail
cd {shlex.quote(handle.work_zsvirt)}
{mvn_inner}
"""
    return _docker_shell(
        runner,
        docker_host,
        ["exec", handle.container_name, "bash", "-lc", script],
    )


def _remove_container(runner, name: str, docker_host: str = "") -> None:
    if docker_host:
        _docker_rm_container(runner, docker_host, name)
        return
    _run_shell(runner, f"docker rm -f {shlex.quote(name)} >/dev/null 2>&1 || true")


def _docker_cp_file_to_container(
        runner,
        docker_host: str,
        source_file: Path,
        container_name: str,
        dest_file: str,
) -> int:
    command = (
        f"{_docker_env_prefix(docker_host)}docker cp "
        f"{shlex.quote(str(source_file))} "
        f"{shlex.quote(container_name)}:{shlex.quote(dest_file)}"
    )
    return _run_shell(runner, command)


def _docker_shell_capture(runner, docker_host: str, args: list[str]):
    command = "docker " + " ".join(shlex.quote(arg) for arg in args)
    return runner.run_command(
        ["bash", "-lc", _docker_env_prefix(docker_host) + command],
        cmd_purge_output=False,
    )


def _docker_cp_zsvirt_to_remote_container(
        runner,
        docker_host: str,
        source_dir: Path,
        container_name: str,
        dest_dir: str,
) -> int:
    return _docker_stream_archive_to_container(
        runner,
        docker_host,
        source_dir,
        container_name,
        dest_dir,
        exclude_ee=True,
    )


def _docker_stream_archive_to_container(
        runner,
        docker_host: str,
        source_dir: Path,
        container_name: str,
        dest_dir: str,
        *,
        exclude_ee: bool = False,
) -> int:
    ee_excludes = "--exclude zsvirt-ee --exclude ./zsvirt-ee " if exclude_ee else ""
    excludes = (
        "--exclude .git "
        "--exclude target "
        "--exclude '*/target' "
        "--exclude .idea "
        "--exclude .gradle "
        "--exclude node_modules "
        f"{ee_excludes}"
        "--exclude '._*' "
        "--exclude '*/._*' "
        "--exclude .DS_Store "
        "--exclude '*/.DS_Store' "
        "--exclude __MACOSX "
        "--exclude '*/__MACOSX'"
    )
    script = (
        f"COPYFILE_DISABLE=1 tar -C {shlex.quote(str(source_dir))} {excludes} -czf - . | "
        f"{_docker_env_prefix(docker_host)}docker exec -i "
        f"{shlex.quote(container_name)} tar -xzf - -C {shlex.quote(dest_dir)}"
    )
    return _run_shell(runner, script)


def _run_remote_container_script(
        runner,
        docker_host: str,
        container_name: str,
        local_script_file: Path,
        script: str,
        reuse_deploy_db: bool = False,
) -> int:
    _write_file(local_script_file, script)
    rc = _docker_cp_file_to_container(
        runner,
        docker_host,
        local_script_file,
        container_name,
        REMOTE_RUN_SCRIPT,
    )
    if rc != 0:
        return rc

    launch = (
        f"rm -f {REMOTE_RUN_EXIT} {REMOTE_RUN_LOG}; "
        f"chmod +x {REMOTE_RUN_SCRIPT}; "
        f"(bash {REMOTE_RUN_SCRIPT} >{REMOTE_RUN_LOG} 2>&1; "
        f"echo $? >{REMOTE_RUN_EXIT}) &"
    )
    rc = _docker_shell(
        runner,
        docker_host,
        ["exec", "-d", container_name, "bash", "-lc", launch],
    )
    if rc != 0:
        return rc

    failures = 0
    status = ""
    while not status:
        result = _docker_shell_capture(
            runner,
            docker_host,
            [
                "exec",
                container_name,
                "bash",
                "-lc",
                f"test -f {REMOTE_RUN_EXIT} && cat {REMOTE_RUN_EXIT} || true",
            ],
        )
        if _returncode(result) != 0:
            failures += 1
            if failures >= 3:
                return _returncode(result)
            time.sleep(5)
            continue
        failures = 0
        status = (result.stdout or "").strip()
        if not status:
            time.sleep(REMOTE_POLL_INTERVAL_SECONDS)

    try:
        rc = int(status.splitlines()[-1].strip())
    except (IndexError, ValueError):
        LOG.error("Invalid remote container exit status: %s", status)
        return 1
    log_lines = 800 if rc != 0 else 160
    log_result = _docker_shell_capture(
        runner,
        docker_host,
        ["exec", container_name, "bash", "-lc", f"tail -n {log_lines} {REMOTE_RUN_LOG}"],
    )
    if _returncode(log_result) != 0:
        return _returncode(log_result)

    log_text = log_result.stdout or ""
    if rc != 0:
        LOG.error("Remote container test script failed: %s", rc)
        if reuse_deploy_db and _looks_like_prepared_db_schema_failure(log_text):
            LOG.error(
                "AI hint: prepared Groovy test database may be stale or corrupted. "
                "Retry with --refresh-deploy-db to rebuild it."
            )
    return rc


def _run_remote_docker_test(
        *,
        runner,
        docker_host: str,
        runner_container: str,
        work_zsvirt: Path,
        work_ee: Path,
        case_file: Path,
        target: TestTarget,
        image: str,
        platform: str | None,
        m2_volume: str,
) -> int:
    _remove_container(runner, runner_container, docker_host)
    create_cmd = ["create", "--name", runner_container]
    if platform:
        create_cmd.extend(["--platform", platform])
    if m2_volume:
        create_cmd.extend(["-v", f"{m2_volume}:/var/maven/.m2"])
    create_cmd.extend([image, "sleep", "infinity"])

    rc = _docker_shell(runner, docker_host, create_cmd)
    if rc != 0:
        return rc
    try:
        rc = _docker_shell(runner, docker_host, ["start", runner_container])
        if rc != 0:
            return rc
        rc = _docker_shell(
            runner,
            docker_host,
            [
                "exec",
                runner_container,
                "bash",
                "-lc",
                f"mkdir -p {DOCKER_WORK_ROOT}/zsvirt {DOCKER_WORK_ROOT}/zsvirt-ee /tmp",
            ],
        )
        if rc != 0:
            return rc
        rc = _docker_cp_zsvirt_to_remote_container(
            runner,
            docker_host,
            work_zsvirt,
            runner_container,
            f"{DOCKER_WORK_ROOT}/zsvirt",
        )
        if rc != 0:
            return rc
        rc = _docker_stream_archive_to_container(
            runner,
            docker_host,
            work_ee,
            runner_container,
            f"{DOCKER_WORK_ROOT}/zsvirt-ee",
        )
        if rc != 0:
            return rc
        rc = _docker_shell(
            runner,
            docker_host,
            [
                "exec",
                runner_container,
                "bash",
                "-lc",
                f"ln -sfn ../zsvirt-ee {DOCKER_WORK_ROOT}/zsvirt/zsvirt-ee",
            ],
        )
        if rc != 0:
            return rc
        if target.needs_case_file:
            rc = _docker_cp_file_to_container(
                runner,
                docker_host,
                case_file,
                runner_container,
                CASE_FILE_IN_CONTAINER,
            )
            if rc != 0:
                return rc
        return _run_remote_container_script(
            runner,
            docker_host,
            runner_container,
            case_file.parent / "remote-run.sh",
            build_container_test_script(target),
        )
    finally:
        _remove_container(runner, runner_container, docker_host)


def _validate_inputs(test_class: str, test_mode: str) -> bool:
    if test_mode not in ("auto", "case", "suite"):
        LOG.error("Unsupported test mode: %s", test_mode)
        return False
    if test_mode == "case" and "." not in test_class:
        LOG.error("Case mode requires fully qualified --test-class, got: %s", test_class)
        return False
    return True


def run_groovy_test_flow(
        *,
        zsvirt_branch: str,
        ee_branch: str,
        test_class: str,
        test_mode: str = "auto",
        zsvirt_repo: str | None = None,
        ee_repo: str | None = None,
        work_root: str | None = None,
        image: str | None = None,
        platform: str | None = None,
        docker_host: str | None = None,
        m2_dir: str | None = None,
        run_id: str | None = None,
        keep_worktree: bool = True,
        refresh_deploy_db: bool = False,
        runner=None,
) -> int:
    if not _validate_inputs(test_class, test_mode):
        return 1

    if not zsvirt_repo:
        LOG.error("--zsvirt-repo is required.")
        return 1
    if not ee_repo:
        LOG.error("--ee-repo is required.")
        return 1
    zsvirt_repo = os.path.realpath(zsvirt_repo)
    ee_repo = os.path.realpath(ee_repo)
    if not _ensure_repo(zsvirt_repo, "zsvirt") or not _ensure_repo(ee_repo, "zsvirt-ee"):
        return 1

    runner = runner or cbok_utils.UnifiedProcessRunner()
    base_ref = zsv_base_ref()
    if not base_ref:
        LOG.error("Configure zsv.base_ref before running Groovy tests.")
        return 1
    for repo in (zsvirt_repo, ee_repo):
        if not check_worktree_clean(repo):
            return 1
    # Refresh both repositories before resolving remote branch inputs.
    for repo in (zsvirt_repo, ee_repo):
        if not sync_base_ref(repo):
            return 1
    inputs = []
    for repo, ref in ((zsvirt_repo, zsvirt_branch), (ee_repo, ee_branch)):
        source = _git_ref(runner, repo, ref)
        base = _git_ref(runner, repo, base_ref)
        if not source or not base:
            LOG.error("Cannot resolve requested ref %s or base %s in %s", ref, base_ref, repo)
            return 1
        inputs.append({"repo": repo, "ref": ref, "source": source, "base_ref": base_ref, "base": base})
    docker_conf = remote_docker_compile_from_conf()
    run_id = _safe_run_id(run_id or f"{zsvirt_branch}-{ee_branch}")
    if work_root:
        root = Path(os.path.realpath(work_root))
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = Path("/tmp") / f"cbok-zsv-groovy-test-{run_id}"
        root.mkdir(parents=True, exist_ok=True)

    work_zsvirt = root / "zsvirt"
    work_ee = root / "zsvirt-ee"
    metadata_path = root / "rebased-refs.json"
    case_file = root / "cases.txt"
    runner_container = f"cbok-zsv-groovy-{run_id}-runner"
    image = image or docker_conf.image.strip() or FALLBACK_IMAGE
    platform = docker_conf.platform.strip() if platform is None else platform
    docker_host = _normalize_docker_host(docker_conf.docker_host if docker_host is None else docker_host)
    if docker_host.lower() in ("none", "-", "disabled", "off", "false", "0"):
        docker_host = ""
    workdir = (docker_conf.workdir.strip() or DOCKER_WORK_ROOT).rstrip("/")
    m2_volume = docker_conf.m2_volume.strip() or "auto"

    partial_worktree = (work_zsvirt.exists() and not work_ee.exists()) or (
        work_ee.exists() and not work_zsvirt.exists()
    )
    if partial_worktree:
        _cleanup_worktrees(runner, zsvirt_repo, ee_repo, work_zsvirt, work_ee, root)
        root.mkdir(parents=True, exist_ok=True)
    elif work_zsvirt.exists() and work_ee.exists() and keep_worktree:
        if not _worktrees_match_requested_refs(
                runner, metadata_path, inputs, (work_zsvirt, work_ee),
        ):
            _cleanup_worktrees(runner, zsvirt_repo, ee_repo, work_zsvirt, work_ee, root)
            root.mkdir(parents=True, exist_ok=True)
    elif (work_zsvirt.exists() or work_ee.exists()) and not keep_worktree:
        _cleanup_worktrees(runner, zsvirt_repo, ee_repo, work_zsvirt, work_ee, root)
        root.mkdir(parents=True, exist_ok=True)

    if not work_zsvirt.exists() and not work_ee.exists():
        rc = _run(
            runner,
            ["git", "-C", zsvirt_repo, "worktree", "add", "--detach", str(work_zsvirt), inputs[0]["source"]],
        )
        if rc != 0:
            return rc
        rc = _run(
            runner,
            ["git", "-C", ee_repo, "worktree", "add", "--detach", str(work_ee), inputs[1]["source"]],
        )
        if rc != 0:
            return rc

        for worktree in (work_zsvirt, work_ee):
            if not rebase_worktree(str(worktree)):
                return 1
        # rebase fetches again; record the base actually used for the resulting HEAD.
        for item, worktree in zip(inputs, (work_zsvirt, work_ee)):
            item["base"] = _git_ref(runner, worktree, base_ref)
        heads = [_git_ref(runner, worktree, "HEAD") for worktree in (work_zsvirt, work_ee)]
        if not all(heads) or not all(item["base"] for item in inputs):
            LOG.error("Cannot record rebased Groovy test worktrees.")
            return 1
        metadata_path.write_text(json.dumps({"inputs": inputs, "heads": heads}))

    rc = _reset_test_worktree(runner, work_zsvirt)
    if rc != 0:
        return rc
    rc = _reset_test_worktree(runner, work_ee)
    if rc != 0:
        return rc

    try:
        _create_ee_link(work_zsvirt)
        target = _resolve_test_target(work_zsvirt, work_ee, test_class, test_mode)
    except ValueError as exc:
        LOG.error("%s", exc)
        return 1
    if target.needs_case_file and "." not in test_class:
        LOG.error("Case mode requires fully qualified --test-class, got: %s", test_class)
        return 1
    _write_harnesses(work_zsvirt, work_ee, target)
    if target.needs_case_file:
        _write_file(case_file, f"{test_class}\n")

    spec = WorktreeContainerSpec(
        zsvirt_root=str(work_zsvirt),
        ee_root=str(work_ee),
        docker_host=docker_host,
        image=image,
        platform=platform or "",
        workdir=workdir,
        container_name="auto",
        m2_volume=m2_volume,
        identity_zsvirt_root=zsvirt_repo,
        identity_ee_root=ee_repo,
        min_free_gb=docker_conf.min_free_gb,
    )
    rc, handle = ensure_worktree_container(
        runner,
        spec,
        require_full_compile=True,
    )
    if rc != 0 or handle is None:
        return rc or 1

    if not handle.full_compile_ran:
        rc = _incremental_compile_changed_modules(runner, docker_host, handle, work_zsvirt, work_ee)
        if rc != 0:
            return rc

    reuse_deploy_db = False if refresh_deploy_db else _container_db_is_ready(runner, docker_host, handle.container_name)
    if reuse_deploy_db:
        LOG.info("Reusing prepared Groovy test database in %s.", handle.container_name)
    elif refresh_deploy_db:
        LOG.info("Refreshing Groovy test database in %s.", handle.container_name)

    if target.needs_case_file:
        rc = _docker_cp_file_to_container(
            runner,
            docker_host,
            case_file,
            handle.container_name,
            CASE_FILE_IN_CONTAINER,
        )
        if rc != 0:
            return rc

    return _run_remote_container_script(
        runner,
        docker_host,
        handle.container_name,
        root / "remote-run.sh",
        build_container_test_script(target, handle.workdir, reuse_deploy_db),
        reuse_deploy_db=reuse_deploy_db,
    )
