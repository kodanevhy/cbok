from bs4 import BeautifulSoup
import logging
import re

from cbok import utils as cbok_utils
from cbok.alert import models

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)

class BaseCrawler(object):
    INDEX = str()

    def __init__(self):
        self.session = cbok_utils.create_session(retries=False)
        self.login_manager = None

    def login(self, username, password):
        pass

    def dedup(self, belong_topic, url):
        # get all article urls in this topic
        # models.Article
        # check if exists
        pass

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
