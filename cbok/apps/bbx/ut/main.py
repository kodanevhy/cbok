import logging
import os.path
import sys

from oslo_utils import fileutils

import cbok.utils
from cbok.apps.bbx import exception
from cbok import settings
from cbok import utils as cbok_utils

LOG = logging.getLogger(__name__)

# Note: stashed image by that tag, not a mandatory requirement
SUPPORTED = {
    # from hub.easystack.io/arm64v8/escloud-linux-source-
    # nova-compute:6.2.2-alpha.21
    "nova": {
        "image": "cbok-ut-nova-compute:latest",
        "test_dir": "/nova/test/"
    },
    # from hub.easystack.io/arm64v8/escloud-linux-source-
    # nova-dashboard-api:6.2.2-alpha.21
    "nova-dashboard-api": {
        "image": "cbok-ut-nova-dashboard-api:latest",
        "test_dir": "/nova_dashboard_api/test/"
    },
}


def run(project, command):
    if project not in SUPPORTED:
        print("error: unknown project '%s'" % project)
        print("%s in choice" % ", ".join(SUPPORTED.keys()))
        sys.exit(1)

    image = SUPPORTED[project]["image"]

    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "worker.sh")

    workspace = settings.Workspace
    project_home = os.path.join(workspace, 'PycharmProjects', 'es', project)

    result = cbok_utils.execute(
        ["bash", "-c", f"source {worker}; is_virtual_env_ready {project}"])

    if result.returncode != 0 or 'Ready' not in result.stdout:
        zip_target = os.path.join(os.path.dirname(project_home),
                                  f"{project}.zip")
        result = cbok_utils.execute(
            ["zip", "-r", zip_target, project],
            cwd=os.path.dirname(project_home)
        )
        if result.returncode != 0:
            LOG.error("unable to zip project '%s'" % project)
            LOG.error(result.stderr)
            fileutils.delete_if_exists(zip_target)
            sys.exit(1)

        try:
            result = cbok_utils.execute(
                ["bash", "-c", f"source {worker}; first_run {image} {project} "
                               f"{zip_target} {command}"])
            if result.returncode != 0 and "no such image" in result.stderr:
                raise exception.NoSuchImage(image=image)

            LOG.info(result.stdout)
            LOG.error(result.stderr)

        finally:
            fileutils.delete_if_exists(zip_target)
    else:
        LOG.info("Using cached tox virtual env")

        test_dir = SUPPORTED[project]["test_dir"]
        test_dir = os.path.join(project_home, test_dir.lstrip("/"))
        result = cbok_utils.execute(
            ["bash", "-c", f"source {worker}; copy_test_dir_and_run "
                           f"{test_dir} {project} {command}"])
        LOG.info(result.stdout)
        LOG.error(result.stderr)
