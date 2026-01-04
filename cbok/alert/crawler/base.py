from bs4 import BeautifulSoup
import logging
import re
import tldextract

from cbok.alert import models
from cbok import utils as cbok_utils
from cbok.alert.login import base as login_base

LOG = logging.getLogger(__name__)

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)

class BaseCrawler(object):
    INDEX = str()

    def __init__(self, use_proxy=False):
        if use_proxy:
            self.session = cbok_utils.create_session(
                retries=False, proxies=cbok_utils.load_proxies())
        else:
            self.session = cbok_utils.create_session(retries=False)
        self.login_manager = login_base.BaseLogin

    def _init_login_manager(self, username, password):
        return self.login_manager(username, password)

    def ensure_cookies(self, username, password):
        lm = self._init_login_manager(username, password)

        session_cookies = \
            lm.ensure_cookies(page_site=self.INDEX)
        domain = tldextract.extract(self.INDEX).domain
        if session_cookies:
            LOG.debug(f"Found stashed and valid cookie of {domain}")

        if not session_cookies or session_cookies == -1:
            LOG.debug(f"No valid cookie found, logging to "
                     f"{domain}")
            session_cookies = lm.retrieve_cookies()

        return session_cookies

    def dedup(self, belong_topic, url):
        return models.Article.objects.filter(
            topic=belong_topic,
            url=url,
        ).exists()

    def fetch_article(self, url):
        title = None
        date = None
        content = None

        resp = self.session.get(url)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        title = (
            soup.title.string.strip()
            if soup.title and soup.title.string
            else ""
        )

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        date_patterns = [
            r"(\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2}[日]?)",
            r"(\d{4}-\d{1,2}-\d{1,2} \d{2}:\d{2})",
            r"(\d{4}/\d{1,2}/\d{1,2} \d{2}:\d{2})"
        ]
        for pattern in date_patterns:
            match = re.search(pattern, resp.text)
            if match:
                date = match.group(1)

        paragraphs = [
            p.get_text(strip=True)
            for p in soup.find_all("p")
            if len(p.get_text(strip=True)) > 0
        ]

        content = "\n\n".join(paragraphs)

        return {
            "title": title,
            "date": date,
            "content": content
        }
