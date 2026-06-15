import logging
import shlex

from django.utils import timezone

from cbok.bbx.zsv.agent_replace import DEFAULT_BACKUP_ROOT
from cbok.bbx.zsv.agent_replace import DEFAULT_KVM_VIRTUALENV
from cbok.bbx.zsv.agent_replace import DEFAULT_SITE_PACKAGES
from cbok.bbx.zsv.agent_replace import default_utility_root
from cbok.bbx.zsv.agent_replace import run_agent_replace_flow
from cbok.bbx.zsv import DEFAULT_ISO_URL
from cbok.bbx.zsv import DEFAULT_NODES
from cbok.bbx.zsv import ZSphereTracker
from cbok.bbx.zsv.compile import DEFAULT_REMOTE_LIB
from cbok.bbx.zsv.compile import run_compile_flow
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

    print(f"Name:         {iso.name}")
    print(f"DB:           {upgraded_iso_modified}")
    print(f"URL:          {latest_iso_modified}")
    print(f"Last sync at: {upgraded_at}")
    if needs_upgrade:
        print(f"---\n{_upgrade_command(tracker)}")


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

    @args.action_description(
        "Build changed ZStack modules, copy JARs to remote Tomcat lib")
    @args.args(
        "--address", metavar="<ip>", required=False,
        help="Target ZSphere/ZStack node (root SSH); required for deploy "
             "(omit with --no-deploy)")
    @args.args(
        "--remote-lib", metavar="<dir>", required=False,
        default=DEFAULT_REMOTE_LIB,
        help=f"Remote WEB-INF/lib (default: {DEFAULT_REMOTE_LIB})")
    @args.args(
        "--zstack-root", metavar="<dir>", required=False,
        help="ZStack checkout root (default: $Workspace/Cursor/zs/zstack)")
    @args.args(
        "--docker-container", metavar="<id>", required=False,
        help="Override [zsv_compile] docker_container; use none to build on host")
    @args.args(
        "--docker-zstack-root", metavar="<dir>", required=False,
        help="Override [zsv_compile] docker_zstack_root")
    @args.args(
        "--no-deploy", action="store_true",
        help="Build locally but skip remote backup/copy")
    def compile(
            self,
            address=None,
            remote_lib=None,
            no_deploy=False,
            zstack_root=None,
            docker_container=None,
            docker_zstack_root=None,
    ):
        """
        Build with mvn -DskipTests clean install using auto-detected modules.
        Optional Docker: [zsv_compile]. Deploy copies JARs to remote WEB-INF/lib (with backup).
        """
        deploy = not no_deploy
        if deploy:
            if not address:
                LOG.error(
                    "Deploy requires --address (or use --no-deploy).")
                return 1
            res = self.ensure_remote_scriptlet(address)
            if getattr(res, "returncode", 0) != 0:
                return getattr(res, "returncode", 1) or 1
        return run_compile_flow(
            address=address if deploy else None,
            remote_lib=remote_lib or DEFAULT_REMOTE_LIB,
            no_deploy=no_deploy,
            zstack_root=zstack_root,
            docker_container_override=docker_container,
            docker_zstack_root_override=docker_zstack_root,
            runner=self.p_runner,
        )

    @args.action_description(
        "Replace changed kvmagent/zstacklib files on all ZSV nodes")
    @args.args(
        "--nodes", metavar="<nodes>", required=False,
        help=f"Comma separated node IPs (default: {','.join(DEFAULT_NODES)})")
    @args.args(
        "--utility-root", metavar="<dir>", required=False,
        default=None,
        help="zstack-utility checkout root (default: workspace zstack-utility)")
    @args.args(
        "--base-ref", metavar="<git-ref>", required=False,
        help="Git base ref for current branch changes (default: upstream/origin branch)")
    @args.args(
        "--site-packages", metavar="<dir|auto>", required=False,
        default=DEFAULT_SITE_PACKAGES,
        help=f"Remote KVM site-packages path (default: {DEFAULT_SITE_PACKAGES})")
    @args.args(
        "--kvm-virtualenv", metavar="<dir>", required=False,
        default=DEFAULT_KVM_VIRTUALENV,
        help=f"Remote KVM virtualenv (default: {DEFAULT_KVM_VIRTUALENV})")
    @args.args(
        "--backup-root", metavar="<dir>", required=False,
        default=DEFAULT_BACKUP_ROOT,
        help=f"Remote backup root (default: {DEFAULT_BACKUP_ROOT})")
    @args.args(
        "--dry-run", action="store_true",
        help="Only print detected files and nodes")
    @args.args(
        "--no-restart", action="store_true",
        help="Copy files and compile, but do not restart zstack-kvmagent")
    def replace_agent(
            self,
            nodes=None,
            utility_root=None,
            base_ref=None,
            site_packages=None,
            kvm_virtualenv=None,
            backup_root=None,
            dry_run=False,
            no_restart=False,
    ):
        """
        Replace changed kvmagent/zstacklib files on all ZSV nodes.
        """
        target_nodes = nodes or ",".join(self._tracker().nodes)
        root = utility_root or default_utility_root()
        return run_agent_replace_flow(
            utility_root=root,
            nodes=target_nodes,
            base_ref=base_ref,
            site_packages=site_packages or DEFAULT_SITE_PACKAGES,
            kvm_virtualenv=kvm_virtualenv or DEFAULT_KVM_VIRTUALENV,
            backup_root=backup_root or DEFAULT_BACKUP_ROOT,
            dry_run=dry_run,
            no_restart=no_restart,
            runner=self.p_runner,
            ensure_remote_scriptlet=None if dry_run else self.ensure_remote_scriptlet,
        )
