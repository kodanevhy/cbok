import logging
import os
import sys

from oslo_utils import strutils

from cbok.cmd import args
from cbok import utils


LOG = logging.getLogger(__name__)


class FoundationCommands:

    def __init__(self):
        self.executor = os.path.join(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__)))),
                    "foundation/executor.sh")

    @args.action_description("Let cbok running into product")
    @args.args(
        '--mgmt-eth', metavar='<mgmt_eth>', required=True,
        help='Management interface name of the node')
    @args.args(
        '--address', metavar='<address>', required=True,
        help='Running address of cbok')
    def deploy(self, address=None, mgmt_eth=None):
        """Let cbok running into product"""
        result = utils.execute(
            ["bash", "-c", f"source {self.executor}; is_ready {address}"]
        )
        if result.returncode == 0:
            LOG.error("CBoK is already ready")
            sys.exit(1)

        LOG.info("Starting deploy CBoK base")
        LOG.debug("Copying resource, be patient if network seems slow")
        
        resource_target = "/opt/foundation/"
        result = utils.execute(
            ["bash", "-c", f"source {self.executor}; copy_resource_to \
                {address} {resource_target} foundation/base"]
        )
        if result.returncode != 0:
            LOG.error(result.stderr)
            sys.exit(1)
        else:
            LOG.info("Resource copied")

        LOG.info("Building foundation")
        result = utils.execute(
            ["bash", "-c", f"source {self.executor}; execute {address} {mgmt_eth}"])
        if result.returncode != 0:
            LOG.error("Unexpected error, Please trace log remote "
                        "workspace home for details")
            sys.exit(1)

        with open("foundation/address", "w+") as f:
            f.write(address)

        LOG.info("Congradulations! deploy successfully")

    @args.action_description("Apply service")
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
    def apply(self, service=None, address=None, rebuild_base=False):
        """Apply service"""
        if rebuild_base and service != "cbok":
            LOG.error("--rebuild-base only used for cbok service")
            sys.exit(1)

        try:
            with open("foundation/address", "r") as f:
                address=f.readline()
        except FileNotFoundError:
            if not address:
                LOG.error("No CBoK found in foundation/address, if you "
                          "confirm that cluster is ready, please use --address and "
                          "its success will be reflaged")
                sys.exit(1)

        result = utils.execute(
            ["bash", "-c", f"source {self.executor}; is_ready {address}"]
        )
        if result.returncode != 0:
            LOG.error("Unreachable, or not a CBoK target")
            sys.exit(1)
        elif address and not os.path.exists("foundation/address"):
            LOG.info("Regenerate the CBoK success flag")
            with open("foundation/address", "w+") as f:
                f.write(address)

        if not os.path.isdir(os.path.join("foundation", service)):
            LOG.error(f"No such service: {service}")
            sys.exit(1)

        LOG.info(f"Applying {service} to {address}")

        result = utils.execute(
            ["bash", "-c",f"source {self.executor}; apply_service {address} {service} {strutils.bool_from_string(rebuild_base)}"]
        )

        if "Failed to copy resource" in result.stderr:
            LOG.error(result.stderr)
            LOG.error("Failed to copy resource")
            sys.exit(1)
        elif "Not allowed: base" in result.stderr:
            LOG.error(result.stderr)
            LOG.error("Not allowed: base")
            sys.exit(1)
        elif result.returncode == 0 and "APPLY SUCCESS" in result.stdout:
            LOG.info("Success")
        else:
            LOG.error(result.stderr)
            LOG.error("Unexpected error, Please trace log remote "
                      "workspace home for details")
            sys.exit(1)
