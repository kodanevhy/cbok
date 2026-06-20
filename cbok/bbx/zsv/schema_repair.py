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

from cbok.bbx.zsv.compile import zstack_root_from_workspace


LOG = logging.getLogger(__name__)

DEFAULT_REMOTE_SQL_DIR = "/tmp/cbok-zsv-schema-sql"
DEFAULT_REMOTE_REPAIR_SQL = "/tmp/cbok-zsv-schema-repair.sql"
ZSV_DB_DIR = "conf/db/zsv"


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


@dataclass(frozen=True)
class SchemaRepairReport:
    version: str
    version_rank: int
    applied_checksum: int | None
    resolved_checksum: int
    missing_tables: list[str]
    missing_columns: list[str]
    view_names: list[str]
    ddl_statements: list[str]


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


def split_sql_statements(sql: str) -> list[str]:
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)

    statements: list[str] = []
    current: list[str] = []
    for ch in cleaned:
        if ch == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


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


def build_repair_sql(report: SchemaRepairReport) -> str:
    lines = [
        f"-- cbok zsv schema repair for migration {report.version}",
    ]
    for statement in report.ddl_statements:
        lines.append(statement.rstrip().rstrip(";") + ";")
    lines.append(
        "UPDATE `zstack`.`schema_version` SET `checksum` = "
        f"{report.resolved_checksum} WHERE `version_rank` = {report.version_rank} "
        f"AND `version` = {_sql_string(report.version)};"
    )
    return "\n".join(lines) + "\n"


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


def _remote_mysql_scalar(address: str, sql: str, runner) -> str:
    result = _remote_mysql_query(address, sql, runner)
    if getattr(result, "returncode", 1) != 0:
        raise RuntimeError(result.stdout or result.stderr or "remote mysql query failed")
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _remote_table_exists(address: str, table: str, runner) -> bool:
    sql = (
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = 'zstack' AND table_name = "
        f"{_sql_string(table)}"
    )
    return _remote_mysql_scalar(address, sql, runner) == "1"


def _remote_column_exists(address: str, table: str, column: str, runner) -> bool:
    sql = (
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = 'zstack' AND table_name = "
        f"{_sql_string(table)} AND column_name = {_sql_string(column)}"
    )
    return _remote_mysql_scalar(address, sql, runner) == "1"


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


def _apply_repair_sql(address: str, local_sql_path: str, runner) -> int:
    result = _run_scriptlet(
        runner,
        "zsv_schema_apply_sql_file "
        f"{shlex.quote(address)} {shlex.quote(local_sql_path)} "
        f"{shlex.quote(DEFAULT_REMOTE_REPAIR_SQL)}",
    )
    return getattr(result, "returncode", 1) or 0


def _repair_report_for_mismatch(
    *,
    address: str,
    migration: AppliedMigration,
    mismatch: ChecksumMismatch,
    sql: str,
    runner,
) -> SchemaRepairReport:
    ddl_statements: list[str] = []
    missing_tables: list[str] = []
    missing_columns: list[str] = []
    view_names: list[str] = []

    for statement in split_sql_statements(sql):
        normalized = " ".join(statement.split())
        alter = re.match(
            r"ALTER\s+TABLE\s+`zstack`\.`(?P<table>[^`]+)`\s+"
            r"ADD\s+COLUMN\s+`(?P<column>[^`]+)`(?:\s|$)",
            normalized,
            re.I,
        )
        if alter:
            table = alter.group("table")
            column = alter.group("column")
            if not _remote_column_exists(address, table, column, runner):
                ddl_statements.append(statement)
                missing_columns.append(f"{table}.{column}")
            continue

        create_table = re.match(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`zstack`\.`(?P<table>[^`]+)`(?:\s|$)",
            normalized,
            re.I,
        )
        if create_table:
            table = create_table.group("table")
            if not _remote_table_exists(address, table, runner):
                ddl_statements.append(statement)
                missing_tables.append(table)
            continue

        view = re.match(
            r"(?:DROP\s+VIEW\s+IF\s+EXISTS|CREATE\s+VIEW)\s+`zstack`\.`(?P<view>[^`]+)`(?:\s|$)",
            normalized,
            re.I,
        )
        if view:
            ddl_statements.append(statement)
            view_names.append(view.group("view"))
            continue

        update = re.match(
            r"UPDATE\s+`zstack`\.`(?P<table>[^`]+)`(?:\s+\w+)?\s+SET\s+",
            normalized,
            re.I,
        )
        if update:
            ddl_statements.append(statement)
            continue

        raise RuntimeError(
            f"unsupported SQL in applied migration {migration.script}: {normalized[:160]}"
        )

    return SchemaRepairReport(
        version=migration.version,
        version_rank=migration.version_rank,
        applied_checksum=migration.checksum,
        resolved_checksum=mismatch.resolved_checksum,
        missing_tables=missing_tables,
        missing_columns=missing_columns,
        view_names=sorted(set(view_names)),
        ddl_statements=ddl_statements,
    )


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

        for _attempt in range(10):
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

            sql = read_branch_file(root, branch, path)
            report = _repair_report_for_mismatch(
                address=address,
                migration=migration,
                mismatch=mismatch,
                sql=sql,
                runner=runner,
            )
            LOG.warning(
                "Repairing ZSV schema %s checksum %s -> %s; missing tables=%s, "
                "missing columns=%s, refreshed views=%s",
                report.version,
                report.applied_checksum,
                report.resolved_checksum,
                ",".join(report.missing_tables) or "(none)",
                ",".join(report.missing_columns) or "(none)",
                ",".join(report.view_names) or "(none)",
            )
            repair_sql = build_repair_sql(report)
            repair_path = os.path.join(td, f"repair-{report.version}.sql")
            Path(repair_path).write_text(repair_sql, encoding="utf-8")
            if not apply_repair:
                print(repair_sql)
                return 1
            rc = _apply_repair_sql(address, repair_path, runner)
            if rc != 0:
                return rc

        LOG.error("Too many ZSV schema checksum repairs; aborting before upgrade.")
        return 1


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

        for _attempt in range(10):
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

            sql = db_path.read_text(encoding="utf-8")
            report = _repair_report_for_mismatch(
                address=address,
                migration=migration,
                mismatch=mismatch,
                sql=sql,
                runner=runner,
            )
            LOG.warning(
                "Repairing ZSV schema %s checksum %s -> %s; missing tables=%s, "
                "missing columns=%s, refreshed views=%s",
                report.version,
                report.applied_checksum,
                report.resolved_checksum,
                ",".join(report.missing_tables) or "(none)",
                ",".join(report.missing_columns) or "(none)",
                ",".join(report.view_names) or "(none)",
            )
            repair_sql = build_repair_sql(report)
            repair_path = os.path.join(td, f"repair-{report.version}.sql")
            Path(repair_path).write_text(repair_sql, encoding="utf-8")
            rc = _apply_repair_sql(address, repair_path, runner)
            if rc != 0:
                return rc

        LOG.error("Too many ZSV schema checksum repairs; aborting before upgrade.")
        return 1
