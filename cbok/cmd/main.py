import os
import subprocess
import sys

import django


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolve_and_reexec_venv():
    """
    If we're not already in the project venv, re-exec into it before loading
    the command modules.
    """
    def _venv_dir():
        if os.environ.get("CBOK_VENV"):
            return os.path.realpath(os.environ["CBOK_VENV"])
        if os.environ.get("CBOK_HOME"):
            return os.path.realpath(os.path.join(os.environ["CBOK_HOME"], "venv"))
        venv_dir = os.path.join(_project_root(), "venv")
        if os.path.isdir(venv_dir):
            return os.path.realpath(venv_dir)
        return None

    venv_dir = _venv_dir()
    if not venv_dir:
        expected_venv = os.path.join(_project_root(), "venv")
        sys.stderr.write(
            "cbok: no virtual env found (looked for %s or CBOK_VENV/CBOK_HOME).\n"
            "Create one: cd %s && python3 -m venv venv && venv/bin/pip install -r requirement/cli.txt && venv/bin/pip install -e .\n"
            % (expected_venv, _project_root())
        )
        sys.exit(1)
    if os.path.realpath(sys.prefix) == venv_dir:
        return

    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    venv_cbok = os.path.join(venv_dir, bin_dir, "cbok.exe" if sys.platform == "win32" else "cbok")
    venv_python = os.path.join(venv_dir, bin_dir, "python.exe" if sys.platform == "win32" else "python")
    project_root = os.path.dirname(venv_dir)
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root + (os.pathsep + env.get("PYTHONPATH", "")) if env.get("PYTHONPATH") else project_root
    argv = ["cbok"] + sys.argv[1:]
    try:
        if os.path.isfile(venv_cbok) and os.access(venv_cbok, os.X_OK):
            os.execve(venv_cbok, argv, env)
        if os.path.isfile(venv_python):
            os.execve(venv_python, [venv_python, "-m", "cbok.cmd"] + sys.argv[1:], env)
    except Exception as e:
        sys.stderr.write("cbok: failed to re-exec into venv %s: %s\n" % (venv_dir, e))
        sys.exit(1)
    sys.stderr.write("cbok: venv at %s has no bin/cbok or bin/python\n" % venv_dir)
    sys.exit(1)


def _ensure_source_branch_is_master(project_root=None, runner=subprocess.run, stderr=sys.stderr):
    project_root = os.path.realpath(project_root or _project_root())

    def _git(*args):
        return runner(
            ["git", "-C", project_root] + list(args),
            capture_output=True,
            text=True,
        )

    result = _git("branch", "--show-current")
    branch = (result.stdout or "").strip() if result.returncode == 0 else ""
    if branch != "master":
        current = branch or "detached HEAD or unknown"
        stderr.write(
            "cbok: refusing to run because the editable source checkout is not on master.\n"
            "source: %s\n"
            "current branch: %s\n"
            "expected branch: master\n"
            "\n"
            "Check and update it manually:\n"
            "  cd %s\n"
            "  git status --short --branch\n"
            "  git checkout master\n"
            "  git fetch origin\n"
            "  git rebase origin/master\n"
            % (project_root, current, project_root)
        )
        detail = (result.stderr or "").strip()
        if result.returncode != 0 and detail:
            stderr.write("\ngit error: %s\n" % detail)
        sys.exit(1)

    local_result = _git("rev-parse", "HEAD")
    local_head = (local_result.stdout or "").strip() if local_result.returncode == 0 else ""
    remote_result = _git("ls-remote", "--exit-code", "origin", "refs/heads/master")
    remote_head = (
        (remote_result.stdout or "").split()[0]
        if remote_result.returncode == 0 and remote_result.stdout
        else ""
    )
    if local_head and remote_head and local_head == remote_head:
        return

    stderr.write(
        "cbok: refusing to run because the editable source checkout is not synced with origin/master.\n"
        "source: %s\n"
        "local master: %s\n"
        "remote master: %s\n"
        "\n"
        "Check and update it manually:\n"
        "  cd %s\n"
        "  git status --short --branch\n"
        "  git fetch origin\n"
        "  git rebase origin/master\n"
        % (
            project_root,
            local_head or "unknown",
            remote_head or "unknown",
            project_root,
        )
    )
    local_detail = (local_result.stderr or "").strip()
    remote_detail = (remote_result.stderr or "").strip()
    if local_result.returncode != 0 and local_detail:
        stderr.write("\ngit error: %s\n" % local_detail)
    if remote_result.returncode != 0 and remote_detail:
        stderr.write("\ngit error: %s\n" % remote_detail)
    sys.exit(1)


def main():
    _ensure_source_branch_is_master()
    _resolve_and_reexec_venv()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cbok.settings")
    django.setup()

    import argparse
    import logging

    from cbok import __version__
    from cbok.cmd import bbx
    from cbok.cmd import foundation
    from cbok.cmd import zsv
    from cbok.cmd.base import BaseCommand
    from cbok import utils as cbok_utils

    LOG = logging.getLogger(__name__)

    CATEGORIES = {
        "patch": bbx.PatchCommands,
        "bin": bbx.BinCommands,
        "openstack": bbx.OpenStackCommands,
        "foundation": foundation.FoundationCommands,
        "proxy": bbx.ProxyCommands,
        "zsv": zsv.ZSphereCommands,
    }

    def setup_logging_level(debug=False):
        root = logging.getLogger()
        root.setLevel(logging.DEBUG if debug else logging.INFO)

        for handler in root.handlers:
            handler.setLevel(logging.DEBUG if debug else logging.INFO)

    # NOTE: means all we used file path in shell scripts are relative
    # to CBoK home
    os.chdir(cbok_utils.assert_cbok_home())

    command_groups = cbok_utils.discover_command_groups(CATEGORIES, BaseCommand)
    parser = argparse.ArgumentParser(
        prog="cbok",
        description="CBoK CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=cbok_utils.format_command_catalog(command_groups),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    # override Django DEBUG configuration, cuz if we in
    # production (DEBUG=False), the cbok cli also can be debug
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    for cat_name, obj, commands in command_groups:
        cat_parser = subparsers.add_parser(cat_name, help=f"{cat_name} commands")
        cat_subparsers = cat_parser.add_subparsers(dest="command", required=True)
        for attr_name, method in commands:
            cmd_parser = cat_subparsers.add_parser(attr_name, help=cbok_utils.command_description(method))
            if hasattr(method, "_args"):
                for arg_args, arg_kwargs in method._args:
                    cmd_parser.add_argument(*arg_args, **arg_kwargs)
            cmd_parser.set_defaults(func=method)

    args = parser.parse_args()

    setup_logging_level(args.debug)
    LOG.info("Starting CBoK CLI")

    try:
        func = getattr(args, "func", None)
        if func:
            kwargs = {k: v for k, v in vars(args).items() if k not in ["subcommand", "command", "func", "debug"]}
            # Pre-ensure remote scriptlet once for commands that
            # specified address.
            if hasattr(func, "_requires_remote_scriptlet"):
                address_kw = getattr(func, "_requires_remote_scriptlet")
                addr = kwargs.get(address_kw)
                if addr:
                    ensure_result = func.__self__.ensure_remote_scriptlet(addr)
                    if getattr(ensure_result, "returncode", 0) != 0:
                        sys.exit(getattr(ensure_result, "returncode", 1) or 1)
            return_code = func(**kwargs)
            sys.exit(return_code)
    except Exception:
        LOG.exception("Command failed")
        sys.exit(1)
