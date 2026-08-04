from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
import logging
import os
import re
import shlex
import tempfile
from urllib.parse import unquote
from urllib.parse import urlparse

import requests

from django.utils import timezone

from cbok.bbx.models import ZSphereUpgradeState
from cbok import utils as cbok_utils
from cbok.bbx.zsv import schema_repair


LOG = logging.getLogger(__name__)

UPGRADE_TYPES = ("iso", "bin")
UPGRADE_HEALTH_TIMEOUT_SECONDS = 30 * 60
UPGRADE_HEALTH_POLL_INTERVAL_SECONDS = 10
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


@dataclass
class IsoInfo:
    name: str
    download_url: str
    modified_at: datetime | None = None
    size: str = ""


def _aware(dt):
    if dt is None:
        return None
    if timezone.is_aware(dt):
        return dt
    return timezone.make_aware(dt, timezone.get_current_timezone())


def _normalize_upgrade_type(value):
    upgrade_type = value.strip().lower()
    if upgrade_type not in UPGRADE_TYPES:
        raise ValueError(f"upgrade_type must be one of: {', '.join(UPGRADE_TYPES)}")
    return upgrade_type


def _required(value, name):
    if value is None or not str(value).strip():
        raise ValueError(f"{name} is required")
    return str(value).strip()


def _artifact_extension(upgrade_type):
    return ".bin" if upgrade_type == "bin" else ".iso"


def _artifact_type_from_url(url):
    path = unquote(urlparse(url).path).lower()
    for upgrade_type in UPGRADE_TYPES:
        if path.endswith(_artifact_extension(upgrade_type)):
            return upgrade_type
    return ""


def _require_artifact_url(url):
    artifact_type = _artifact_type_from_url(url)
    if not artifact_type:
        raise ValueError("upgrade_url must be an exact .iso or .bin file URL")
    return artifact_type


def _artifact_name_from_url(url):
    return os.path.basename(unquote(urlparse(url).path))


def _dedupe(items):
    out = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _is_node_address(value):
    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", value))


class ZsvHostDiscoveryError(RuntimeError):
    pass


def discover_management_nodes(address, runner):
    result = runner.run_command([
        "bash", "-lc",
        "source scriptlet/bootstrap.sh; "
        f"zsv_discover_management_nodes {shlex.quote(address)}",
    ], cmd_purge_output=False)
    if getattr(result, "returncode", 1) != 0:
        return []
    return _dedupe([
        line.strip()
        for line in (result.stdout or "").splitlines()
        if line.strip() and _is_node_address(line.strip())
    ])


def discover_healthy_kvm_host_nodes(address, runner):
    result = runner.run_command([
        "bash", "-lc",
        "source scriptlet/bootstrap.sh; "
        f"zsv_discover_healthy_kvm_hosts_from_primary {shlex.quote(address)}",
    ], cmd_purge_output=False)
    if getattr(result, "returncode", 1) != 0:
        details = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
        raise ZsvHostDiscoveryError(details or f"failed to discover healthy KVM hosts from {address}")
    nodes = _dedupe([
        line.strip()
        for line in (result.stdout or "").splitlines()
        if line.strip() and _is_node_address(line.strip())
    ])
    if not nodes:
        raise ZsvHostDiscoveryError(f"no healthy KVM hosts found from {address}")
    return nodes


def discover_ceph_primary_storage_nodes(address, runner):
    result = runner.run_command([
        "bash", "-lc",
        "source scriptlet/bootstrap.sh; "
        f"zsv_discover_ceph_primary_storage_nodes {shlex.quote(address)}",
    ], cmd_purge_output=False)
    if getattr(result, "returncode", 1) != 0:
        return []
    return _dedupe([
        line.strip()
        for line in (result.stdout or "").splitlines()
        if line.strip() and _is_node_address(line.strip())
    ])


def discover_zbs_primary_storage_nodes(address, runner):
    result = runner.run_command([
        "bash", "-lc",
        "source scriptlet/bootstrap.sh; "
        f"zsv_discover_zbs_primary_storage_nodes {shlex.quote(address)}",
    ], cmd_purge_output=False)
    if getattr(result, "returncode", 1) != 0:
        return []
    return _dedupe([
        line.strip()
        for line in (result.stdout or "").splitlines()
        if line.strip() and _is_node_address(line.strip())
    ])


def discover_imagestore_backup_storage_nodes(address, runner):
    result = runner.run_command([
        "bash", "-lc",
        "source scriptlet/bootstrap.sh; "
        f"zsv_discover_imagestore_bs_nodes_from_primary {shlex.quote(address)}",
    ], cmd_purge_output=False)
    if getattr(result, "returncode", 1) != 0:
        return []
    return _dedupe([
        line.strip()
        for line in (result.stdout or "").splitlines()
        if line.strip() and _is_node_address(line.strip())
    ])


