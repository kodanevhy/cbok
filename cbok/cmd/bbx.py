from cbok.apps.bbx.put_patch import main as put_patch
from cbok.apps.bbx.ut import main as ut
from cbok.cmd import args


class PatchCommands:

    @args.action_description("Upload the patch changes to a running env")
    @args.args(
        '--node', metavar='<node>', default=None,
        help='The node locate replica (Optional)')
    @args.args(
        '--service', metavar='<service>', required=True,
        help='(sub-)service like a deployment split from a project')
    @args.args(
        '--address', metavar='<address>', required=True,
        help='Address of env, or an os-in-os, which you are already '
             'authorized')
    def put(self, address=None, service=None, node=None):
        """Upload the patch changes to a running env"""
        try:
            put_patch.run(address, service, node)
        except Exception:
            raise

    @args.action_description("Solution of unit test")
    @args.args(
        '--tox-command', metavar='<tox_command>', required=True,
        help='Tox command bebind of tox -e, see tox --help for details')
    @args.args(
        '--project', metavar='<project>', required=True,
        help='A project located in es')
    def ut(self, project, tox_command):
        """Solution of unit test """
        try:
            ut.run(project, tox_command)
        except Exception:
            raise
