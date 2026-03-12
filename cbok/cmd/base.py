import os
import sys


def _resolve_and_reexec_venv():
    """
    If we're not already in the project venv, re-exec into it. Must run before
    any cbok imports (e.g. utils->requests), so only uses stdlib os/sys.
    """
    def _venv_dir():
        if os.environ.get("CBOK_VENV"):
            return os.path.realpath(os.environ["CBOK_VENV"])
        if os.environ.get("CBOK_HOME"):
            return os.path.realpath(os.path.join(os.environ["CBOK_HOME"], "venv"))
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(base_dir))
        venv_dir = os.path.join(project_root, "venv")
        if os.path.isdir(venv_dir):
            return os.path.realpath(venv_dir)
        return None

    venv_dir = _venv_dir()
    if not venv_dir:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        expected_venv = os.path.join(project_root, "venv")
        sys.stderr.write(
            "cbok: no virtual env found (looked for %s or CBOK_VENV/CBOK_HOME).\n"
            "Create one: cd %s && python3 -m venv venv && venv/bin/pip install -r requirement/cli.txt && venv/bin/pip install -e .\n"
            % (expected_venv, project_root)
        )
        sys.exit(1)
    if os.path.realpath(sys.prefix) == venv_dir:
        return

    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    venv_cbok = os.path.join(venv_dir, bin_dir, "cbok.exe" if sys.platform == "win32" else "cbok")
    venv_python = os.path.join(venv_dir, bin_dir, "python.exe" if sys.platform == "win32" else "python")
    argv = ["cbok"] + sys.argv[1:]
    try:
        if os.path.isfile(venv_cbok) and os.access(venv_cbok, os.X_OK):
            os.execv(venv_cbok, argv)
        if os.path.isfile(venv_python):
            os.execv(venv_python, [venv_python, "-m", "cbok.cmd"] + sys.argv[1:])
    except Exception as e:
        sys.stderr.write("cbok: failed to re-exec into venv %s: %s\n" % (venv_dir, e))
        sys.exit(1)
    sys.stderr.write("cbok: venv at %s has no bin/cbok or bin/python\n" % venv_dir)
    sys.exit(1)


_resolve_and_reexec_venv()

import argparse
import logging

import django

from cbok import __version__
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
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
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
