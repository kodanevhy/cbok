import argparse
import logging
import os
import sys
from cbok import settings
from cbok.cmd import bbx
from cbok.cmd import foundation

LOG = logging.getLogger("cbok-cli")

CATEGORIES = {
    'patch': bbx.PatchCommands,
    'bin': bbx.BinCommands,
    'foundation': foundation.FoundationCommands,
}


def setup_logging(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    assert os.getcwd().lower() == settings.BASE_DIR.lower()

    parser = argparse.ArgumentParser(prog="cbok", description="CBoK CLI")
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

    setup_logging(debug=args.debug)
    LOG.info("Starting CBoK CLI (debug=%s)", args.debug)

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
