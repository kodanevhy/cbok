import shlex

from cbok import utils as cbok_utils


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
