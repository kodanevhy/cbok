from bs4 import BeautifulSoup
import re
from readability import Document
import requests

from cbok.apps.alert import common


class ArticleCrawler:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(common.HEADERS)

    def fetch(self, url):
        response = self.session.get(url, timeout=10)
        response.encoding = response.apparent_encoding

        doc = Document(response.text)
        title = doc.title()

        soup = BeautifulSoup(doc.summary(), "lxml")
        content = soup.get_text(separator="\n", strip=True)

        pub_date = self.extract_date(response.text)

        return {
            "title": title,
            "date": pub_date,
            "content": content
        }

    @staticmethod
    def extract_date(html):
        date_patterns = [
            r"(\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2}[日]?)",
            r"(\d{4}-\d{1,2}-\d{1,2} \d{2}:\d{2})",
            r"(\d{4}/\d{1,2}/\d{1,2} \d{2}:\d{2})"
        ]
        for pattern in date_patterns:
            match = re.search(pattern, html)
            if match:
                return match.group(1)
        return None


if __name__ == "__main__":
    crawler = ArticleCrawler()
    url = "https://finance.sina.com.cn/jjxw/2025-12-01/doc-infzhiak3246200.shtml"
    result = crawler.fetch(url)

    print("\n=== Title ===")
    print(result["title"])

    print("\n=== Date ===")
    print(result["date"])

    print("\n=== Content ===")
    print(result["content"])
