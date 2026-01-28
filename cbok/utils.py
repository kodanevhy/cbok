import configparser
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
import socket
import subprocess
import sys
from urllib3.util.retry import Retry
import threading

from cbok import exception
from cbok import settings


LOG = logging.getLogger(__name__)
CONF = settings.CONF


def applications():
    install_apps = []
    for app in settings.CBoK_APPS:
        if app.startswith("cbok."):
            install_apps.append(app.split(".")[1])
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


# FIXME(koda): the service output was mixed in stdout, so we cannot
# retreive, use `execute` in this util file as workaround
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
            if isinstance(args, str):
                full_cmd.append(args)
            else:
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

            # WARNING: DONOT use `sh/bash -c` to call remote in first shell
            # Now we can capture the first shell output called by Python,
            # but if the first shell still calls the remote shell by using
            # `sh/bash -c`, we cannot record the exactly execution time of
            # command in remote shell, because the remote script returned
            # output until all the command finished. Unless we can impl the
            # same thread catcher with Python from here to first shell
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


def assert_cbok_home():
    workspace = settings.Workspace
    cbok_home = os.path.join(workspace, "Cursor", "me", "cbok")
    if not os.path.exists(cbok_home):
        print(f"CBoK command required: please re-define workspace root in "
              f"settings.Workspace, and build source tree first "
              f"and put CBoK into {os.path.dirname(cbok_home)}:")
        print(f"*mkdir -p {os.path.dirname(cbok_home)}*")
        sys.exit(1)

    return cbok_home


def assert_tree(path):
    workspace = settings.Workspace
    abs_path = os.path.join(workspace, path)
    return True if os.path.exists(abs_path) else False


def load_proxies(conf=None):
    if not conf:
        conf = CONF
    if not conf.has_section("proxy"):
        return None

    scheme = conf.get("proxy", "type", fallback="socks5h")
    host = conf.get("proxy", "localhost")
    port = conf.get("proxy", "localport")

    url = f"{scheme}://{host}:{port}"
    return {"http": url, "https": url}


def write_proxy_conf(path):
    if "proxy" in CONF.sections():
        with open(path, "w") as f:
            try:
                proxy_conf = (f"cipher={CONF.get("proxy", "cipher")}\n"
                f"password={CONF.get("proxy", "password")}\n"
                f"vps_server={CONF.get("proxy", "vps_server")}\n"
                f"port={CONF.get("proxy", "port")}")
            except (configparser.NoSectionError,
                    configparser.NoOptionError) as e:
                LOG.warning("Please fill in the proxy configuration: %s", e)
                return False
            f.write(proxy_conf)
    else:
        LOG.warning("No proxy configuration found, maybe failed to fetch "
                    "repository")


def create_session(
    timeout=10,
    retries=3,
    backoff_factor=0.5,
    proxies=None,
):
    """
    :param timeout: default request timeout
    :param retries: retry times
    :param backoff_factor: retry backoff
    :param proxies: requests proxies dict, e.g.
        {
            "http": "socks5h://127.0.0.1:1080",
            "https": "socks5h://127.0.0.1:1080",
        }
    """

    def _wrap_timeout(func, timeout):
        def wrapper(*args, **kwargs):
            kwargs.setdefault("timeout", timeout)
            return func(*args, **kwargs)
        return wrapper

    session = requests.Session()

    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    })

    if proxies:
        session.proxies.update(proxies)

    session.request = _wrap_timeout(session.request, timeout)

    return session


def is_ipv4(addr):
    try:
        socket.inet_aton(addr)
        return addr.count('.') == 3
    except socket.error:
        return False
