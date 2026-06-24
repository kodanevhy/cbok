import getpass
import logging
import os
from pathlib import Path
import shlex
import tempfile
from urllib.parse import unquote
from urllib.parse import urlparse

from django.utils import timezone

from cbok import settings
from cbok.bbx.zsv.agent_replace import DEFAULT_BACKUP_ROOT
from cbok.bbx.zsv.agent_replace import DEFAULT_KVM_VIRTUALENV
from cbok.bbx.zsv.agent_replace import DEFAULT_SITE_PACKAGES
from cbok.bbx.zsv.agent_replace import run_agent_replace_flow
from cbok.bbx.zsv import UPGRADE_TYPES
from cbok.bbx.zsv import ZSphereTracker
from cbok.bbx.zsv.service import discover_management_nodes
from cbok.bbx.zsv.compile import DEFAULT_REMOTE_LIB
from cbok.bbx.zsv.compile import run_compile_flow
from cbok.bbx.zsv.groovy_test import run_groovy_test_flow
from cbok.cmd import args
from cbok.cmd import base


LOG = logging.getLogger(__name__)


def _conf_get(section: str, option: str, default: str) -> str:
    conf = settings.CONF
    if conf.has_section(section) and conf.has_option(section, option):
        return conf.get(section, option).strip()
    return default


def _zsv_deploy_conf(option: str, default: str) -> str:
    return _conf_get("zsv_deploy", option, default)


def _upgrade_type_from_state(state):
    for value in (
            getattr(state, "last_upgraded_iso_name", ""),
            getattr(state, "latest_iso_name", ""),
            getattr(state, "iso_url", ""),
    ):
        path = unquote(urlparse(value or "").path).lower()
        if path.endswith(".iso"):
            return "iso"
        if path.endswith(".bin"):
            return "bin"
    return "bin"


def _latest_upgrade_state(name=None, primary_node=None):
    from django.db.models import Q
    from cbok.bbx.models import ZSphereUpgradeState

    qs = ZSphereUpgradeState.objects.all()
    if name:
        qs = qs.filter(name=name)
    elif primary_node:
        qs = qs.filter(Q(name=primary_node) | Q(nodes__contains=primary_node))
    return qs.order_by("-last_upgraded_at", "-last_checked_at", "-id").first()


def _local_public_keys():
    ssh_dir = Path.home() / ".ssh"
    keys = []
    seen = set()
    if not ssh_dir.is_dir():
        return keys

    for path in sorted(ssh_dir.glob("*.pub")):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            key = line.strip()
            if not key or key.startswith("#") or key in seen:
                continue
            seen.add(key)
            keys.append(key)
    return keys


def _upgrade_command(tracker):
    parts = [
        "cbok",
        "zsv",
        "upgrade",
        "--name",
        shlex.quote(tracker.name),
        "--upgrade-type",
        shlex.quote(tracker.upgrade_type),
        "--upgrade-url",
        shlex.quote(tracker.upgrade_url),
        "--db-file",
        shlex.quote(tracker.schema_db_file),
        "--primary-node",
        shlex.quote(tracker.primary_node),
    ]
    return " ".join(parts)


def _print_iso(tracker, iso, state, needs_upgrade):
    def _fmt(dt):
        if not dt:
            return "never"
        return timezone.localtime(dt).isoformat()

    latest_iso_modified = _fmt(iso.modified_at) if iso.modified_at else "unknown"
    upgraded_iso_modified = _fmt(state.last_upgraded_iso_modified_at)
    upgraded_at = _fmt(state.last_upgraded_at)

    print(f"Name:         {iso.name}")
    print(f"Upgrade type: {tracker.upgrade_type}")
    print(f"DB:           {upgraded_iso_modified}")
    print(f"URL:          {latest_iso_modified}")
    print(f"Last sync at: {upgraded_at}")
    if needs_upgrade:
        print(f"---\n{_upgrade_command(tracker)}")


