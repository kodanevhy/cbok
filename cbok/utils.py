from contextlib import contextmanager
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading

from cbok import exception
from cbok import settings


LOG = logging.getLogger(__name__)


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


class UnifiedProcessRunner:
    def __init__(self, log_prefix="SHELL"):
        self.log_prefix = log_prefix

    def run_shell_script(self, script_path, args=None, cwd=None, env=None):
        if sys.platform == 'win32':
            script_path = script_path.replace('\\', '/')
            script_path = str(Path(script_path).resolve())

        if not os.access(script_path, os.X_OK):
            os.chmod(script_path, 0o755)

        return self.run_command(script_path, args, cwd=cwd, env=env)

    def _print_header(self, cmd):
        LOG.debug(f"Working from: {os.getcwd()}")
        if isinstance(cmd, list):
            cmd_str = ' '.join(cmd)
        else:
            cmd_str = cmd
        LOG.info(f"[{self.log_prefix}] {cmd_str}")

    def _print_failed_status(self, returncode):
        LOG.error(f"[{self.log_prefix}] ERRNO: {returncode} ;<")

    def run_command(self, cmd, args=None, shell=False, cwd=None, env=None,
                           timeout=None, check=False):
        if isinstance(cmd, str):
            full_cmd = [cmd]
        else:
            full_cmd = list(cmd)

        if args:
            full_cmd.extend(args)

        self._print_header(full_cmd)

        if shell:
            if isinstance(full_cmd, list):
                full_cmd = " ".join(full_cmd)

        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        try:
            proc = subprocess.Popen(
                full_cmd,
                shell=shell,
                cwd=cwd,
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                universal_newlines=True
            )

            output_lines = []

            def read_output():
                for line in iter(proc.stdout.readline, ''):
                    line = line.rstrip()
                    if line:
                        output_lines.append(line)
                        if line.startswith("+"):
                            continue
                        LOG.info(f"[{self.log_prefix}] {line}")
                proc.stdout.close()

            output_thread = threading.Thread(target=read_output)
            output_thread.daemon = True
            output_thread.start()

            proc.wait(timeout=timeout)

            output_thread.join(timeout=1)

            if proc.returncode != 0:
                self._print_failed_status(proc.returncode)

            result = subprocess.CompletedProcess(
                args=full_cmd,
                returncode=proc.returncode,
                stdout='\n'.join(output_lines),
                stderr=''
            )

            if check and proc.returncode != 0:
                raise subprocess.CalledProcessError(
                    proc.returncode, full_cmd, result.stdout, result.stderr
                )

            return result

        except subprocess.TimeoutExpired as e:
            LOG.error(f"Timeout: {timeout} second(s)")
            raise
        except FileNotFoundError as e:
            LOG.error(f"Not Found: {full_cmd[0]}")
            raise
        except Exception as e:
            LOG.error(f"Unexpected error: {e}")
            raise
