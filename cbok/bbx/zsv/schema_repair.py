from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

from cbok.bbx.zsv import base_ref as zsv_base_ref_helper
from cbok.bbx.zsv.config import zsv_base_ref
from cbok.bbx.zsv.config import zstack_root_from_workspace


LOG = logging.getLogger(__name__)

DEFAULT_REMOTE_SQL_DIR = "/tmp/cbok-zsv-schema-sql"
DEFAULT_REMOTE_APPLY_SQL = "/tmp/cbok-zsv-schema-apply.sql"
ZSV_DB_DIR = "conf/db/zsv"
DEFAULT_ZSV_SCHEMA_DB_FILE = os.path.join(ZSV_DB_DIR, "V5.1.0__schema.sql")


@dataclass(frozen=True)
class AppliedMigration:
    version: str
    version_rank: int
    checksum: int | None
    script: str


@dataclass(frozen=True)
class ChecksumMismatch:
    version: str
    applied_checksum: int
    resolved_checksum: int


def _git(root: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", root, *args],
        capture_output=True,
        text=True,
    )


def _sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _version_from_script(script: str) -> str:
    m = re.match(r"V(?P<version>[^_]+)__.*\.sql$", os.path.basename(script))
    if not m:
        raise ValueError(f"cannot parse migration version from {script}")
    return m.group("version")


def branch_sql_files(zstack_root: str, branch: str) -> dict[str, str]:
    result = _git(zstack_root, "ls-tree", "-r", "--name-only", branch, "--", ZSV_DB_DIR)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip())

    files: dict[str, str] = {}
    for path in (result.stdout or "").splitlines():
        name = os.path.basename(path.strip())
        if not name.startswith("V") or not name.endswith(".sql"):
            continue
        files[_version_from_script(name)] = path.strip()
    return files


def read_branch_file(zstack_root: str, branch: str, path: str) -> str:
    result = _git(zstack_root, "show", f"{branch}:{path}")
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip())
    return result.stdout or ""


def write_branch_sql_dir(
    zstack_root: str,
    branch: str,
    files_by_version: dict[str, str],
    target_dir: str,
) -> None:
    Path(target_dir).mkdir(parents=True, exist_ok=True)
    for path in files_by_version.values():
        content = read_branch_file(zstack_root, branch, path)
        Path(target_dir, os.path.basename(path)).write_text(content, encoding="utf-8")


def materialize_zsv_schema_db_file(
    *,
    target_dir: str,
    zstack_root: str | None = None,
) -> str:
    base_ref = zsv_base_ref()
    if not base_ref:
        raise RuntimeError("zsv base_ref is not configured")

    root = os.path.realpath(zstack_root) if zstack_root else zstack_root_from_workspace()
    if not zsv_base_ref_helper.sync_base_ref(root):
        raise RuntimeError(f"failed to sync zsv base_ref {base_ref}")

    content = read_branch_file(root, base_ref, DEFAULT_ZSV_SCHEMA_DB_FILE)
    Path(target_dir).mkdir(parents=True, exist_ok=True)
    target = Path(target_dir, os.path.basename(DEFAULT_ZSV_SCHEMA_DB_FILE))
    target.write_text(content, encoding="utf-8")
    return str(target)


def parse_checksum_mismatches(output: str) -> list[ChecksumMismatch]:
    pattern = re.compile(
        r"Migration Checksum mismatch for migration (?P<version>[^\r\n]+)"
        r".*?Applied to database\s*:\s*(?P<applied>-?\d+)"
        r".*?Resolved locally\s*:\s*(?P<resolved>-?\d+)",
        re.S,
    )
    return [
        ChecksumMismatch(
            version=m.group("version").strip(),
            applied_checksum=int(m.group("applied")),
            resolved_checksum=int(m.group("resolved")),
        )
        for m in pattern.finditer(output or "")
    ]


def _bash_scriptlet(expr: str) -> list[str]:
    return ["bash", "-lc", f"source scriptlet/bootstrap.sh; {expr}"]


def _run_scriptlet(runner, expr: str):
    return runner.run_command(_bash_scriptlet(expr), cmd_purge_output=False)


def _remote_mysql_query(address: str, sql: str, runner) -> subprocess.CompletedProcess[str]:
    return _run_scriptlet(
        runner,
        "zsv_mysql_query "
        f"{shlex.quote(address)} {shlex.quote(sql)}",
    )


