from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
import logging
import os
import re
import shlex
from urllib.parse import unquote
from urllib.parse import urljoin
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

from django.utils import timezone

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


def _parse_apache_datetime(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%d-%b-%Y %H:%M"):
        try:
            return _aware(datetime.strptime(value.strip(), fmt))
        except ValueError:
            continue
    return None


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


def _is_artifact_url(url, upgrade_type):
    return unquote(urlparse(url).path).lower().endswith(_artifact_extension(upgrade_type))


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
        if line.strip()
    ])


class ZSphereTracker:
    def __init__(
            self,
            name=None,
            upgrade_type=None,
            upgrade_url=None,
            db_file=None,
            primary_node=None,
            runner=None,
        ):
        self.name = _required(name, "name")
        self.upgrade_type = _normalize_upgrade_type(_required(upgrade_type, "upgrade_type"))
        self.upgrade_url = _required(upgrade_url, "upgrade_url")
        self.iso_url = self.upgrade_url
        self.primary_node = _required(primary_node, "primary_node")
        self.nodes = self._normalize_nodes([self.primary_node])
        self.runner = runner or cbok_utils.UnifiedProcessRunner()
        self.schema_db_file = str(db_file).strip() if db_file else ""
        self.discovered_nodes = False

    @staticmethod
    def _normalize_nodes(nodes):
        if isinstance(nodes, str):
            nodes = nodes.split(",")
        normalized = [node.strip() for node in nodes if node and node.strip()]
        if not normalized:
            raise ValueError("at least one ZSphere node is required")
        return normalized

    def get_state(self):
        from cbok.bbx.models import ZSphereUpgradeState

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
        if _is_artifact_url(self.upgrade_url, self.upgrade_type):
            return self._fetch_exact_artifact(self.upgrade_url)
        return self._fetch_latest_from_index(self.upgrade_url)

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

    def _fetch_latest_from_index(self, index_url):
        response = requests.get(index_url, timeout=20, headers=HTTP_HEADERS)
        response.raise_for_status()

        candidates = self._parse_artifact_rows(response.text, response.url)
        if not candidates:
            raise RuntimeError(
                f"No {self.upgrade_type.upper()} artifact found from {index_url}")
        return max(candidates, key=lambda iso: iso.modified_at or timezone.now())

    def _parse_artifact_rows(self, html, base_url):
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        text = soup.get_text("\n")

        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not _is_artifact_url(href, self.upgrade_type):
                continue

            name = unquote(link.get_text(strip=True) or _artifact_name_from_url(href))
            line_match = re.search(
                rf"{re.escape(name)}\s+"
                r"(?P<modified>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})"
                r"(?:\s+(?P<size>\S+))?",
                text,
            )
            modified_at = None
            size = ""
            if line_match:
                modified_at = _parse_apache_datetime(
                    line_match.group("modified"))
                size = line_match.group("size") or ""

            candidates.append(IsoInfo(
                name=name,
                download_url=urljoin(base_url, href),
                modified_at=modified_at,
                size=size,
            ))

        return candidates

    def refresh_state(self, iso):
        state = self.get_state()
        state.last_checked_at = timezone.now()

        update_fields = ["last_checked_at"]
        new_iso_detected = self._is_newer_iso(
            iso.name, iso.modified_at,
            state.latest_iso_name, state.latest_iso_modified_at)
        if new_iso_detected:
            state.latest_iso_name = iso.name
            state.latest_iso_modified_at = iso.modified_at
            update_fields.extend(["latest_iso_name", "latest_iso_modified_at"])

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
        if not state.latest_iso_name:
            return False
        if not state.last_upgraded_iso_name:
            return True
        if cls._is_newer_iso(
                state.latest_iso_name, state.latest_iso_modified_at,
                state.last_upgraded_iso_name,
                state.last_upgraded_iso_modified_at):
            return True
        return False

    @staticmethod
    def _iso_modified_arg(iso):
        if not iso.modified_at:
            return ""
        return timezone.localtime(iso.modified_at).isoformat()

    def check(self):
        iso = self.fetch_latest_iso()
        state, new_iso_detected = self.refresh_state(iso)
        return iso, state, self.needs_upgrade(state, iso), new_iso_detected

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
        iso, state, needs_upgrade, _new_iso_detected = self.check()
        if not needs_upgrade:
            LOG.error("Already up to date, interrupted before running upgrade")
            return 1, iso, state

        if not self.discovered_nodes:
            result = command.ensure_remote_scriptlet(self.primary_node)
            if getattr(result, "returncode", 0) != 0:
                return result.returncode, iso, state

        repair_rc = schema_repair.run_schema_repair_for_file(
            address=self.primary_node,
            db_file=self.schema_db_file,
            runner=self.runner,
        )
        if repair_rc != 0:
            return repair_rc, iso, state

        result = self.runner.run_command([
            "bash", "-lc",
            "source scriptlet/bootstrap.sh; "
            f"zsv_upgrade_latest {shlex.quote(self.primary_node)} "
            f"{shlex.quote(iso.download_url)} {shlex.quote(iso.name)} "
            f"{shlex.quote(self._iso_modified_arg(iso))} "
            f"{shlex.quote(iso.size or '')} "
            f"{shlex.quote(self.upgrade_type)}",
        ], cmd_purge_output=True)
        if result.returncode == 0:
            state.latest_iso_name = iso.name
            state.latest_iso_modified_at = iso.modified_at
            state.last_upgraded_iso_name = iso.name
            state.last_upgraded_iso_modified_at = iso.modified_at
            state.last_upgraded_at = timezone.now()
            state.save(update_fields=[
                "latest_iso_name",
                "latest_iso_modified_at",
                "last_upgraded_iso_name",
                "last_upgraded_iso_modified_at",
                "last_upgraded_at",
            ])
            result = self.runner.run_command([
                "bash", "-lc",
                "source scriptlet/bootstrap.sh; "
                f"zsv_ensure_ui_started {shlex.quote(self.primary_node)}",
            ], cmd_purge_output=True)
            if result.returncode == 0:
                result = self.runner.run_command([
                    "bash", "-lc",
                    "source scriptlet/bootstrap.sh; "
                    f"zsv_wait_resources_ready {shlex.quote(self.primary_node)} "
                    f"{UPGRADE_HEALTH_TIMEOUT_SECONDS} "
                    f"{UPGRADE_HEALTH_POLL_INTERVAL_SECONDS}",
                ], cmd_purge_output=True)
        return result.returncode, iso, state
