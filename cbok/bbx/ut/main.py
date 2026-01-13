import json
import logging
import os.path
import sys
import shlex

from oslo_utils import fileutils
from cbok.bbx import exception
from cbok import settings
from cbok import utils as cbok_utils

LOG = logging.getLogger(__name__)

# Note: stashed image by that tag, not a mandatory requirement
SUPPORTED = {
    # from hub.easystack.io/arm64v8/escloud-linux-source-
    # nova-compute:6.2.2-alpha.21
    "nova": {
        "image": "cbok-ut-nova-compute:latest",
        "site": "/root/workspace/ut/nova/",
    },
    # from hub.easystack.io/arm64v8/escloud-linux-source-
    # nova-dashboard-api:6.2.2-alpha.21
    "nova-dashboard-api": {
        "image": "cbok-ut-nova-dashboard-api:latest",
        "site": "/root/workspace/ut/nova-dashboard-api/",
    },
}


def copy_changes(project, container_name, changes, executor=None):
    service_meta = SUPPORTED[project]
    target_site = service_meta["site"]

    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "worker.sh")

    for change in changes:
        change["remote_path"] = os.path.join(
            target_site, change["path"].split(f"{project}")[1].lstrip('/'))

    files_args = json.dumps(changes)

    result = executor.run_command(
        ["bash", "-c", f"source {worker}; copy_changes {container_name} "
                       f"{shlex.quote(files_args)}"])
    
    if result.returncode != 0:
        LOG.error(result.stderr)
        raise exception.CopyChangesFailed()


def run(project, command, executor=None):
    if project not in SUPPORTED:
        print("error: unsupported project: %s" % project)
        print("%s in choice" % ", ".join(SUPPORTED.keys()))
        sys.exit(1)

    image = SUPPORTED[project]["image"]

    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "worker.sh")

    workspace = settings.Workspace
    project_home = os.path.join(workspace, 'Cursor', 'es', project)

    result = executor.run_command(
        ["bash", "-c", f"source {worker}; is_virtual_env_ready {project}"])

    if result.returncode != 0 or 'Ready' not in result.stdout:
        zip_target = os.path.join(os.path.dirname(project_home),
                                  f"{project}.zip")
        result = executor.run_command(
            ["zip", "-r", zip_target, project,
            "-x", f"{project}/.idea/*",
            "-x", f"{project}/venv/*"],
            cwd=os.path.dirname(project_home)
        )
        if result.returncode != 0:
            fileutils.delete_if_exists(zip_target)
            sys.exit(1)

        try:
            result = executor.run_command(
                ["bash", "-c", f"source {worker}; first_run {image} {project} "
                               f"{zip_target} {command}"])
            if result.returncode != 0 and "no such image" in result.stderr:
                raise exception.NoSuchImage(image=image)

        finally:
            fileutils.delete_if_exists(zip_target)
    else:
        LOG.info("Using cached tox virtual env")

        result = cbok_utils.execute(
                ["bash", "-c", f"source {worker}; get_diff {project}"])

        if result.returncode == 0 and not result.stdout:
            raise exception.NoDiffBetweenHead()

        if result.returncode != 0:
            LOG.error(result.stderr)
            raise exception.AnalysisCommitFailed(project=project)

        files = [json.loads(line) for line in result.stdout.splitlines()]
        for file in files:
            file_abs = os.path.join(settings.Workspace, 'Cursor',
                                    'es', project, file["path"])
            file["path"] = file_abs

        container_name = f"ut-{project}"
        copy_changes(project, container_name, files, executor)

        result = executor.run_command(
            ["bash", "-c", f"source {worker}; later_run "
                           f"{project} {command}"])
