import argparse
import logging
import os
import sys

from cbok.apps.bbx.put_patch import main as put_patch
from cbok.apps.bbx.ut import main as ut
from cbok import settings

LOG = logging.getLogger("bbx-cli")


def setup_logging(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )
    handler.setFormatter(formatter)
    LOG.addHandler(handler)
    LOG.setLevel(level)


def action_description(desc):
    """Decorator to attach a description to a method."""
    def wrapper(func):
        func._description = desc
        return func
    return wrapper


def args(*arg_args, **arg_kwargs):
    """Decorator to attach CLI args to a method."""
    def wrapper(func):
        if not hasattr(func, '_args'):
            func._args = []
        func._args.append((arg_args, arg_kwargs))
        return func
    return wrapper


class PatchCommands:

    @action_description("Upload the patch changes to a running env")
    @args(
        '--node', metavar='<node>', default=None,
        help='The node locate replica (Optional)')
    @args(
        '--service', metavar='<service>', required=True,
        help='(sub-)service like a deployment split from a project')
    @args(
        '--address', metavar='<address>', required=True,
        help='Address of env, or an os-in-os, which you are already '
             'authorized')
    def put(self, address=None, service=None, node=None):
        """Upload the patch changes to a running env"""
        try:
            put_patch.run(address, service, node)
        except Exception:
            raise

    @action_description("Solution of unit test")
    @args(
        '--tox-command', metavar='<tox_command>', required=True,
        help='Tox command bebind of tox -e, see tox --help for details')
    @args(
        '--project', metavar='<project>', required=True,
        help='A project located in es')
    def ut(self, project, tox_command):
        """Solution of unit test """
        try:
            ut.run(project, tox_command)
        except Exception:
            raise


CATEGORIES = {
    'patch': PatchCommands,
}


def main():
    assert os.getcwd() == settings.BASE_DIR

    parser = argparse.ArgumentParser(description="CBoK BBX CLI")
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    subparsers = parser.add_subparsers(dest='category', required=True)

    for cat_name, cls in CATEGORIES.items():
        cat_parser = subparsers.add_parser(cat_name)
        cat_subparsers = cat_parser.add_subparsers(dest='command',
                                                   required=True)
        obj = cls()
        for attr_name in dir(obj):
            if attr_name.startswith('_'):
                continue
            method = getattr(obj, attr_name)
            if callable(method) and hasattr(method, '_args'):
                cmd_parser = cat_subparsers.add_parser(
                    attr_name, help=getattr(method, '_description', ''))
                for arg_args, arg_kwargs in method._args:
                    cmd_parser.add_argument(*arg_args, **arg_kwargs)
                cmd_parser.set_defaults(func=method)

    args = parser.parse_args()

    setup_logging(debug=args.debug)
    LOG.info("Starting BBX CLI (debug=%s)", args.debug)

    try:
        func = getattr(args, 'func', None)
        if func:
            kwargs = {k: v for k, v in vars(args).items()
                      if k not in ['category', 'command', 'func', 'debug']}
            return_code = func(**kwargs)
            sys.exit(return_code)
    except Exception as e:
        LOG.exception("Command failed")
        sys.exit(1)
