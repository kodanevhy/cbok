from __future__ import annotations

import datetime
import hashlib
import logging
import os
import shlex
import subprocess
from dataclasses import asdict
from dataclasses import dataclass


LOG = logging.getLogger(__name__)

DEFAULT_WORKDIR = "/work"
DEFAULT_M2_VOLUME = "zsv-m2"
MAVEN_REPO = "/var/maven/.m2/repository"
FULL_COMPILE_THREADS = "12"
FULL_COMPILE_CMD = "./runMavenProfile premium"
SOURCE_EXCLUDES = (
    "--exclude .git "
    "--exclude target "
    "--exclude '*/target' "
    "--exclude .idea "
    "--exclude .gradle "
    "--exclude node_modules "
    "--exclude '._*' "
    "--exclude '*/._*' "
    "--exclude .DS_Store "
    "--exclude '*/.DS_Store' "
    "--exclude __MACOSX "
    "--exclude '*/__MACOSX'"
)
RSYNC_EXCLUDES = (
    "--exclude .git "
    "--exclude target "
    "--exclude '*/target' "
    "--exclude .idea "
    "--exclude .gradle "
    "--exclude node_modules "
    "--exclude '._*' "
    "--exclude '*/._*' "
    "--exclude .DS_Store "
    "--exclude '*/.DS_Store' "
    "--exclude __MACOSX "
    "--exclude '*/__MACOSX'"
)
PREMIUM_DIR_EXCLUDES = "--exclude premium --exclude ./premium"


@dataclass(frozen=True)
class WorktreeContainerSpec:
    zstack_root: str
    premium_root: str | None
    docker_host: str
    image: str
    platform: str = ""
    workdir: str = DEFAULT_WORKDIR
    container_name: str = "auto"
    m2_volume: str = DEFAULT_M2_VOLUME


@dataclass
class WorktreeContainerRecord:
    worktree_key: str
    zstack_root: str
    premium_root: str
    docker_host: str
    image: str
    platform: str
    workdir: str
    container_name: str
    m2_volume: str
    zstack_head: str = ""
    premium_head: str = ""
    full_compile_done: bool = False
    full_compile_started_at: datetime.datetime | None = None
    full_compile_finished_at: datetime.datetime | None = None
    last_used_at: datetime.datetime | None = None
    last_error: str = ""


@dataclass(frozen=True)
class WorktreeContainerHandle:
    worktree_key: str
    container_name: str
    docker_host: str
    workdir: str
    work_zstack: str
    work_premium: str
    full_compile_ran: bool


class InMemoryWorktreeContainerStore:
    def __init__(self):
        self.records: dict[str, WorktreeContainerRecord] = {}

    def get_or_create(self, defaults: WorktreeContainerRecord):
        existing = self.records.get(defaults.worktree_key)
        if existing:
            return existing, False
        self.records[defaults.worktree_key] = defaults
        return defaults, True

    def save(self, record, update_fields=None):
        self.records[record.worktree_key] = record

    def find_by_container_name(self, container_name: str):
        for record in self.records.values():
            if record.container_name == container_name:
                return record
        return None


class DjangoWorktreeContainerStore:
    def get_or_create(self, defaults: WorktreeContainerRecord):
        from cbok.bbx.models import ZsvWorktreeContainerState

        values = asdict(defaults)
        key = values.pop("worktree_key")
        obj, created = ZsvWorktreeContainerState.objects.get_or_create(
            worktree_key=key,
            defaults=values,
        )
        if not created:
            changed = []
            for field in (
                    "zstack_root",
                    "premium_root",
                    "docker_host",
                    "image",
                    "platform",
                    "workdir",
                    "container_name",
                    "m2_volume",
            ):
                value = getattr(defaults, field)
                if getattr(obj, field) != value:
                    setattr(obj, field, value)
                    changed.append(field)
            if changed:
                obj.save(update_fields=changed)
        return obj, created

    def save(self, record, update_fields=None):
        record.save(update_fields=update_fields)

    def find_by_container_name(self, container_name: str):
        from cbok.bbx.models import ZsvWorktreeContainerState

        return ZsvWorktreeContainerState.objects.filter(
            container_name=container_name,
        ).first()


_FALLBACK_STORE = InMemoryWorktreeContainerStore()


