import logging
import shlex

from django.utils import timezone

from cbok.bbx.zsv import DEFAULT_ISO_URL
from cbok.bbx.zsv import DEFAULT_NODES
from cbok.bbx.zsv import ZSphereTracker
from cbok.cmd import args
from cbok.cmd import base


LOG = logging.getLogger(__name__)


def _upgrade_command(tracker):
    return " ".join([
        "cbok",
        "zsv",
        "upgrade",
        "--name",
        shlex.quote(tracker.name),
        "--iso-url",
        shlex.quote(tracker.iso_url),
        "--nodes",
        shlex.quote(",".join(tracker.nodes)),
        "--primary-node",
        shlex.quote(tracker.primary_node),
    ])


def _print_iso(tracker, iso, state, needs_upgrade):
    def _fmt(dt):
        if not dt:
            return "never"
        return timezone.localtime(dt).isoformat()

    latest_iso_modified = _fmt(iso.modified_at) if iso.modified_at else "unknown"
    upgraded_iso_modified = _fmt(state.last_upgraded_iso_modified_at)
    upgraded_at = _fmt(state.last_upgraded_at)

    print(f"Upgrade ISO: {iso.name}")
    print(f"DB upgraded ISO modified at: {upgraded_iso_modified}")
    print(f"URL latest ISO modified at: {latest_iso_modified}")
    print(f"Last upgraded at: {upgraded_at}")
    print(f"Need upgrade: {'yes' if needs_upgrade else 'no'}")
    if needs_upgrade:
        print(f"Manual upgrade command: {_upgrade_command(tracker)}")


class ZSphereCommands(base.BaseCommand):
    def _tracker(self, name=None, iso_url=None, nodes=None, primary_node=None):
        return ZSphereTracker(
            name=name,
            iso_url=iso_url,
            nodes=nodes,
            primary_node=primary_node,
            runner=self.p_runner,
        )

    @args.action_description("Check whether ZSphere needs upgrade")
    @args.args(
        "--primary-node", metavar="<primary_node>", required=False,
        help=f"Node where zstack-upgrade runs (default: {DEFAULT_NODES[0]})")
    @args.args(
        "--nodes", metavar="<nodes>", required=False,
        help=f"Comma separated node IPs (default: {','.join(DEFAULT_NODES)})")
    @args.args(
        "--iso-url", metavar="<iso_url>", required=False,
        help=f"ISO index URL or exact ISO URL (default: {DEFAULT_ISO_URL})")
    @args.args(
        "--name", metavar="<name>", required=False,
        help="Tracked environment name")
    def check(self, name=None, iso_url=None, nodes=None, primary_node=None):
        """Check whether ZSphere needs upgrade"""
        tracker = self._tracker(name, iso_url, nodes, primary_node)
        iso, state, needs_upgrade, _new_iso_detected = tracker.check()
        _print_iso(tracker, iso, state, needs_upgrade)
        return 0

    @args.action_description("Show status of tracked ZSphere nodes")
    @args.args(
        "--primary-node", metavar="<primary_node>", required=False,
        help=f"Node where zstack-upgrade runs (default: {DEFAULT_NODES[0]})")
    @args.args(
        "--nodes", metavar="<nodes>", required=False,
        help=f"Comma separated node IPs (default: {','.join(DEFAULT_NODES)})")
    @args.args(
        "--iso-url", metavar="<iso_url>", required=False,
        help=f"ISO index URL or exact ISO URL (default: {DEFAULT_ISO_URL})")
    @args.args(
        "--name", metavar="<name>", required=False,
        help="Tracked environment name")
    def status(self, name=None, iso_url=None, nodes=None, primary_node=None):
        """Show status of tracked ZSphere nodes"""
        tracker = self._tracker(name, iso_url, nodes, primary_node)
        return tracker.status(self)

    @args.action_description("Upgrade ZSphere primary node to latest ISO")
    @args.args(
        "--primary-node", metavar="<primary_node>", required=False,
        help=f"Node where zstack-upgrade runs (default: {DEFAULT_NODES[0]})")
    @args.args(
        "--nodes", metavar="<nodes>", required=False,
        help=f"Comma separated node IPs (default: {','.join(DEFAULT_NODES)})")
    @args.args(
        "--iso-url", metavar="<iso_url>", required=False,
        help=f"ISO index URL or exact ISO URL (default: {DEFAULT_ISO_URL})")
    @args.args(
        "--name", metavar="<name>", required=False,
        help="Tracked environment name")
    def upgrade(self, name=None, iso_url=None, nodes=None, primary_node=None):
        """Upgrade ZSphere primary node to latest ISO"""
        tracker = self._tracker(name, iso_url, nodes, primary_node)
        returncode, iso, state = tracker.upgrade(self)
        if returncode == 0:
            LOG.info("Upgrade command finished: %s", iso.name)
        else:
            LOG.error("Upgrade command was not completed: %s", iso.name)
        return returncode