class ZSphereTracker:
    def __init__(
            self,
            name=None,
            upgrade_type=None,
            upgrade_url=None,
            primary_node=None,
            runner=None,
        ):
        self.name = _required(name, "name")
        self.upgrade_url = _required(upgrade_url, "upgrade_url")
        self.upgrade_type = _require_artifact_url(self.upgrade_url)
        if upgrade_type:
            requested_type = _normalize_upgrade_type(str(upgrade_type))
            if requested_type != self.upgrade_type:
                raise ValueError(
                    f"upgrade_url file type {self.upgrade_type} "
                    f"does not match upgrade_type {requested_type}")
        self.iso_url = self.upgrade_url
        self.primary_node = _required(primary_node, "primary_node")
        self.nodes = self._normalize_nodes([self.primary_node])
        self.runner = runner or cbok_utils.UnifiedProcessRunner()
        self.discovered_nodes = False

    @staticmethod
    def _normalize_nodes(nodes):
        if isinstance(nodes, str):
            nodes = nodes.split(",")
        normalized = [node.strip() for node in nodes if node and node.strip()]
        if not normalized:
            raise ValueError("at least one ZSphere node is required")
        return normalized

    def get_state(self, persist_source=True):
        if not persist_source:
            state = ZSphereUpgradeState.objects.filter(name=self.name).first()
            if state:
                return state
            return ZSphereUpgradeState(
                name=self.name,
                iso_url=self.iso_url,
                nodes=",".join(self.nodes),
            )

        state, _ = ZSphereUpgradeState.objects.get_or_create(
            name=self.name,
            defaults={
                "iso_url": self.iso_url,
                "nodes": ",".join(self.nodes),
            },
        )
        state.iso_url = self.iso_url
        state.nodes = ",".join(self.nodes)
        state.save(update_fields=["iso_url", "nodes"])
        return state

    def fetch_latest_iso(self):
        return self._fetch_exact_artifact(self.upgrade_url)

    def _fetch_exact_artifact(self, artifact_url):
        try:
            response = requests.head(
                artifact_url, allow_redirects=True, timeout=20, headers=HTTP_HEADERS)
            response.raise_for_status()
        except requests.RequestException as exc:
            LOG.warning(
                "Unable to probe upgrade package metadata locally, remote node will download it directly: %s",
                exc,
            )
            return IsoInfo(
                name=_artifact_name_from_url(artifact_url),
                download_url=artifact_url,
            )
        modified_at = None
        if response.headers.get("Last-Modified"):
            modified_at = _aware(parsedate_to_datetime(
                response.headers["Last-Modified"]))
        return IsoInfo(
            name=_artifact_name_from_url(response.url or artifact_url),
            download_url=response.url or artifact_url,
            modified_at=modified_at,
            size=response.headers.get("Content-Length", ""),
        )

    def refresh_state(self, iso, persist_state=True):
        state = self.get_state(persist_source=persist_state)
        state.last_checked_at = timezone.now()

        update_fields = ["last_checked_at"]
        new_iso_detected = self._is_newer_iso(
            iso.name, iso.modified_at,
            state.latest_iso_name, state.latest_iso_modified_at)
        if new_iso_detected:
            state.latest_iso_name = iso.name
            state.latest_iso_modified_at = iso.modified_at
            update_fields.extend(["latest_iso_name", "latest_iso_modified_at"])

        if persist_state:
            state.save(update_fields=update_fields)
        return state, new_iso_detected

    @staticmethod
    def _is_newer_iso(name, modified_at, stored_name, stored_modified_at):
        if not stored_name:
            return True
        if modified_at and stored_modified_at:
            return modified_at > stored_modified_at
        if modified_at and not stored_modified_at:
            return True
        if not modified_at and not stored_modified_at:
            return name != stored_name
        return False

    @classmethod
    def needs_upgrade(cls, state, iso=None):
        latest_name = iso.name if iso else state.latest_iso_name
        latest_modified_at = iso.modified_at if iso else state.latest_iso_modified_at
        if not latest_name:
            return False
        if not state.last_upgraded_iso_name:
            return True
        if cls._is_newer_iso(
                latest_name, latest_modified_at,
                state.last_upgraded_iso_name,
                state.last_upgraded_iso_modified_at):
            return True
        return False

    @staticmethod
    def _iso_modified_arg(iso):
        if not iso.modified_at:
            return ""
        return timezone.localtime(iso.modified_at).isoformat()

    def check(self, persist_state=True):
        iso = self.fetch_latest_iso()
        state, new_iso_detected = self.refresh_state(iso, persist_state=persist_state)
        return iso, state, self.needs_upgrade(state, iso), new_iso_detected

    def record_successful_upgrade(self, state, iso):
        state.iso_url = self.iso_url
        state.nodes = ",".join(self.nodes)
        state.latest_iso_name = iso.name
        state.latest_iso_modified_at = iso.modified_at
        state.last_checked_at = timezone.now()
        state.last_upgraded_iso_name = iso.name
        state.last_upgraded_iso_modified_at = iso.modified_at
        state.last_upgraded_at = timezone.now()
        update_fields = [
            "iso_url",
            "nodes",
            "latest_iso_name",
            "latest_iso_modified_at",
            "last_checked_at",
            "last_upgraded_iso_name",
            "last_upgraded_iso_modified_at",
            "last_upgraded_at",
        ]
        if getattr(state, "pk", True) is None:
            state.save()
        else:
            state.save(update_fields=update_fields)

    def resolve_upgrade_nodes(self):
        nodes = discover_management_nodes(self.primary_node, self.runner)
        if not nodes:
            LOG.warning(
                "No management nodes discovered from primary node %s; "
                "falling back to primary node only",
                self.primary_node)
            nodes = [self.primary_node]
            self.discovered_nodes = False
        elif self.primary_node not in nodes:
            nodes.insert(0, self.primary_node)
            self.discovered_nodes = True
        else:
            self.discovered_nodes = True
        self.nodes = self._normalize_nodes(nodes)

    def ensure_scriptlet(self, command):
        for node in self.nodes:
            result = command.ensure_remote_scriptlet(node)
            if getattr(result, "returncode", 0) != 0:
                return result
        return None

    def status(self, command):
        self.resolve_upgrade_nodes()
        nodes = " ".join(shlex.quote(node) for node in self.nodes)
        result = self.runner.run_command([
            "bash", "-lc",
            f"source scriptlet/bootstrap.sh; zsv_nodes_status {nodes}",
        ], cmd_purge_output=True)
        return result.returncode

    def upgrade(self, command):
        self.resolve_upgrade_nodes()
        iso, state, needs_upgrade, _new_iso_detected = self.check(persist_state=False)
        if not needs_upgrade:
            LOG.error("Already up to date, interrupted before running upgrade")
            return 1, iso, state

        if not self.discovered_nodes:
            result = command.ensure_remote_scriptlet(self.primary_node)
            if getattr(result, "returncode", 0) != 0:
                return result.returncode, iso, state

        with tempfile.TemporaryDirectory() as td:
            try:
                db_file = schema_repair.materialize_zsv_schema_db_file(target_dir=td)
            except RuntimeError as exc:
                LOG.error("Failed to resolve ZSV schema db file from base ref: %s", exc)
                return 1, iso, state

            schema_precheck_rc = schema_repair.run_schema_mismatch_precheck_for_file(
                address=self.primary_node,
                db_file=db_file,
                runner=self.runner,
            )
        if schema_precheck_rc != 0:
            return schema_precheck_rc, iso, state

        result = self.runner.run_command([
            "bash", "-lc",
            "source scriptlet/bootstrap.sh; "
            f"zsv_upgrade_latest {shlex.quote(self.primary_node)} "
            f"{shlex.quote(iso.download_url)} {shlex.quote(iso.name)} "
            f"{shlex.quote(self._iso_modified_arg(iso))} "
            f"{shlex.quote(iso.size or '')} "
            f"{shlex.quote(self.upgrade_type)}",
        ], cmd_purge_output=True)
        if result.returncode != 0:
            return result.returncode, iso, state

        result = self.runner.run_command([
            "bash", "-lc",
            "source scriptlet/bootstrap.sh; "
            f"zsv_ensure_ui_started {shlex.quote(self.primary_node)}",
        ], cmd_purge_output=True)
        if result.returncode != 0:
            return result.returncode, iso, state

        result = self.runner.run_command([
            "bash", "-lc",
            "source scriptlet/bootstrap.sh; "
            f"zsv_wait_resources_ready {shlex.quote(self.primary_node)} "
            f"{UPGRADE_HEALTH_TIMEOUT_SECONDS} "
            f"{UPGRADE_HEALTH_POLL_INTERVAL_SECONDS}",
        ], cmd_purge_output=True)
        if result.returncode == 0:
            self.record_successful_upgrade(state, iso)
        return result.returncode, iso, state