def default_state_store():
    try:
        from django.apps import apps
        if apps.ready:
            return DjangoWorktreeContainerStore()
    except Exception:
        LOG.debug("Django app registry is not ready; using in-memory zsv container state")
    return _FALLBACK_STORE


def normalize_docker_host(raw: str | None) -> str:
    host = (raw or "").strip()
    if host.startswith("http://"):
        return "tcp://" + host[len("http://"):]
    if host.startswith("https://"):
        return "tcp://" + host[len("https://"):]
    if host.lower() in ("", "none", "-", "disabled", "off", "false", "0"):
        return ""
    return host


def worktree_key_for_spec(spec: WorktreeContainerSpec) -> str:
    parts = [
        os.path.realpath(spec.zstack_root),
        os.path.realpath(spec.premium_root) if spec.premium_root else "",
        normalize_docker_host(spec.docker_host),
        spec.image.strip(),
        (spec.platform or "").strip(),
        (spec.workdir or DEFAULT_WORKDIR).rstrip("/") or DEFAULT_WORKDIR,
    ]
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _safe_docker_token(value: str) -> str:
    token = "".join(c.lower() if c.isalnum() else "-" for c in value)
    token = "-".join(part for part in token.split("-") if part)
    return token or "worktree"


def container_name_for_spec(spec: WorktreeContainerSpec, worktree_key: str) -> str:
    raw = (spec.container_name or "").strip()
    if raw and raw.lower() != "auto":
        return raw
    root_name = _safe_docker_token(os.path.basename(os.path.realpath(spec.zstack_root)))
    return f"cbok-zsv-worktree-{root_name}-{worktree_key[:16]}"


def _git_head(root: str | None) -> str:
    if not root or not os.path.isdir(root):
        return ""
    result = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _now() -> datetime.datetime:
    try:
        from django.utils import timezone
        return timezone.now()
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc)


def _run_shell(runner, script: str) -> int:
    result = runner.run_command(["bash", "-lc", script], cmd_purge_output=False)
    return getattr(result, "returncode", 1) or 0


def docker_env_prefix(docker_host: str) -> str:
    docker_host = normalize_docker_host(docker_host)
    if not docker_host:
        return ""
    return f"DOCKER_HOST={shlex.quote(docker_host)} "


def docker_shell(runner, docker_host: str, args: list[str]) -> int:
    command = "docker " + " ".join(shlex.quote(arg) for arg in args)
    return _run_shell(runner, docker_env_prefix(docker_host) + command)


def docker_shell_capture(runner, docker_host: str, args: list[str]):
    command = "docker " + " ".join(shlex.quote(arg) for arg in args)
    return runner.run_command(
        ["bash", "-lc", docker_env_prefix(docker_host) + command],
        cmd_purge_output=False,
    )


def _returncode(result) -> int:
    return getattr(result, "returncode", 1) or 0


def _docker_running_state(runner, docker_host: str, container_name: str) -> bool | None:
    result = docker_shell_capture(
        runner,
        docker_host,
        ["inspect", "--format", "{{.State.Running}}", container_name],
    )
    if _returncode(result) != 0:
        return None
    return (getattr(result, "stdout", "") or "").strip().lower() == "true"


def _create_container(runner, spec: WorktreeContainerSpec, container_name: str) -> int:
    cmd = ["create", "--name", container_name]
    if spec.platform:
        cmd.extend(["--platform", spec.platform])
    if spec.m2_volume:
        cmd.extend(["-v", f"{spec.m2_volume}:/var/maven/.m2"])
    cmd.extend([spec.image, "sleep", "infinity"])
    return docker_shell(runner, spec.docker_host, cmd)


def _start_and_init_container(runner, spec: WorktreeContainerSpec, container_name: str) -> int:
    rc = docker_shell(runner, spec.docker_host, ["start", container_name])
    if rc != 0:
        return rc
    init_script = f"""
set -euo pipefail
	mkdir -p {shlex.quote(spec.workdir)}/zstack /tmp /var/maven/.m2
rm -rf /root/.m2
ln -sfn /var/maven/.m2 /root/.m2
"""
    return docker_shell(
        runner,
        spec.docker_host,
        ["exec", container_name, "bash", "-lc", init_script],
    )


