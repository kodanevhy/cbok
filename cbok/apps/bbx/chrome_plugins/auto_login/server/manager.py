import base64
import logging
import os.path
import re
import time
import urllib3
from urllib3 import exceptions
from urllib3 import util
from urllib import parse

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
        query_string = None
        if query:
            query_string = '&'.join([f'{k}={v}' for k, v in query.items()])
        url = f'{url}?{query_string}'
        try:
            with cbok_utils.suppress_logs("urllib3", level=logging.ERROR):
                response = self.pool_manager.request(
                    'GET', url, timeout=self.timeout)
            status_code = response.status
            if 'Wrong URL' in response.data.decode('utf-8'):
                return
            if status_code == 200 and type(response.data) == bytes:
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
        except urllib3.exceptions.MaxRetryError:
            pass
        except urllib3.exceptions.RequestError:
            pass

    def _resolve_form_csrftoken(self, url):
        html_byte = self.get_login_page(url)
        if not html_byte:
            # Request error means no such environment for test or
            # network unreachable, just ignore the address and use
            # default passphrase.
            return
        html_str = html_byte.decode('utf-8')

        index_str = '<input type=\'hidden\' name=\'csrfmiddlewaretoken\' ' \
                    'value=\''
        start = html_str.find(index_str) + len(index_str)
        end = start + 32
        csrf = html_str[start: end]
        return csrf

    @staticmethod
    def persistent(address, username, password):
        home = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target = os.path.join(home, 'passphrase')
        existing_data = []
        try:
            with open(target, 'r', encoding='utf-8') as t:
                for line in t.readlines():
                    parts = line.strip().split(',')
                    existing_data.append(parts)
        except FileNotFoundError:
            pass

        new_record = [address, username, password]
        if new_record not in existing_data:
            LOG.info(f"Persisting {address} by {password}")
            existing_data.append(new_record)
            sorted_data = sorted(existing_data, key=lambda x: x[0])

            with open(target, 'w', encoding='utf-8') as file:
                for record in sorted_data:
                    file.write(','.join(record) + '\n')
        else:
            LOG.info(f"{address} already ready")

    @staticmethod
    def base64_encode(s):
        return base64.b64encode(s.encode('utf-8')).decode('utf-8')

    @staticmethod
    def remove(address):
        if not address:
            return

        home = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target = os.path.join(home, 'passphrase')
        with open(target, 'r') as file:
            lines = file.readlines()

        matched = any(line.startswith(address + ",") for line in lines)
        if not matched:
            return

        LOG.info(f"Removing {address}")

        filtered_lines = [line for line in lines
                          if not line.startswith(address)]
        with open(target, 'w') as file:
            file.writelines(filtered_lines)

    @staticmethod
    def parse_current():
        parsed = dict()
        home = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target = os.path.join(home, 'passphrase')
        with open(target, 'r') as t:
            lines = t.readlines()
            for line in lines:
                line = line.rstrip('\n')
                address = line.split(',')[0]
                username = line.split(',')[1]
                password = line.split(',')[2]
                parsed.update({address: {username: password}})
        return parsed

    @staticmethod
    def pre_clean_passphrase():
        """Pre clean passphrase before handle"""

        home = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target = os.path.join(home, 'passphrase')
        with open(target, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        rows = [line.split(",") for line in lines]
        counts = {}
        for row in rows:
            ip = row[0]
            counts[ip] = counts.get(ip, 0) + 1

        filtered_rows = [row for row in rows if counts[row[0]] == 1]

        with open(target, "w", encoding="utf-8") as f:
            for row in filtered_rows:
                f.write(",".join(row) + "\n")

    def try_login_and_persistent(self, viewer_address=None,
                                 viewer_password=None):
        def _worker():
            for password in possible_password:
                if password == 'test@passw%srd' and \
                        re.match(r'^172\.\d+\.0\.2$', addr):
                    env_id = addr.split('.')[1]
                    password = password % env_id
                cookie = {
                    'csrftoken': csrf
                }
                body = {
                    'username': username,
                    'password': self.base64_encode(password),
                    'csrfmiddlewaretoken': csrf
                }
                status_code = self.try_login(url, cookie, body)
                if status_code == 405:
                    self.persistent(addr, username, password)
                    return True

        self.pre_clean_passphrase()

        username = 'admin@example.org'
        current_parsed = self.parse_current()
        current_addresses = current_parsed.keys()

        if viewer_address and viewer_password:
            # If it comes from viewer, no need to check current.
            addr = viewer_address
            possible_password = [viewer_password]

            url = 'https://%s/ems_dashboard_api/auth_login/' % viewer_address
            csrf = self._resolve_form_csrftoken(url)
            if not csrf:
                self.remove(viewer_address)
                return

            if addr == '100.100.3.21':
                possible_password = ["Admin@Compute1"]

            if not _worker():
                self.remove(addr)
        else:
            LOG.info("Running fully sync")
            LOG.info(f"Starting view: {current_parsed}")

            # We need to check current record first, if failed, remove.
            addresses = sorted(set(list(current_addresses) + list(self.ADDRESS)))

            for addr in addresses:
                possible_password = list(self.POSSIBLE_PASSWORD)

                url = 'https://%s/ems_dashboard_api/auth_login/' % addr
                csrf = self._resolve_form_csrftoken(url)
                if not csrf:
                    self.remove(addr)
                    continue

                if addr == '100.100.3.21':
                    possible_password.insert(0, 'Admin@Compute1')

                # Use stored password to verify first
                if addr in current_addresses:
                    password = current_parsed.get(addr).get(username)
                    if password not in possible_password:
                        possible_password.insert(0, password)

                if not _worker():
                    self.remove(addr)
            LOG.info("Fully sync finished")

        return True


def run():
    manager = LoginManager()
    manager.try_login_and_persistent()


if __name__ == '__main__':
    while True:
        run()
        time.sleep(600)
