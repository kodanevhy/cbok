from contextlib import contextmanager
import logging
import os
import subprocess

from cbok import exception
from cbok import settings


def applications():
    install_apps = []
    for app in settings.CBoK_APPS:
        if app.startswith("cbok.apps."):
            install_apps.append(app.split(".")[2])
        else:
            install_apps.append(app)
    return install_apps


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


def execute(cmd, cwd=None):
    stash_cwd = None
    if cwd:
        stash_cwd = os.getcwd()
        os.chdir(cwd)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        if stash_cwd:
            os.chdir(stash_cwd)

    return result


@contextmanager
def suppress_logs(package, level=logging.ERROR):
    logger = logging.getLogger(package)
    old_level = logger.level
    logger.setLevel(level)
    try:
        yield
    finally:
        logger.setLevel(old_level)


def initial_task(func):
    func.initial = True
    return func


def periodic_task(interval=60):
    def decorator(func):
        func.periodic = True
        func.interval = interval
        return func
    return decorator
