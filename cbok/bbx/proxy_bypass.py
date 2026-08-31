import re


NETWORKSETUP = "/usr/sbin/networksetup"
ROUTE = "/sbin/route"


class ProxyBypassError(RuntimeError):
    pass


def read_bypass_domains(conf):
    if not conf.has_section("proxy"):
        raise ProxyBypassError("Missing [proxy] in cbok.conf.")
    if not conf.has_option("proxy", "bypass_domains"):
        raise ProxyBypassError("cbok.conf [proxy] needs bypass_domains.")

    raw = conf.get("proxy", "bypass_domains")
    domains = []
    for line in raw.splitlines():
        for item in line.split(","):
            domain = item.strip()
            if domain:
                domains.append(domain)

    if not domains:
        raise ProxyBypassError("cbok.conf [proxy] bypass_domains is empty.")
    return domains


def _run_checked(runner, cmd, **kwargs):
    result = runner.run_command(cmd, **kwargs)
    if result.returncode != 0:
        detail = (result.stdout or result.stderr or "").strip()
        if detail:
            raise ProxyBypassError(f"Command failed: {' '.join(cmd)}\n{detail}")
        raise ProxyBypassError(f"Command failed: {' '.join(cmd)}")
    return result


def _current_default_interface(runner):
    result = _run_checked(
        runner,
        [ROUTE, "-n", "get", "default"],
        log_output=False,
    )
    for line in result.stdout.splitlines():
        if line.strip().startswith("interface:"):
            return line.split(":", 1)[1].strip()
    raise ProxyBypassError("Unable to find default route interface.")


def resolve_current_wifi_service(runner=None):
    from cbok import utils as cbok_utils

    runner = runner or cbok_utils.UnifiedProcessRunner()
    interface = _current_default_interface(runner)
    result = _run_checked(
        runner,
        [NETWORKSETUP, "-listnetworkserviceorder"],
        log_output=False,
    )

    service = None
    matched_non_wifi = None
    service_re = re.compile(r"^\(\d+\)\s+(.+)$")
    hardware_re = re.compile(r"^\(Hardware Port:\s*(.*?),\s*Device:\s*([^)]+)\)$")

    for line in result.stdout.splitlines():
        service_match = service_re.match(line.strip())
        if service_match:
            service = service_match.group(1).strip()
            continue

        hardware_match = hardware_re.match(line.strip())
        if not hardware_match or not service:
            continue

        hardware_port = hardware_match.group(1).strip()
        device = hardware_match.group(2).strip()
        if device != interface:
            continue
        if hardware_port == "Wi-Fi":
            return service
        matched_non_wifi = f"{service} ({hardware_port}, {device})"

    if matched_non_wifi:
        raise ProxyBypassError(
            f"Current default route service is not a Wi-Fi service: {matched_non_wifi}"
        )
    raise ProxyBypassError(
        f"Unable to map default route interface {interface} to a Wi-Fi network service."
    )


def apply_bypass_domains(domains, runner=None):
    from cbok import utils as cbok_utils

    runner = runner or cbok_utils.UnifiedProcessRunner()
    domains = [str(domain).strip() for domain in domains if str(domain).strip()]
    if not domains:
        raise ProxyBypassError("No proxy bypass domains to apply.")

    service = resolve_current_wifi_service(runner)
    _run_checked(
        runner,
        [NETWORKSETUP, "-setproxybypassdomains", service] + domains,
    )
    return service
