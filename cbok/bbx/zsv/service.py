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

from cbok import settings
from cbok import utils as cbok_utils


LOG = logging.getLogger(__name__)

DEFAULT_ENV_NAME = "zsphere-h84r-zsv-5.0.0"
DEFAULT_ISO_URL = (
    "http://storage.zstack.io/mirror/zstack_zsphere_iso_h84r_zsv_5.0.0/latest/"
)
DEFAULT_NODES = ("172.26.53.17", "172.26.53.18")
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


def _conf_get(option, default):
    if settings.CONF.has_option("zsv", option):
        return settings.CONF.get("zsv", option)
    return default


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


def _is_iso_url(url):
    return unquote(urlparse(url).path).lower().endswith(".iso")


def _iso_name_from_url(url):
    return os.path.basename(unquote(urlparse(url).path))


class ZSphereTracker:
    def __init__(self, name=None, iso_url=None, nodes=None, primary_node=None,
                 runner=None):
        self.name = name or _conf_get("env_name", DEFAULT_ENV_NAME)
        self.iso_url = iso_url or _conf_get("iso_url", DEFAULT_ISO_URL)
        self.nodes = self._normalize_nodes(nodes or _conf_get(
            "nodes", ",".join(DEFAULT_NODES)))
        self.primary_node = primary_node or _conf_get(
            "primary_node", self.nodes[0])
        self.runner = runner or cbok_utils.UnifiedProcessRunner()

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
        if _is_iso_url(self.iso_url):
            return self._fetch_exact_iso(self.iso_url)
        return self._fetch_latest_from_index(self.iso_url)

    def _fetch_exact_iso(self, iso_url):
        response = requests.head(
            iso_url, allow_redirects=True, timeout=20, headers=HTTP_HEADERS)
        response.raise_for_status()
        modified_at = None
        if response.headers.get("Last-Modified"):
            modified_at = _aware(parsedate_to_datetime(
                response.headers["Last-Modified"]))
        return IsoInfo(
            name=_iso_name_from_url(response.url or iso_url),
            download_url=response.url or iso_url,
            modified_at=modified_at,
            size=response.headers.get("Content-Length", ""),
        )

    def _fetch_latest_from_index(self, index_url):
        response = requests.get(index_url, timeout=20, headers=HTTP_HEADERS)
        response.raise_for_status()

        candidates = self._parse_iso_rows(response.text, response.url)
        if not candidates:
            raise RuntimeError(f"No ISO found from {index_url}")
        return max(candidates, key=lambda iso: iso.modified_at or timezone.now())

    def _parse_iso_rows(self, html, base_url):
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        text = soup.get_text("\n")

        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not _is_iso_url(href):
                continue

            name = unquote(link.get_text(strip=True) or _iso_name_from_url(href))
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

    def check(self):
        iso = self.fetch_latest_iso()
        state, new_iso_detected = self.refresh_state(iso)
        return iso, state, self.needs_upgrade(state, iso), new_iso_detected

    def ensure_scriptlet(self, command):
        for node in self.nodes:
            result = command.ensure_remote_scriptlet(node)
            if getattr(result, "returncode", 0) != 0:
                return result
        return None

    def status(self, command):
        nodes = " ".join(shlex.quote(node) for node in self.nodes)
        result = self.runner.run_command([
            "bash", "-lc",
            f"source scriptlet/bootstrap.sh; zsv_nodes_status {nodes}",
        ], cmd_purge_output=True)
        return result.returncode

    def upgrade(self, command):
        iso, state, needs_upgrade, _new_iso_detected = self.check()
        if not needs_upgrade:
            LOG.error("Already up to date, interrupted before running upgrade")
            return 1, iso, state

        result = command.ensure_remote_scriptlet(self.primary_node)
        if getattr(result, "returncode", 0) != 0:
            return result.returncode, iso, state

        result = self.runner.run_command([
            "bash", "-lc",
            "source scriptlet/bootstrap.sh; "
            f"zsv_upgrade_latest {shlex.quote(self.primary_node)} "
            f"{shlex.quote(iso.download_url)} {shlex.quote(iso.name)}",
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
        return result.returncode, iso, state