class ZSphereCommands(base.BaseCommand):
    def _tracker(
            self,
            name=None,
            upgrade_type=None,
            upgrade_url=None,
            primary_node=None,
            db_file=None,
    ):
        return ZSphereTracker(
            name=name,
            upgrade_type=upgrade_type,
            upgrade_url=upgrade_url,
            db_file=db_file,
            primary_node=primary_node,
            runner=self.p_runner,
        )

    @args.action_description("Check whether ZSphere needs upgrade")
    @args.args(
        "--primary-node", metavar="<primary_node>", required=True,
        help="Node used to identify the tracked environment")
    def check(self, primary_node=None):
        """Check whether ZSphere needs upgrade"""
        if not primary_node:
            LOG.error("check requires --primary-node.")
            return 1
        state = _latest_upgrade_state(primary_node=primary_node)
        if not state:
            LOG.error(
                "No tracked ZSphere upgrade record found for primary node %s.",
                primary_node)
            return 1

        tracker = self._tracker(
            state.name,
            _upgrade_type_from_state(state),
            state.iso_url,
            primary_node,
            db_file=None,
        )
        iso, state, needs_upgrade, _new_iso_detected = tracker.check()
        _print_iso(tracker, iso, state, needs_upgrade)
        return 0

    @args.action_description("Show status of tracked ZSphere nodes")
    @args.args(
        "--primary-node", metavar="<primary_node>", required=True,
        help="Node used to discover ZSphere nodes")
    def status(self, primary_node=None):
        """Show status of tracked ZSphere nodes"""
        if not primary_node:
            LOG.error("status requires --primary-node.")
            return 1
        result = self.ensure_remote_scriptlet(primary_node)
        if getattr(result, "returncode", 0) != 0:
            return getattr(result, "returncode", 1) or 1
        nodes = discover_management_nodes(primary_node, self.p_runner)
        if not nodes:
            LOG.warning(
                "No management nodes discovered from primary node %s; "
                "falling back to primary node only",
                primary_node)
            nodes = [primary_node]
        elif primary_node not in nodes:
            nodes.insert(0, primary_node)
        nodes_arg = " ".join(shlex.quote(node) for node in nodes)
        result = self.p_runner.run_command([
            "bash", "-lc",
            f"source scriptlet/bootstrap.sh; zsv_nodes_status {nodes_arg}",
        ], cmd_purge_output=True)
        return result.returncode

    @args.action_description("Restart ZSphere management node")
    @args.args(
        "--address", metavar="<ip>", required=True,
        help="Target ZSphere/ZStack management node (root SSH)")
    def restart_mn(self, address=None):
        """Restart ZSphere management node"""
        if not address:
            LOG.error("restart_mn requires --address.")
            return 1
        result = self.ensure_remote_scriptlet(address)
        if getattr(result, "returncode", 0) != 0:
            return getattr(result, "returncode", 1) or 1
        result = self.p_runner.run_command([
            "bash", "-lc",
            "source scriptlet/bootstrap.sh; "
            f"zsv_restart_mn {shlex.quote(address)}",
        ], cmd_purge_output=False)
        return getattr(result, "returncode", 1) or 0

    @args.action_description("Install local SSH public keys on all ZSphere nodes")
    @args.args(
        "--primary-node", metavar="<primary_node>", required=True,
        help="Node used to discover ZSphere nodes")
    @args.args(
        "--password", metavar="<password>", required=False,
        help="Root password for all nodes; prompts securely when omitted")
    def install_ssh_key(self, primary_node=None, password=None):
        """Install local SSH public keys on all ZSphere nodes"""
        if not primary_node:
            LOG.error("install_ssh_key requires --primary-node.")
            return 1

        keys = _local_public_keys()
        if not keys:
            LOG.error("No local public keys found under ~/.ssh/*.pub.")
            return 1

        if password is None:
            password = getpass.getpass("Root password for all ZSphere nodes: ")
        if not password:
            LOG.error("Password is required.")
            return 1

        old_sshpass = os.environ.get("SSHPASS")
        os.environ["SSHPASS"] = password
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
                tmp.write("\n".join(keys) + "\n")
                key_file = tmp.name

            result = self.ensure_remote_scriptlet(primary_node)
            if getattr(result, "returncode", 0) != 0:
                return getattr(result, "returncode", 1) or 1

            nodes = discover_management_nodes(primary_node, self.p_runner)
            if not nodes:
                LOG.warning(
                    "No management nodes discovered from primary node %s; "
                    "falling back to primary node only",
                    primary_node)
                nodes = [primary_node]
            elif primary_node not in nodes:
                nodes.insert(0, primary_node)

            for node in nodes:
                result = self.ensure_remote_scriptlet(node)
                if getattr(result, "returncode", 0) != 0:
                    return getattr(result, "returncode", 1) or 1
                result = self.p_runner.run_command([
                    "bash", "-lc",
                    "source scriptlet/bootstrap.sh; "
                    f"zsv_authorize_public_keys {shlex.quote(node)} {shlex.quote(key_file)}",
                ], cmd_purge_output=False)
                if getattr(result, "returncode", 0) != 0:
                    return getattr(result, "returncode", 1) or 1

            LOG.info("Installed %s local public key(s) on %s node(s).", len(keys), len(nodes))
            return 0
        finally:
            try:
                if "key_file" in locals():
                    os.unlink(key_file)
            finally:
                if old_sshpass is None:
                    os.environ.pop("SSHPASS", None)
                else:
                    os.environ["SSHPASS"] = old_sshpass

    @args.action_description("Upgrade ZSphere primary node with latest BIN/ISO package")
    @args.args(
        "--primary-node", metavar="<primary_node>", required=True,
        help="Node where upgrade runs and discovers other MNs")
    @args.args(
        "--upgrade-type", metavar="<type>", required=True,
        choices=UPGRADE_TYPES,
        help="Upgrade package type: bin or iso")
    @args.args(
        "--upgrade-url", metavar="<url>", required=True,
        help="BIN/ISO index URL or exact package URL")
    @args.args(
        "--db-file", metavar="<path>", required=True,
        help="Local ZSV schema SQL file used for pre-upgrade Flyway checksum repair")
    @args.args(
        "--name", metavar="<name>", required=True,
        help="Tracked environment name")
    def upgrade(
            self,
            name=None,
            upgrade_type=None,
            upgrade_url=None,
            db_file=None,
            primary_node=None,
    ):
        """Upgrade ZSphere primary node with latest BIN/ISO package"""
        tracker = self._tracker(
            name,
            upgrade_type,
            upgrade_url,
            primary_node,
            db_file=db_file,
        )
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
        "--zstack-root", metavar="<dir>", required=True,
        help="ZStack checkout root for the current worktree")
    @args.args(
        "--premium-root", metavar="<dir>", required=True,
        help="premium checkout root for the current worktree")
    @args.args(
        "--no-deploy", action="store_true",
        help="Build and skip remote backup/copy")
    def compile(
            self,
            address=None,
            no_deploy=False,
            zstack_root=None,
            premium_root=None,
    ):
        """
        Build changed modules in a remote Docker worktree container.
        Deploy copies JARs to remote WEB-INF/lib (with backup).
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
            remote_lib=_zsv_deploy_conf("remote_lib", DEFAULT_REMOTE_LIB),
            no_deploy=no_deploy,
            zstack_root=zstack_root,
            premium_root=premium_root,
            runner=self.p_runner,
        )

    @args.action_description(
        "Run a ZStack Groovy integration test in a reusable worktree Docker container")
    @args.args(
        "--zstack-branch", metavar="<git-ref>", required=True,
        help="ZStack branch/ref to test")
    @args.args(
        "--premium-branch", metavar="<git-ref>", required=True,
        help="premium branch/ref to test")
    @args.args(
        "--test-class", metavar="<fqcn>", required=True,
        help="Groovy Test or Case class; Case mode requires fully qualified class name")
    @args.args(
        "--test-mode", choices=("auto", "case", "suite"), default="auto",
        help="auto: *Test runs as a suite, other classes run as designated Case")
    @args.args(
        "--zstack-repo", metavar="<dir>", required=True,
        help="Source ZStack repo for the current worktree")
    @args.args(
        "--premium-repo", metavar="<dir>", required=True,
        help="Source premium repo for the current worktree")
    @args.args(
        "--work-root", metavar="<dir>", required=False,
        default=None,
        help="Reusable run directory; default is /tmp/cbok-zsv-groovy-test-<zstack-branch>-<premium-branch>")
    @args.args(
        "--run-id", metavar="<name>", required=False,
        default=None,
        help="Stable suffix for Docker network/container and default work root")
    @args.args(
        "--refresh-worktree", action="store_true",
        help="Replace the generated zstack/premium worktree before the run")
    def groovy_test(
            self,
            zstack_branch=None,
            premium_branch=None,
            test_class=None,
            test_mode="auto",
            zstack_repo=None,
            premium_repo=None,
            work_root=None,
            run_id=None,
            refresh_worktree=False,
    ):
        """Run a ZStack Groovy integration test in a reusable Docker container"""
        return run_groovy_test_flow(
            zstack_branch=zstack_branch,
            premium_branch=premium_branch,
            test_class=test_class,
            test_mode=test_mode,
            zstack_repo=zstack_repo,
            premium_repo=premium_repo,
            work_root=work_root,
            run_id=run_id,
            keep_worktree=not refresh_worktree,
            runner=self.p_runner,
        )

    @args.action_description(
        "Replace changed kvmagent/zstacklib files on all ZSV nodes")
    @args.args(
        "--primary-node", metavar="<primary_node>", required=True,
        help="Node used to discover ZSphere nodes")
    @args.args(
        "--utility-root", metavar="<dir>", required=True,
        help="zstack-utility checkout root for the current worktree")
    @args.args(
        "--dry-run", action="store_true",
        help="Only print detected files and nodes")
    @args.args(
        "--no-restart", action="store_true",
        help="Copy files and compile, but do not restart zstack-kvmagent")
    def replace_agent(
            self,
            primary_node=None,
            utility_root=None,
            dry_run=False,
            no_restart=False,
    ):
        """
        Replace changed kvmagent/zstacklib files on all ZSV nodes.
        """
        if not primary_node:
            LOG.error("replace_agent requires --primary-node.")
            return 1
        if not utility_root:
            LOG.error("replace_agent requires --utility-root.")
            return 1
        discovered = discover_management_nodes(primary_node, self.p_runner)
        target_nodes = ",".join(discovered or [primary_node])
        return run_agent_replace_flow(
            utility_root=utility_root,
            nodes=target_nodes,
            site_packages=_zsv_deploy_conf("site_packages", DEFAULT_SITE_PACKAGES),
            kvm_virtualenv=_zsv_deploy_conf("kvm_virtualenv", DEFAULT_KVM_VIRTUALENV),
            backup_root=_zsv_deploy_conf("backup_root", DEFAULT_BACKUP_ROOT),
            dry_run=dry_run,
            no_restart=no_restart,
            runner=self.p_runner,
            ensure_remote_scriptlet=None if dry_run else self.ensure_remote_scriptlet,
        )
