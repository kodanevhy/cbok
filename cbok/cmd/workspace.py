import logging

from cbok import settings
from cbok import workspace as workspace_service
from cbok.cmd import args
from cbok.cmd import base


LOG = logging.getLogger(__name__)


class WorkspaceCommands(base.BaseCommand):
    def _workspace_root(self, workspace_arg=""):
        root = (workspace_arg or settings.Workspace or "").strip()
        if not root:
            raise workspace_service.WorkspaceLayoutError(
                "workspace is not configured; set [default] workspace in cbok.conf"
            )
        return root

    def _run(self, func, *func_args, **func_kwargs):
        try:
            result = func(*func_args, **func_kwargs)
        except workspace_service.WorkspaceLayoutError as e:
            LOG.error("%s", e)
            return 1
        if result:
            LOG.info("%s", result)
        return 0

    @args.action_description("Initialize workspace layout")
    @args.args("--workspace", default="", help="Workspace root; defaults to [default] workspace")
    def init(self, workspace=""):
        return self._run(
            workspace_service.init_workspace,
            self._workspace_root(workspace),
        )

    @args.action_description("Initialize an editor layout")
    @args.args("--editor", required=True, help="Editor directory name, for example Cursor")
    def init_editor(self, editor=None):
        return self._run(
            workspace_service.init_editor,
            self._workspace_root(),
            editor,
        )

    @args.action_description("Initialize a company directory under all editors")
    @args.args("--company", required=True, help="Company directory name, for example zs")
    def init_company(self, company=None):
        return self._run(
            workspace_service.init_company,
            self._workspace_root(),
            company,
        )

    @args.action_description("Initialize or clone a project directory")
    @args.args("--editor", required=True, help="Editor directory name")
    @args.args("--company", required=True, help="Initialized company directory name")
    @args.args("--project", required=True, help="Project directory name")
    @args.args("--repo", default="", help="Git repository URL to clone; target path must not exist")
    def init_project(self, editor=None, company=None, project=None, repo=""):
        return self._run(
            workspace_service.init_project,
            self._workspace_root(),
            editor,
            company,
            project,
            repo=repo,
        )

    @args.action_description("Select active workspace editor and company")
    @args.args("--editor", required=True, help="Editor directory name")
    @args.args("--company", required=True, help="Initialized company directory name")
    def use(self, editor=None, company=None):
        return self._run(
            workspace_service.use_context,
            self._workspace_root(),
            editor,
            company,
        )
