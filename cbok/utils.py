import os
import subprocess

from cbok import exception
from cbok import settings


def applications():
    return settings.CBoK_APPS


def locate_project_path(ide, company, name):
    workspace = settings.Workspace

    def _all_ides():
        base = workspace
        return [
            _name for _name in os.listdir(base)
            if os.path.isdir(os.path.join(base, _name))
        ]

    def _all_companies():
        _base = str(os.path.join(workspace, ide))
        return [
            _name for _name in os.listdir(_base)
            if os.path.isdir(os.path.join(_base, _name))
        ]

    if ide not in _all_ides() or company not in _all_companies():
        raise exception.CannotLocateProject()

    return os.path.join(workspace, ide, company, name)


def execute(cmd, capture_output=True):
    if capture_output:
        return subprocess.run(cmd, capture_output=True, text=True)
    else:
        return subprocess.run(cmd, shell=True)
