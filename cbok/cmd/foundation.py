import logging
import os
import sys

from cbok.cmd import args
from cbok import utils


LOG = logging.getLogger(__name__)


class FoundationCommands:

    @args.action_description("Let cbok running into product")
    @args.args(
        '--address', metavar='<address>', required=True,
        help='Running address of cbok')
    def deploy(self, address=None):
        """Let cbok running into product"""
        try:

            executor = os.path.join(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__)))),
                        "foundation/executor.sh")
            resource_target = "/opt/"
            result = utils.execute(
                ["bash", "-c", f"source {executor}; copy_resource_to \
                    {address} {resource_target}"]
            )
            if result.returncode != 0:
                LOG.error(result.stderr)
                sys.exit(1)
            else:
                LOG.info("Resource copied")

            LOG.info("Building foundation, logging at remote workspace home")
            result = utils.execute(
                ["bash", "-c", f"source {executor}; execute {address} \
                    {os.path.join(resource_target, 'foundation')}"])
            if result.returncode != 0:
                LOG.error("Please trace log for details")
                sys.exit(1)

        except Exception:
            raise
