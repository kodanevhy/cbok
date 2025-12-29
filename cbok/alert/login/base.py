import logging
import json
import os
import tldextract

from cbok import utils as cbok_utils

LOG = logging.getLogger(__name__)


class BaseLogin(object):
    URL = 'https://www.baselogin.com'

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.session = cbok_utils.create_session(retries=False)

    @property
    def target(self):
        return tldextract.extract(self.URL).domain

    def ensure_cookies(self, page_site):
        def _load_cookie():
            filename=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "cookie.json")
            if not os.path.exists(filename):
                return None

            with open(filename, "r", encoding="utf-8") as f:
                all_cookies = json.load(f)

            return all_cookies.get(tldextract.extract(page_site).domain)

        cookies = _load_cookie()
        if not cookies:
            return None

        resp = self.session.get(page_site, cookies=cookies, timeout=10)

        if resp.status_code == 200:
            return cookies
        else:
            return -1

    def persist_cookie(self, target, raw_cookies):
        filename=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "cookie.json")

        cookies = {cookie['name']: cookie['value'] \
            for cookie in raw_cookies}

        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                try:
                    all_target_cookies = json.load(f)
                except json.JSONDecodeError:
                    all_target_cookies = {}
        else:
            all_target_cookies = {}

        all_target_cookies[target] = cookies

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(all_target_cookies, f, indent=2, ensure_ascii=False)

        LOG.info(f"Cookies of {self.target} are persisted")

    def login(self):
        pass

    def retrieve_cookies(self):
        pass