def ensure_container_exists(runner, spec: WorktreeContainerSpec, container_name: str) -> tuple[int, bool]:
    running = _docker_running_state(runner, spec.docker_host, container_name)
    created = False
    if running is None:
        rc = _create_container(runner, spec, container_name)
        if rc != 0:
            return rc, created
        created = True
        running = False
    if not running:
        rc = _start_and_init_container(runner, spec, container_name)
        if rc != 0:
            return rc, created
    else:
        rc = _start_and_init_container(runner, spec, container_name)
        if rc != 0:
            return rc, created
    return 0, created


def _stream_source_to_upload_dir(
        runner,
        spec: WorktreeContainerSpec,
        source_dir: str,
        container_name: str,
        upload_dir: str,
        *,
        exclude_premium: bool = False,
) -> int:
    premium_excludes = "--exclude premium --exclude ./premium " if exclude_premium else ""
    excludes = SOURCE_EXCLUDES + " " + premium_excludes
    inner = f"rm -rf {shlex.quote(upload_dir)} && mkdir -p {shlex.quote(upload_dir)} && tar -xzf - -C {shlex.quote(upload_dir)}"
    script = (
        "tar_extra_opts=''; "
        "tar --no-xattrs -cf /dev/null --files-from /dev/null >/dev/null 2>&1 && tar_extra_opts=\"$tar_extra_opts --no-xattrs\"; "
        "tar --no-mac-metadata -cf /dev/null --files-from /dev/null >/dev/null 2>&1 && tar_extra_opts=\"$tar_extra_opts --no-mac-metadata\"; "
        f"COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 tar $tar_extra_opts -C {shlex.quote(source_dir)} {excludes} -czf - . | "
        f"{docker_env_prefix(spec.docker_host)}docker exec -i {shlex.quote(container_name)} "
        f"bash -lc {shlex.quote(inner)}"
    )
    return _run_shell(runner, script)


def sync_sources_to_container(runner, spec: WorktreeContainerSpec, container_name: str) -> int:
    work_zstack = f"{spec.workdir}/zstack"
    work_premium = f"{work_zstack}/premium"
    upload_root = "/tmp/cbok-zsv-src"
    rc = _stream_source_to_upload_dir(
        runner,
        spec,
        spec.zstack_root,
        container_name,
        f"{upload_root}/zstack",
        exclude_premium=True,
    )
    if rc != 0:
        return rc
    premium_sync = ""
    if spec.premium_root:
        rc = _stream_source_to_upload_dir(
            runner,
            spec,
            spec.premium_root,
            container_name,
            f"{upload_root}/premium",
        )
        if rc != 0:
            return rc
        premium_sync = f"""
	if [ -L {shlex.quote(work_premium)} ]; then
	  rm -f {shlex.quote(work_premium)}
	fi
	if [ -e {shlex.quote(work_premium)} ] && [ ! -d {shlex.quote(work_premium)} ]; then
	  rm -f {shlex.quote(work_premium)}
	fi
	mkdir -p {shlex.quote(work_premium)}
	rsync -a --delete {RSYNC_EXCLUDES} {upload_root}/premium/ {shlex.quote(work_premium)}/
	"""
    sync_script = f"""
	set -euo pipefail
	mkdir -p {shlex.quote(work_zstack)}
	rsync -a --delete {RSYNC_EXCLUDES} {PREMIUM_DIR_EXCLUDES} {upload_root}/zstack/ {shlex.quote(work_zstack)}/
	{premium_sync}
	"""
    return docker_shell(
        runner,
        spec.docker_host,
        ["exec", container_name, "bash", "-lc", sync_script],
    )


def full_compile_script(spec: WorktreeContainerSpec) -> str:
    work_zstack = f"{spec.workdir}/zstack"
    script = f"""
set -euo pipefail
cd {shlex.quote(work_zstack)}
sed -i -E 's|mvn( -T [^ ]+)? -Dmaven.test.skip=true -P premium clean install|mvn -T {shlex.quote(FULL_COMPILE_THREADS)} -Dmaven.test.skip=true -P premium clean install|' runMavenProfile
grep -q 'mvn -T {shlex.quote(FULL_COMPILE_THREADS)} -Dmaven.test.skip=true -P premium clean install' runMavenProfile
{FULL_COMPILE_CMD}
cd {shlex.quote(work_zstack)}/testlib
mvn clean install -Dmaven.test.skip=true
if [ -d {shlex.quote(work_zstack)}/premium/testlib-premium ]; then
  cd {shlex.quote(work_zstack)}/premium/testlib-premium
  mvn clean install -Dmaven.test.skip=true
fi
"""
    return script