def _remote_applied_migrations(
    address: str,
    scripts: list[str],
    runner,
) -> dict[str, AppliedMigration]:
    if not scripts:
        return {}
    script_list = ",".join(_sql_string(script) for script in scripts)
    sql = (
        "SELECT version, version_rank, IFNULL(checksum, ''), script "
        "FROM zstack.schema_version "
        f"WHERE success = 1 AND script IN ({script_list})"
    )
    result = _remote_mysql_query(address, sql, runner)
    if getattr(result, "returncode", 1) != 0:
        raise RuntimeError(result.stdout or result.stderr or "failed to read schema_version")

    migrations: dict[str, AppliedMigration] = {}
    for line in (result.stdout or "").splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 4:
            continue
        version, version_rank, checksum, script = parts
        migrations[version] = AppliedMigration(
            version=version,
            version_rank=int(version_rank),
            checksum=int(checksum) if checksum else None,
            script=script,
        )
    return migrations


def _stage_sql_dir(address: str, local_dir: str, remote_dir: str, runner) -> int:
    result = _run_scriptlet(
        runner,
        "zsv_schema_stage_sql_dir "
        f"{shlex.quote(address)} {shlex.quote(local_dir)} {shlex.quote(remote_dir)}",
    )
    return getattr(result, "returncode", 1) or 0


def _run_remote_flyway(address: str, remote_dir: str, runner) -> subprocess.CompletedProcess[str]:
    return _run_scriptlet(
        runner,
        "zsv_schema_flyway_migrate "
        f"{shlex.quote(address)} {shlex.quote(remote_dir)}",
    )


def _run_remote_flyway_repair(address: str, remote_dir: str, runner) -> int:
    result = _run_scriptlet(
        runner,
        "zsv_schema_flyway_repair "
        f"{shlex.quote(address)} {shlex.quote(remote_dir)}",
    )
    return getattr(result, "returncode", 1) or 0


def _apply_schema_sql_file(address: str, local_sql_path: str, runner) -> subprocess.CompletedProcess[str]:
    return _run_scriptlet(
        runner,
        "zsv_schema_apply_sql_file "
        f"{shlex.quote(address)} {shlex.quote(local_sql_path)} "
        f"{shlex.quote(DEFAULT_REMOTE_APPLY_SQL)}",
    )


