import argparse
import os
import sys

from cbok.apps.bbx.put_patch import main as put_patch
from cbok import settings


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


CATEGORIES = {
    'patch': PatchCommands,
}


def main():
    assert os.getcwd() == settings.BASE_DIR

    parser = argparse.ArgumentParser(description="CBoK BBX CLI")
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

    try:
        func = getattr(args, 'func', None)
        if func:
            kwargs = {k: v for k, v in vars(args).items()
                      if k not in ['category', 'command', 'func']}
            return_code = func(**kwargs)
            sys.exit(return_code)
    except Exception as e:
        print(f"{e}")
        sys.exit(1)
