import json
import logging
import os
import shlex
import sys

from cbok.apps.bbx import exception
from cbok import utils as cbok_utils
from cbok import settings


LOG = logging.getLogger(__name__)


service_supported = {
    "nova-api-osapi": {
        "parent": "nova",
        "package": "nova",
        "site": "/usr/local/lib/python3.6/site-packages/nova/",
        "controller": "Deployment",
        "replica": "nova-api-osapi",
        "container": "nova-osapi",
        "config_map": "nova-bin",
        "start_script": "/tmp/nova-api.sh"
    },
    "nova-conductor": {
        "parent": "nova",
        "package": "nova",
        "site": "/usr/local/lib/python3.6/site-packages/nova/",
        "controller": "Deployment",
        "replica": "nova-conductor",
        "container": "nova-conductor",
        "config_map": "nova-bin",
        "start_script": "/tmp/nova-conductor.sh"
    },
    "nova-compute": {
        "parent": "nova",
        "package": "nova",
        "site": "/usr/local/lib/python3.6/site-packages/nova/",
        "controller": "DaemonSet",
        "replica": "nova-compute",
        "container": "nova-compute",
        "config_map": "nova-bin",
        "start_script": "/tmp/nova-compute.sh"
    },
    "nova-dashboard-api": {
        "parent": "nova-dashboard-api",
        "package": "nova_dashboard_api",
        "site": "/usr/lib/python2.7/site-packages/nova_dashboard_api/",
        "controller": "Deployment",
        "replica": "nova-dashboard-api",
        "container": "nova-dashboard-api",
        "config_map": "nova-bin",
        "start_script": "/nova-dashboard-api.sh"
    }
}


def commit_changes(project):
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "worker", "diff.sh")

    result = cbok_utils.execute(
        ["bash", "-c", f"source {worker}; get_diff " + project])

    if result.returncode == 0 and not result.stdout:
        raise exception.NoDiffBetweenHead()

    if result.returncode != 0:
        LOG.error(result.stderr)
        raise exception.AnalysisCommitFailed(project=project)

    files = [json.loads(line) for line in result.stdout.splitlines()]
    for file in files:
        file_abs = os.path.join(settings.Workspace, 'PycharmProjects',
                                'es', project, file["path"])
        file["path"] = file_abs

    return files


def init_pod(address, service_meta, node=None):
    worker = None
    controller = service_meta["controller"]
    if controller == "Deployment":
        worker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "worker", "pod_deployment.sh")
    elif controller == "DaemonSet":
        worker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "worker", "pod_daemonset.sh")

    func = "init_pod"
    if address.startswith("172.18.0"):
        func = "init_pod_os_in_os"
    result = cbok_utils.execute(
        ["bash", "-c", f"source {worker}; {func} {address} "
                       f"{service_meta['controller']} "
                       f"{service_meta['replica']} "
                       f"{service_meta['config_map']} "
                       f"{service_meta['start_script']} "
                       f"{node if controller == 'DaemonSet' else ''} "])

    if result.returncode != 0 or "Done;" not in result.stdout:
        LOG.error(result.stderr)
        raise exception.InitPodFailed(service=service_meta["replica"])

    pod_name = result.stdout.split("Done;")[1]
    return pod_name


def copy_changes(address, changes, pod_name, service_meta):
    parent = service_meta["parent"]
    package = service_meta["package"]
    target_site = service_meta["site"]
    container = service_meta["container"]

    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "worker", "copy.sh")

    for change in changes:
        change["remote_path"] = os.path.join(
            target_site, change["path"].split(f"{parent}/{package}")[1].lstrip('/'))

    files_args = json.dumps(changes)

    func = "copy"
    if address.startswith("172.18.0"):
        func = "copy_os_in_os"
    result = cbok_utils.execute(
        ["bash", "-c", f"source {worker}; {func} {shlex.quote(address)} "
                       f"{shlex.quote(pod_name)} {shlex.quote(container)} "
                       f"{shlex.quote(files_args)}"])
    if result.returncode != 0:
        LOG.error(result.stderr)
        raise exception.CopyChangesFailed()


def finalize_startup(address, pod_name, service_meta):
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "worker", "startup.sh")
    script = service_meta["start_script"]
    container = service_meta["container"]

    func = "finalize_startup"
    if address.startswith("172.18.0"):
        func = "finalize_startup_os_in_os"

    result = cbok_utils.execute(
        ["bash", "-c", f"source {worker}; {func} {shlex.quote(address)} "
                       f"{shlex.quote(pod_name)} {shlex.quote(container)} "
                       f"{shlex.quote(script)}"]
    )
    if result.returncode != 0:
        LOG.error(result.stderr)
        raise exception.FinalizeStartupFailed()


def run(address, service, node):

    if service not in service_supported:
        print(f"error: {service}\n"
              f"{list(service_supported.keys())} in choices")
        sys.exit(1)

    service_meta = service_supported[service]

    controller = service_meta["controller"]
    if controller == "Deployment" and node:
        print(f"error: redundant argument {node}")
        sys.exit(1)
    if controller == "DaemonSet" and not node:
        print("error: node is required for DaemonSet")
        sys.exit(1)

    try:
        changes = commit_changes(service_meta["parent"])
    except exception.NoDiffBetweenHead as e:
        print(e.msg_fmt)
        return

    pod_name = None
    if controller == "Deployment":
        pod_name = init_pod(address, service_meta)
    elif controller == "DaemonSet":
        pod_name = init_pod(address, service_meta, node)

    pod_name = pod_name.strip()
    copy_changes(address, changes, pod_name, service_meta)
    finalize_startup(address, pod_name, service_meta)

    print(pod_name)
