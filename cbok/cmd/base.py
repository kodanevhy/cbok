import os
import shlex

from cbok import utils as cbok_utils
from cbok.cmd import args


def _source_project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BaseCommand:
    def __init__(self) -> None:
        self.p_runner = cbok_utils.UnifiedProcessRunner()

    def ensure_remote_scriptlet(self, address: str):
        """
        Ensure local scriptlet is synced to remote /opt/cbok/scriptlet once.
        """
        if not address:
            return
        # base.py already chdir to cbok home, so scriptlet/ is resolvable.
        addr_q = shlex.quote(str(address))
        result = self.p_runner.run_command(
            ["bash", "-lc", f"source scriptlet/bootstrap.sh; ensure_remote_scriptlet {addr_q}"]
        )
        return result


class DefaultCommands(BaseCommand):
    def __init__(self, project_root=None) -> None:
        super().__init__()
        self.project_root = os.path.realpath(project_root or _source_project_root())

    @args.action_description("Checkout CBoK source master and rebase origin/master")
    def rebase(self):
        """Checkout CBoK source master and rebase it from origin/master."""
        for git_args in (
            ["checkout", "master"],
            ["fetch", "origin"],
            ["rebase", "origin/master"],
        ):
            result = self.p_runner.run_command(["git", "-C", self.project_root] + git_args)
            if result.returncode != 0:
                return result.returncode or 1
        return 0
