import configparser
import logging
import os
import sys

from oslo_utils import strutils

from cbok.cmd import args
from cbok import settings


CONF = settings.CONF
LOG = logging.getLogger(__name__)


class FoundationCommands(args.BaseCommand):

    def __init__(self):
        super().__init__()
        self.executor = os.path.join(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__)))),
                    "foundation/executor.sh")

    def _check_and_reflag_success(self, address_arg):
        stashed_address = None

        try:
            with open("foundation/address", "r") as f:
                stashed_address=f.readline()
                address = stashed_address
        except FileNotFoundError:
            if not address_arg:
                LOG.error("No CBoK found in foundation/address, if you "
                        "confirm that cluster is ready, please use --address and "
                        "its success will be reflaged")
                sys.exit(1)

        if address_arg:
            address = address_arg

        result = self.p_runner.run_command(
            ["bash", "-c", f"source {self.executor}; is_ready {address}"]
        )
        if "Not deployed" in result.stdout:
            LOG.error(f"Not a CBoK target: {address}")
            sys.exit(1)

        if address != stashed_address:
            LOG.info(f"Regenerate the CBoK success flag: {address}")
            with open("foundation/address", "w+") as f:
                f.write(address)

        return address

    @args.action_description("Let cbok running into product")
    @args.args(
        '--mgmt-eth', metavar='<mgmt_eth>', required=True,
        help='Management interface name of the node')
    @args.args(
        '--address', metavar='<address>', required=True,
        help='Running address of cbok')
    def deploy(self, address=None, mgmt_eth=None):
        """Let cbok running into product"""
        result = self.p_runner.run_command(
            ["bash", "-c", f"source {self.executor}; is_ready {address}"]
        )
        if result.returncode == 0 and "Already deployed" in result.stdout:
            LOG.error("CBoK is already ready")
            sys.exit(1)

        LOG.info("Detected clean host, starting deploy CBoK base")

        result = self.p_runner.run_command(
            ["bash", "-c", f"source {self.executor}; install_rsync {address}"]
        )
        LOG.debug(f"rsync installed to {address}")

        if "proxy" in CONF.sections():
            with open("foundation/base/proxy", "w") as f:
                try:
                    proxy_conf = (f"cipher={CONF.get("proxy", "cipher")}\n"
                    f"password={CONF.get("proxy", "password")}\n"
                    f"vps_server={CONF.get("proxy", "vps_server")}\n"
                    f"port={CONF.get("proxy", "port")}")
                except (configparser.NoSectionError,
                        configparser.NoOptionError) as e:
                    LOG.warning("Please fill in the proxy configuration: %s", e)
                    sys.exit(1)
                f.write(proxy_conf)
        else:
            LOG.warning("No proxy configuration found, maybe failed to fetch "
                        "repository")

        LOG.debug("Copying resource, be patient if network seems slow")

        resource_target = "/opt/foundation/"
        result = self.p_runner.run_command(
            ["bash", "-c", f"source {self.executor}; copy_resource_to "
             f"{address} {resource_target} foundation/base"]
        )
        if result.returncode != 0:
            sys.exit(1)
        else:
            LOG.info("Resource copied")

        LOG.info("Building foundation")
        result = self.p_runner.run_command(
            ["bash", "-c", f"source {self.executor}; execute {address} {mgmt_eth}"])
        if result.returncode != 0:
            sys.exit(1)

        with open("foundation/address", "w+") as f:
            f.write(address)
        with open("cbok/bbx/chrome_plugins/auto_login/client/address", "w+") as f:
            f.write(address)

        LOG.info("Deploy successfully ;)")

    @args.action_description("Apply service")
    @args.args(
        '--dev', metavar='<dev>', default=False, required=False,
        help="Optional. Whether to build current working branch")
    @args.args(
        '--rebuild-base', metavar='<rebuild_base>', default=False, required=False,
        help="Optional. Whether to rebuild base image of cbok service")
    @args.args(
        '--address', metavar='<address>', default=None, required=False,
        help="Optional. The address to apply and reflag the CBoK success if "
             "its address not exists")
    @args.args(
        '--service', metavar='<service>', required=True,
        help='service name')
    def apply(self, service=None, address=None, rebuild_base=False, dev=False):
        """Apply service"""
        if rebuild_base and service != "cbok":
            LOG.error("--rebuild-base only used for cbok service")
            sys.exit(1)

        address = self._check_and_reflag_success(address)

        if not os.path.isdir(os.path.join("foundation", service)):
            LOG.error(f"No such service: {service}")
            sys.exit(1)

        LOG.info(f"Applying {service} to {address}")

        dev = strutils.bool_from_string(dev)
        result = self.p_runner.run_command(
            ["bash", "-c",
            f"source {self.executor}; apply_service "
            f"{address} {service} {strutils.bool_from_string(rebuild_base)} "
            f"{dev}"]
        )

        if service == "cbok":
            LOG.info("Re-flagging auto login plugin address")
            with open(
                "cbok/bbx/chrome_plugins/auto_login/client/address",
                "w+") as f:
                f.write(address)

        if result.returncode != 0:
            sys.exit(1)
        elif result.returncode == 0 and "APPLY SUCCESS" in result.stdout:
            LOG.info("Success")

    @args.action_description("Uninstall service")
    @args.args(
        '--address', metavar='<address>', default=None, required=False,
        help="Optional. The address to apply and reflag the CBoK success if "
             "its address not exists")
    @args.args(
        '--service', metavar='<service>', required=True,
        help='service name')
    def remove(self, service=None, address=None):
        """Uninstall service"""

        address = self._check_and_reflag_success(address)

        if not os.path.isdir(os.path.join("foundation", service)):
            LOG.error(f"No such service: {service}")
            sys.exit(1)

        LOG.info(f"Removing {service} from {address}")

        result = self.p_runner.run_command(
            ["bash", "-c",f"source {self.executor}; remove_service {address} {service}"]
        )

        if result.returncode != 0:
            sys.exit(1)
        elif result.returncode == 0 and "REMOVE SUCCESS" in result.stdout:
            LOG.info("Success")
