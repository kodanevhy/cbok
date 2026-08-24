import logging
import os
import shlex

from cbok import utils as cbok_utils
from cbok.cmd import args


LOG = logging.getLogger(__name__)
FORCE_ABORT_PROMPT = (
    "Discard local CBoK source changes and abort any rebase? Type 'yes' to continue: "
)


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

    def _git(self, *git_args, **kwargs):
        return self.p_runner.run_command(
            ["git", "-C", self.project_root] + list(git_args),
            **kwargs,
        )

    def _source_checkout_is_dirty(self) -> bool | None:
        result = self._git("status", "--porcelain", log_output=False)
        if result.returncode != 0:
            LOG.error("Unexpected error while checking CBoK source checkout before rebase.")
            return None
        return bool((result.stdout or "").strip())

    def _confirm_force_abort(self) -> bool:
        try:
            answer = input(FORCE_ABORT_PROMPT)
        except EOFError:
            LOG.error("Force abort requires interactive confirmation.")
            return False
        if answer.strip() != "yes":
            LOG.error("Force abort cancelled; confirmation was not yes.")
            return False
        return True

    def _force_abort_source_checkout(self):
        self._git(
            "rebase", "--abort",
            cmd_purge_output=False,
            log_output=False,
            log_failed_status=False,
        )
        for git_args in (
            ("reset", "--hard"),
            ("clean", "-fd"),
        ):
            result = self._git(*git_args)
            if result.returncode != 0:
                return result.returncode or 1
        return 0

    @args.action_description("Checkout CBoK source master and rebase origin/master")
    @args.args(
        "--force-abort",
        action="store_true",
        help=(
            "Prompt for confirmation, then abort any in-progress rebase and "
            "discard local CBoK source changes before rebasing master"),
    )
    def rebase(self, force_abort=False):
        """Checkout CBoK source master and rebase it from origin/master."""
        if force_abort:
            if not self._confirm_force_abort():
                return 1
            force_result = self._force_abort_source_checkout()
            if force_result != 0:
                return force_result
        else:
            dirty = self._source_checkout_is_dirty()
            if dirty is None:
                return 1
            if dirty:
                LOG.error(
                    "Unexpected dirty CBoK source checkout before rebase.\n"
                    "source: %s\n"
                    "cbok rebase expects the editable source checkout to be a clean master baseline.\n"
                    "Inspect it with: git -C %s status --short\n"
                    "Use cbok rebase --force-abort only if local changes can be discarded.",
                    self.project_root,
                    self.project_root,
                )
                return 1

        for git_args in (
            ["checkout", "master"],
            ["fetch", "origin"],
            ["rebase", "origin/master"],
        ):
            result = self._git(*git_args)
            if result.returncode != 0:
                return result.returncode or 1
        return 0