def _default_record(spec: WorktreeContainerSpec) -> WorktreeContainerRecord:
    key = worktree_key_for_spec(spec)
    return WorktreeContainerRecord(
        worktree_key=key,
        zstack_root=os.path.realpath(spec.zstack_root),
        premium_root=os.path.realpath(spec.premium_root) if spec.premium_root else "",
        docker_host=normalize_docker_host(spec.docker_host),
        image=spec.image,
        platform=spec.platform or "",
        workdir=spec.workdir,
        container_name=container_name_for_spec(spec, key),
        m2_volume=spec.m2_volume or "",
        zstack_head=_git_head(spec.zstack_root),
        premium_head=_git_head(spec.premium_root),
    )


def ensure_worktree_container(
        runner,
        spec: WorktreeContainerSpec,
        *,
        require_full_compile: bool = True,
        state_store=None,
) -> tuple[int, WorktreeContainerHandle | None]:
    spec = WorktreeContainerSpec(
        zstack_root=os.path.realpath(spec.zstack_root),
        premium_root=os.path.realpath(spec.premium_root) if spec.premium_root else None,
        docker_host=normalize_docker_host(spec.docker_host),
        image=spec.image,
        platform=spec.platform or "",
        workdir=(spec.workdir or DEFAULT_WORKDIR).rstrip("/") or DEFAULT_WORKDIR,
        container_name=spec.container_name or "auto",
        m2_volume=spec.m2_volume or DEFAULT_M2_VOLUME,
    )
    store = state_store or default_state_store()
    defaults = _default_record(spec)
    container_owner = store.find_by_container_name(defaults.container_name)
    if container_owner and container_owner.worktree_key != defaults.worktree_key:
        LOG.error(
            "Docker container %s is already bound to another worktree: %s (zstack: %s, premium: %s). "
            "Use a unique --docker-container for this worktree.",
            defaults.container_name,
            container_owner.worktree_key,
            container_owner.zstack_root,
            container_owner.premium_root,
        )
        return 1, None

    record, _created = store.get_or_create(defaults)
    container_created = False
    rc, container_created = ensure_container_exists(runner, spec, record.container_name)
    if rc != 0:
        return rc, None
    if container_created and record.full_compile_done:
        record.full_compile_done = False
        store.save(record, update_fields=["full_compile_done"])

    rc = sync_sources_to_container(runner, spec, record.container_name)
    if rc != 0:
        record.last_error = f"source sync failed: {rc}"
        record.last_used_at = _now()
        store.save(record, update_fields=["last_error", "last_used_at"])
        return rc, None

    full_compile_ran = False
    record.zstack_head = defaults.zstack_head
    record.premium_head = defaults.premium_head
    record.last_used_at = _now()
    store.save(record, update_fields=["zstack_head", "premium_head", "last_used_at"])

    if require_full_compile and not record.full_compile_done:
        full_compile_ran = True
        record.full_compile_started_at = _now()
        record.full_compile_finished_at = None
        record.last_error = ""
        store.save(
            record,
            update_fields=[
                "full_compile_started_at",
                "full_compile_finished_at",
                "last_error",
            ],
        )
        LOG.info("Running full ZStack premium compile in %s", record.container_name)
        rc = docker_shell(
            runner,
            spec.docker_host,
            ["exec", record.container_name, "bash", "-lc", full_compile_script(spec)],
        )
        if rc != 0:
            record.full_compile_done = False
            record.last_error = f"full compile failed: {rc}"
            record.last_used_at = _now()
            store.save(
                record,
                update_fields=["full_compile_done", "last_error", "last_used_at"],
            )
            return rc, None
        record.full_compile_done = True
        record.full_compile_finished_at = _now()
        record.last_used_at = record.full_compile_finished_at
        store.save(
            record,
            update_fields=[
                "full_compile_done",
                "full_compile_finished_at",
                "last_used_at",
            ],
        )

    handle = WorktreeContainerHandle(
        worktree_key=record.worktree_key,
        container_name=record.container_name,
        docker_host=spec.docker_host,
        workdir=spec.workdir,
        work_zstack=f"{spec.workdir}/zstack",
        work_premium=f"{spec.workdir}/zstack/premium",
        full_compile_ran=full_compile_ran,
    )
    return 0, handle