def _split_sql_statements(content: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    for line in content.splitlines(keepends=True):
        current.append(line)
        if line.rstrip().endswith(";"):
            statements.append("".join(current))
            current = []
    if current:
        statements.append("".join(current))
    return statements


def _statement_body(statement: str) -> str:
    return "\n".join(
        line
        for line in statement.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    )


def _is_duplicate_schema_replay_error(output: str) -> bool:
    patterns = (
        r"\bERROR\s+1050\b",  # table already exists
        r"\bERROR\s+1060\b",  # duplicate column
        r"\bERROR\s+1061\b",  # duplicate key name
        r"\bERROR\s+1022\b.*\bduplicate key\b",
        r"\bERROR\s+1005\b.*\berrno:\s*121\b",
    )
    return any(re.search(pattern, output or "", re.I | re.S) for pattern in patterns)


def _apply_schema_sql_statements(address: str, source_sql_path: str, runner) -> int:
    source = Path(source_sql_path)
    skipped = 0
    with tempfile.TemporaryDirectory() as td:
        for index, statement in enumerate(_split_sql_statements(source.read_text(encoding="utf-8")), 1):
            if not _statement_body(statement).strip():
                continue

            statement_path = Path(td, f"statement-{index:04d}.sql")
            statement_path.write_text(
                statement if statement.endswith("\n") else f"{statement}\n",
                encoding="utf-8",
            )
            result = _apply_schema_sql_file(address, str(statement_path), runner)
            rc = getattr(result, "returncode", 1) or 0
            if rc != 0 and _is_duplicate_schema_replay_error(
                "\n".join((getattr(result, "stdout", "") or "", getattr(result, "stderr", "") or ""))
            ):
                skipped += 1
                LOG.warning("Skipped duplicate ZSV schema replay error at statement %s.", index)
                continue
            if rc != 0:
                return rc

    if skipped:
        LOG.warning("Skipped %d duplicate ZSV schema replay error(s).", skipped)
    return 0


def _apply_mismatch_sql_and_repair(
    *,
    address: str,
    migration: AppliedMigration,
    mismatch: ChecksumMismatch,
    local_sql_path: str,
    remote_sql_dir: str,
    apply_repair: bool,
    runner,
) -> int:
    LOG.warning(
        "Applying ZSV schema migration %s for checksum %s -> %s before flyway repair.",
        migration.script,
        mismatch.applied_checksum,
        mismatch.resolved_checksum,
    )
    if not apply_repair:
        print(f"Would apply {local_sql_path} and run flyway repair on {address}.")
        return 1

    rc = _apply_schema_sql_statements(address, local_sql_path, runner)
    if rc != 0:
        return rc
    return _run_remote_flyway_repair(address, remote_sql_dir, runner)


def run_schema_repair_flow(
    *,
    address: str,
    branch: str,
    zstack_root: str | None,
    apply_repair: bool,
    runner,
) -> int:
    root = os.path.realpath(zstack_root) if zstack_root else zstack_root_from_workspace()
    files_by_version = branch_sql_files(root, branch)
    scripts = [os.path.basename(path) for path in files_by_version.values()]
    applied = _remote_applied_migrations(address, scripts, runner)
    applied_files = {
        version: path
        for version, path in files_by_version.items()
        if version in applied
    }
    if not applied_files:
        LOG.info("No applied ZSV schema migrations from branch %s found on %s.", branch, address)
        return 0

    with tempfile.TemporaryDirectory() as td:
        local_sql_dir = os.path.join(td, "zsv")
        write_branch_sql_dir(root, branch, applied_files, local_sql_dir)
        rc = _stage_sql_dir(address, local_sql_dir, DEFAULT_REMOTE_SQL_DIR, runner)
        if rc != 0:
            return rc

        flyway_result = _run_remote_flyway(address, DEFAULT_REMOTE_SQL_DIR, runner)
        if getattr(flyway_result, "returncode", 1) == 0:
            LOG.info("ZSV schema checksums already match branch %s.", branch)
            return 0

        mismatches = parse_checksum_mismatches(flyway_result.stdout or "")
        if not mismatches:
            LOG.error("Flyway failed but no checksum mismatch was detected.")
            return getattr(flyway_result, "returncode", 1) or 1

        mismatch = mismatches[0]
        migration = applied.get(mismatch.version)
        path = applied_files.get(mismatch.version)
        if not migration or not path:
            LOG.error("Checksum mismatch %s is not in applied ZSV branch files.", mismatch.version)
            return 1

        local_sql_path = os.path.join(local_sql_dir, os.path.basename(path))
        rc = _apply_mismatch_sql_and_repair(
            address=address,
            migration=migration,
            mismatch=mismatch,
            local_sql_path=local_sql_path,
            remote_sql_dir=DEFAULT_REMOTE_SQL_DIR,
            apply_repair=apply_repair,
            runner=runner,
        )
        if rc != 0:
            return rc

        verify_result = _run_remote_flyway(address, DEFAULT_REMOTE_SQL_DIR, runner)
        if getattr(verify_result, "returncode", 1) == 0:
            LOG.info("ZSV schema checksums match after flyway repair.")
            return 0
        LOG.error("Flyway still failed after schema SQL apply and repair.")
        return getattr(verify_result, "returncode", 1) or 1


def run_schema_repair_for_file(
    *,
    address: str,
    db_file: str,
    runner,
) -> int:
    if not db_file:
        LOG.info("No ZSV schema db_file configured; skip schema precheck.")
        return 0

    db_path = Path(db_file).expanduser()
    if not db_path.is_file():
        LOG.error("Configured ZSV schema db_file does not exist: %s", db_path)
        return 1

    script = db_path.name
    version = _version_from_script(script)
    applied = _remote_applied_migrations(address, [script], runner)
    migration = applied.get(version)
    if not migration:
        LOG.info("ZSV schema migration %s has not been applied on %s.", script, address)
        return 0

    with tempfile.TemporaryDirectory() as td:
        local_sql_dir = os.path.join(td, "zsv")
        Path(local_sql_dir).mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(db_path), os.path.join(local_sql_dir, script))
        rc = _stage_sql_dir(address, local_sql_dir, DEFAULT_REMOTE_SQL_DIR, runner)
        if rc != 0:
            return rc

        flyway_result = _run_remote_flyway(address, DEFAULT_REMOTE_SQL_DIR, runner)
        if getattr(flyway_result, "returncode", 1) == 0:
            LOG.info("ZSV schema checksum already matches %s.", db_path)
            return 0

        mismatches = parse_checksum_mismatches(flyway_result.stdout or "")
        if not mismatches:
            LOG.error("Flyway failed but no checksum mismatch was detected.")
            return getattr(flyway_result, "returncode", 1) or 1

        mismatch = mismatches[0]
        if mismatch.version != version:
            LOG.error("Checksum mismatch %s does not match configured db_file %s.", mismatch.version, db_path)
            return 1

        rc = _apply_mismatch_sql_and_repair(
            address=address,
            migration=migration,
            mismatch=mismatch,
            local_sql_path=str(db_path),
            remote_sql_dir=DEFAULT_REMOTE_SQL_DIR,
            apply_repair=True,
            runner=runner,
        )
        if rc != 0:
            return rc

        verify_result = _run_remote_flyway(address, DEFAULT_REMOTE_SQL_DIR, runner)
        if getattr(verify_result, "returncode", 1) == 0:
            LOG.info("ZSV schema checksum matches after flyway repair.")
            return 0
        LOG.error("Flyway still failed after schema SQL apply and repair.")
        return getattr(verify_result, "returncode", 1) or 1
