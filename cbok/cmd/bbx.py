import logging
import os
import shutil

from cbok.apps.bbx.put_patch import main as put_patch
from cbok.apps.bbx.ut import main as ut
from cbok.cmd import args
from cbok import exception
from cbok import utils

LOG = logging.getLogger(__name__)


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


class BinCommands:

    @staticmethod
    def _get_version(cmd):
        try:
            result = utils.execute(cmd)
            output = result.stdout.strip()
            stderr = result.stderr.strip()
            if stderr:
                return stderr.splitlines()[0]
            if output:
                return output.splitlines()[0]
        except FileNotFoundError:
            return ""
        except Exception:
            return ""
        return ""

    @staticmethod
    def _find_all_pythons():
        paths = os.environ.get("PATH", "").split(os.pathsep)
        seen = set()
        python_versions = {}

        for path in paths:
            if not os.path.isdir(path):
                continue
            for fname in os.listdir(path):
                if fname.startswith("python") and "pythonw" not in fname \
                    and "config" not in fname:
                    full_path = os.path.join(path, fname)
                    if full_path in seen or not os.access(full_path, os.X_OK):
                        continue
                    seen.add(full_path)
                    version = BinCommands._get_version([full_path, "--version"])
                    if version:
                        python_versions[full_path] = version
        return python_versions

    @staticmethod
    def _find_go():
        go_path = shutil.which("go")
        version = BinCommands._get_version([go_path, "version"]) if go_path else ""
        return (go_path, version if version else "not found")

    def usage(self):
        """Detail the binary files in the local directory"""
        try:
            current_python = shutil.which("python")
            python_versions = self._find_all_pythons()
            go_path, go_version = self._find_go()

            print("Python versions found:")
            if python_versions:
                for path, version in sorted(python_versions.items(), key=lambda x: x[0]):
                    prefix = "-> " if path == current_python else "   "
                    print(f"{prefix}{path}: {version}")
            else:
                print("No Python found")

            print("\nGo version:")
            prefix = "-> " if go_path == shutil.which("go") else "   "
            print(f"{prefix}{go_path}: {go_version}")

        except Exception as e:
            raise e

    @args.action_description("Get the absolute path of that binary")
    @args.args(
        '--skip-venv', action='store_true', required=False,
        help='Show the highest priority Python of the node (ignore virtual env)')
    @args.args(
        '--binary', metavar='<binary>', required=True,
        help='A binary symbol link used in shell')
    def which(self, binary, skip_venv=False):
        """Get the absolute path of that binary"""

        venv_path = os.environ.get("VIRTUAL_ENV")
        path_list = os.environ.get("PATH", "").split(":")

        if skip_venv and venv_path:
            venv_bin = os.path.join(venv_path, "bin")
            path_list = [p for p in path_list if not p.startswith(venv_bin)]
            os.environ["PATH"] = ":".join(path_list)

        elif venv_path and not skip_venv:
            raise exception.ShouldNotVirtualEnv()

        result = utils.execute(["which", binary])
        if result.returncode == 0:
            abs_path = result.stdout.strip()
            print(f"{binary}: {abs_path}")
        else:
            LOG.error(result.stderr)

    @args.action_description("Override the binary to use")
    @args.args(
        '--binary', metavar='<binary>', required=True,
        help='A binary symbol link used in shell')
    def default(self, binary):
        """Override the binary to use"""
        pass
