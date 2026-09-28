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


LOG = logging.getLogger(__name__)

DEFAULT_REMOTE_SQL_DIR = "/tmp/cbok-zsv-schema-sql"
MANUAL_REPAIR_SKILL = "cbok-zsv-upgrade-db-repair"
ARTIFACT_PRECHECK_MARKER = "__CBOK_ZSV_SCHEMA_PRECHECK__"


class ZsvSchemaChecksumMismatchError(Exception):
    def __init__(self, message: str, returncode: int = 1):
        self.returncode = returncode
        super().__init__(message)


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


def _sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _version_from_script(script: str) -> str:
    m = re.match(r"V(?P<version>[^_]+)__.*\.sql$", os.path.basename(script))
    if not m:
        raise ValueError(f"cannot parse migration version from {script}")
    return m.group("version")


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
    return runner.run_command(_bash_scriptlet(expr))


def _run_scriptlet_quiet(runner, expr: str):
    return runner.run_command(
        _bash_scriptlet(expr),
        log_output=False,
        log_failed_status=False,
    )


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


def format_manual_repair_hint(
    *,
    address: str,
    migration: AppliedMigration,
    mismatch: ChecksumMismatch,
    db_file: str,
) -> str:
    return "\n".join([
        "ZSV schema checksum mismatch detected.",
        "cbok will not repair the database automatically.",
        f"Ask the AI to use skill `{MANUAL_REPAIR_SKILL}` to repair the database, then retry `cbok zsv upgrade`.",
        f"primary node: {address}",
        f"migration: {migration.version} ({migration.script})",
        f"applied checksum: {mismatch.applied_checksum}",
        f"resolved checksum: {mismatch.resolved_checksum}",
        f"SQL source: {db_file}",
    ])


def _parse_artifact_precheck_report(output: str) -> dict[str, str]:
    lines = (output or "").splitlines()
    try:
        start = lines.index(ARTIFACT_PRECHECK_MARKER) + 1
    except ValueError:
        return {}

    fields: dict[str, str] = {}
    for line in lines[start:]:
        if not line.strip():
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def run_schema_mismatch_precheck_for_artifact(
    *,
    address: str,
    artifact_url: str,
    artifact_name: str,
    artifact_modified: str = "",
    artifact_size: str = "",
    upgrade_type: str,
    runner,
) -> int:
    result = _run_scriptlet_quiet(
        runner,
        "zsv_schema_precheck_artifact "
        f"{shlex.quote(address)} "
        f"{shlex.quote(artifact_url)} "
        f"{shlex.quote(artifact_name)} "
        f"{shlex.quote(artifact_modified or '')} "
        f"{shlex.quote(artifact_size or '')} "
        f"{shlex.quote(upgrade_type)}",
    )
    returncode = getattr(result, "returncode", 1) or 0
    if returncode == 0:
        return 0

    output = result.stdout or result.stderr or ""
    fields = _parse_artifact_precheck_report(output)
    try:
        version = fields["version"]
        script = fields["script"]
        version_rank = int(fields["version_rank"])
        applied_checksum = int(fields["applied_checksum"])
        resolved_checksum = int(fields["resolved_checksum"])
    except (KeyError, ValueError):
        LOG.error("ZSV schema artifact precheck failed.\n%s", output.strip())
        return returncode
    if not re.fullmatch(r"\d+(?:\.\d+)+", version) or not (
            script.startswith(f"V{version}__") and script.endswith(".sql")):
        LOG.error("ZSV schema artifact precheck failed.\n%s", output.strip())
        return returncode

    migration = AppliedMigration(
        version=version,
        version_rank=version_rank,
        checksum=applied_checksum,
        script=script,
    )
    mismatch = ChecksumMismatch(
        version=version,
        applied_checksum=applied_checksum,
        resolved_checksum=resolved_checksum,
    )
    raise ZsvSchemaChecksumMismatchError(format_manual_repair_hint(
        address=fields.get("primary_node") or address,
        migration=migration,
        mismatch=mismatch,
        db_file=fields.get("sql_source") or fields.get("artifact_path") or artifact_name,
    ), returncode=returncode)


def run_schema_mismatch_precheck_for_file(
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

        LOG.error(format_manual_repair_hint(
            address=address,
            migration=migration,
            mismatch=mismatch,
            db_file=str(db_path),
        ))
        return 1
