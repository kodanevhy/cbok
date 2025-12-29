import base64
import ipaddress
import logging
import re
import time
from urllib import parse
import urllib3
from urllib3 import exceptions, util

from cbok.bbx.models import ChromePluginAutoLoginHostInfo
from cbok import utils as cbok_utils

LOG = logging.getLogger(__name__)


class LoginManager:
    def __init__(self):
        self.ADDRESS = [f'172.{i}.0.2' for i in range(30, 120)]
        self.ADDRESS.insert(0, '100.100.3.21')
        self.POSSIBLE_PASSWORD = [
            'test@passw0rd',
            'Admin@ES20!8',
            'test@passw%srd'
        ]
        self.pool_manager = urllib3.PoolManager(cert_reqs='CERT_NONE')
        urllib3.disable_warnings(exceptions.InsecureRequestWarning)

        # not very accurate
        self.timeout = util.timeout.Timeout(connect=3, read=3)

    def get_login_page(self, url, query=None):
        query_string = '&'.join([f'{k}={v}' for k, v in query.items()]) if query else None
        url = f'{url}?{query_string}' if query_string else url
        try:
            with cbok_utils.suppress_logs("urllib3", level=logging.ERROR):
                response = self.pool_manager.request(
                    'GET', url, timeout=self.timeout)
            status_code = response.status
            if 'Wrong URL' in response.data.decode('utf-8'):
                return
            if status_code == 200 and isinstance(response.data, bytes):
                return response.data
        except exceptions.MaxRetryError:
            pass
        except exceptions.RequestError:
            pass

    def try_login(self, url, cookies, body):
        headers = {
            'Cookie': '; '.join([f'{k}={v}' for k, v in cookies.items()]),
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        try:
            body = parse.urlencode(body)
            with cbok_utils.suppress_logs("urllib3", level=logging.ERROR):
                response = self.pool_manager.request(
                    'POST',
                    url,
                    body=body,
                    headers=headers,
                    timeout=self.timeout
                )
            return response.status
        except exceptions.MaxRetryError:
            pass
        except exceptions.RequestError:
            pass

    def _resolve_form_csrftoken(self, url):
        html_byte = self.get_login_page(url)
        if not html_byte:
            return
        html_str = html_byte.decode('utf-8')
        index_str = "<input type='hidden' name='csrfmiddlewaretoken' value='"
        start = html_str.find(index_str) + len(index_str)
        end = start + 32
        return html_str[start:end]

    @staticmethod
    def base64_encode(s):
        return base64.b64encode(s.encode('utf-8')).decode('utf-8')

    @staticmethod
    def get_current_hosts():
        parsed = {}
        hosts = ChromePluginAutoLoginHostInfo.objects.all()
        for h in hosts:
            parsed[h.ip_address] = {h.username: h.password}
        return parsed

    @staticmethod
    def save_host(ip_address, username, password):
        obj, created = ChromePluginAutoLoginHostInfo.objects.update_or_create(
            ip_address=ip_address,
            username=username,
            defaults={'password': password}
        )
        if created:
            LOG.info(f"Created host {ip_address} with password {password}")
        else:
            LOG.info(f"Updated host {ip_address} with password {password}")

    @staticmethod
    def remove_host(ip_address):
        if ChromePluginAutoLoginHostInfo.objects.filter(ip_address=ip_address).exists():
            ChromePluginAutoLoginHostInfo.objects.filter(ip_address=ip_address).delete()
            LOG.info(f"Removed host {ip_address}")

    def try_login_and_persistent(self, viewer_address=None, viewer_password=None):
        def _worker(addr, username, csrf, possible_password, url):
            for password in possible_password:
                if password == 'test@passw%srd' and re.match(r'^172\.\d+\.0\.2$', addr):
                    env_id = addr.split('.')[1]
                    password = password % env_id
                cookie = {'csrftoken': csrf}
                body = {'username': username, 'password': self.base64_encode(password), 'csrfmiddlewaretoken': csrf}
                status_code = self.try_login(url, cookie, body)
                if status_code == 405:
                    self.save_host(addr, username, password)
                    return True
            return False

        username = 'admin@example.org'
        current_parsed = self.get_current_hosts()
        current_addresses = current_parsed.keys()

        addresses = []
        if viewer_address and viewer_password:
            addresses = [(viewer_address, [viewer_password])]
        else:
            addresses = [(addr, list(self.POSSIBLE_PASSWORD)) for addr in sorted(
                set(list(current_addresses) + list(self.ADDRESS)),
                key=lambda ip: ipaddress.ip_address(ip)
            )]

        for addr, possible_password in addresses:
            url = f'https://{addr}/ems_dashboard_api/auth_login/'
            csrf = self._resolve_form_csrftoken(url)
            if not csrf:
                self.remove_host(addr)
                continue

            if addr == '100.100.3.21':
                possible_password.insert(0, 'Admin@Compute1')

            # Use stored password first
            if addr in current_addresses:
                password = current_parsed.get(addr).get(username)
                if password not in possible_password:
                    possible_password.insert(0, password)

            if not _worker(addr, username, csrf, possible_password, url):
                self.remove_host(addr)

        LOG.info("Fully sync finished")
        return True


def run():
    manager = LoginManager()
    manager.try_login_and_persistent()


if __name__ == '__main__':
    while True:
        run()
        time.sleep(600)
