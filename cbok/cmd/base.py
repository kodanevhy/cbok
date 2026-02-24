import argparse
import logging
import os
import sys

import django

from cbok.cmd import bbx
from cbok.cmd import foundation
from cbok import utils as cbok_utils


LOG = logging.getLogger(__name__)

CATEGORIES = {
    'patch': bbx.PatchCommands,
    'bin': bbx.BinCommands,
    'openstack': bbx.OpenStackCommands,
    'foundation': foundation.FoundationCommands,
    'proxy': bbx.ProxyCommands,
}


def setup_logging_level(debug=False):
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    for handler in root.handlers:
        handler.setLevel(logging.DEBUG if debug else logging.INFO)


def main():
    # To make logging sense, the logger only effective
    # after Django setup
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cbok.settings")
    django.setup()

    os.chdir(cbok_utils.assert_cbok_home())

    parser = argparse.ArgumentParser(prog="cbok", description="CBoK CLI")
    # override Django DEBUG configuration, cuz if we in
    # production (DEBUG=False), the cbok cli also can be debug
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    subparsers = parser.add_subparsers(dest='subcommand', required=True)

    for cat_name, cls in CATEGORIES.items():
        cat_parser = subparsers.add_parser(cat_name, help=f"{cat_name} commands")
        cat_subparsers = cat_parser.add_subparsers(dest='command', required=True)
        obj = cls()
        for attr_name in dir(obj):
            if attr_name.startswith('_'):
                continue
            method = getattr(obj, attr_name)
            if callable(method):
                cmd_parser = cat_subparsers.add_parser(
                    attr_name, help=method.__doc__
                )
                if hasattr(method, "_args"):
                    for arg_args, arg_kwargs in method._args:
                        cmd_parser.add_argument(*arg_args, **arg_kwargs)
                cmd_parser.set_defaults(func=method)

    args = parser.parse_args()

    setup_logging_level(args.debug)
    LOG.info("Starting CBoK CLI")

    try:
        func = getattr(args, 'func', None)
        if func:
            kwargs = {k: v for k, v in vars(args).items()
                      if k not in ['subcommand', 'command', 'func', 'debug']}
            return_code = func(**kwargs)
            sys.exit(return_code)
    except Exception:
        LOG.exception("Command failed")
        sys.exit(1)
