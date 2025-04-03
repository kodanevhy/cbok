import base64
import os.path
import re

import urllib3
from urllib3 import exceptions
from urllib3 import util
from urllib import parse


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
        home = os.path.dirname(os.path.abspath(__file__))
        target = os.path.join(home, 'static/passphrase')
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
            existing_data.append(new_record)
            sorted_data = sorted(existing_data, key=lambda x: x[0])

            with open(target, 'w', encoding='utf-8') as file:
                for record in sorted_data:
                    file.write(','.join(record) + '\n')

    @staticmethod
    def base64_encode(s):
        return base64.b64encode(s.encode('utf-8')).decode('utf-8')

    @staticmethod
    def remove(address):
        if not address:
            return

        home = os.path.dirname(os.path.abspath(__file__))
        target = os.path.join(home, 'static/passphrase')
        with open(target, 'r') as file:
            lines = file.readlines()

        filtered_lines = [line for line in lines
                          if not line.startswith(address)]

        with open(target, 'w') as file:
            file.writelines(filtered_lines)

    @staticmethod
    def parse_current():
        parsed = dict()
        home = os.path.dirname(os.path.abspath(__file__))
        target = os.path.join(home, 'static/passphrase')
        with open(target, 'r') as t:
            lines = t.readlines()
            for line in lines:
                line = line.rstrip('\n')
                address = line.split(',')[0]
                username = line.split(',')[1]
                password = line.split(',')[2]
                parsed.update({address: {username: password}})
        return parsed

    def try_login_and_persistent(self):
        current_parsed = self.parse_current()
        current_addresses = current_parsed.keys()
        if len(self.ADDRESS) == 1:
            # If it comes from viewer, no need to check current.
            current_addresses = []

        # We need to check current record first, if failed, remove.
        addresses = list(set(current_addresses + self.ADDRESS))
        for addr in addresses:
            url = 'https://%s/ems_dashboard_api/auth_login/' % addr
            csrf = self._resolve_form_csrftoken(url)
            if not csrf:
                continue

            possible_password = self.POSSIBLE_PASSWORD
            if addr == '100.100.3.21':
                possible_password.insert(0, 'Admin@Compute1')

            username = 'admin@example.org'
            if addr in current_addresses:
                password = current_parsed.get(addr).get(username)
                possible_password.insert(0, password)

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
                    break
            else:
                self.remove(addr)
        return True


def run():
    manager = LoginManager()
    # spend about 15 minutes
    manager.try_login_and_persistent()

if __name__ == '__main__':
    run()
