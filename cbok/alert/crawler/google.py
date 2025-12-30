import ast
from bs4 import BeautifulSoup
import logging
import re
import time
from urllib import parse

from cbok.alert.crawler import base
from cbok.alert.login import google
from cbok import utils as cbok_utils

LOG = logging.getLogger(__name__)


class GoogleAlertCrawler(base.BaseCrawler):
    INDEX = 'https://www.google.com/alerts'
    HISTORY = 'https://www.google.com/alerts/history'

    def __init__(self):
        super().__init__()
        self.login_manager = google.GoogleLogin

    def analysis_index(self):
        session_cookies = self.ensure_cookies(
            "kodanevhyz@gmail.com", "Everlost584@")

        headers = cbok_utils.construct_headers()
        self.session.headers.update(headers)

        page = self.session.get(self.INDEX, cookies=session_cookies)
        if page.status_code != 200:
            raise

        pattern = r'window.STATE\s*=\s*(\[.*?\]);'
        match = re.search(pattern, page.text)
        if match:
            state_content = match.group(1)
            state_content = state_content.replace('null', 'None')
            state_content = state_content.replace('false', 'False')
            state_content = state_content.replace('true', 'True')

            try:
                state_data = ast.literal_eval(state_content)
                r = {}
                for s in state_data[0]:
                    for a in s:
                        alert_name = a[1][2][0]
                        alert_id = a[1][5][0][-1]
                        r.update({alert_name: alert_id})
                return r, session_cookies
            except SyntaxError:
                raise
        else:
            print("window.STATE field not found")
            raise

    def _extract_article_url(self, google_url):
        """
        Input example:
        https://www.google.com/url?rct=j&sa=t&url=$real_url
        
        return: real_url
        """
        parsed = parse.urlparse(google_url)
        qs = parse.parse_qs(parsed.query)
        real_url = parse.unquote(qs["url"][0])

        return real_url

    def analysis_history(self, name, date=7):
        now = int(time.time())
        d = 86400 * date
        # That mean the past `date` days by default
        params = f'[null,null,{now},{d}]'
        indexed, session_cookies = self.analysis_index()
        sid = indexed[name]
        url = f'{self.HISTORY}?params={parse.quote(params)}&s={sid}'

        r = self.session.get(url, cookies=session_cookies)

        html = r.text.encode('utf-8')

        soup = BeautifulSoup(html, 'html.parser')

        results = []

        for message in soup.find_all('div', class_='history_message'):
            date_elem = message.find('span', class_='age')
            date = date_elem.text.strip() if date_elem else 'unknown'

            source_type_elem = message.find('h3', class_='source')
            source_type = source_type_elem.text.strip() if source_type_elem else 'unknown'

            for result in message.find_all('li', class_='result'):
                title_elem = result.find('a', class_='result_title_link')
                source_elem = result.find('div', class_='result_source')
                snippet_elem = result.find('span', class_='snippet')

                if not title_elem or not snippet_elem:
                    continue

                title = title_elem.text.strip()
                article_url = self._extract_article_url(title_elem.get('href', ''))

                source = source_elem.text.strip() if source_elem else ''
                snippet = snippet_elem.text.strip()

                keywords = []
                if snippet_elem:
                    bold_elems = snippet_elem.find_all('b')
                    keywords = [b.text.strip() for b in bold_elems if b.text.strip()]

                results.append({
                    'date': date,
                    'type': source_type,
                    'title': title,
                    'source': source,
                    'snippet': snippet,
                    'url': article_url,
                    'keywords': keywords
                })

        return results
