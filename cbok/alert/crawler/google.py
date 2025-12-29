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

    def login(self, username, password):
        return self.login_manager(username, password)

    def analysis_index(self):
        # gl = self.login('kodanevhyz@gmail.com', 'Everlost584@')
        # cookies = gl.retrieve_cookies()

        headers = cbok_utils.construct_headers()
        self.session.headers.update(headers)
        # session_cookies = {cookie['name']: cookie['value'] for cookie in cookies}
        # print(session_cookies)
        session_cookies = {'__Secure-3PSIDCC': 'AKEyXzUJ1lYKuPSquXhuETdjMtXDUNFvLjAMEFlS_9L5F0OB8oGAG73jid1ffz0iXnLwlSWrpg', '__Secure-1PSIDCC': 'AKEyXzXsIyRJ8VS7jz1Mr9Oq9s5qfQ8dmxYLLJJZt6sWndweWb6JYVE8UIRHtK8LfYgP1kjUgQ', 'SIDCC': 'AKEyXzXDgTGHOIur66NzGeqesu22zwLhMFXcMD6lNlpuhP6iuqU4IfKw-WZDeDe_NLDo9XJE', 'OSID': 'g.a0004ggf51HvPLMI8APTV8YexAbACoWl532r36vudmBr-hGahwXEJdh9k6P_8-JyAwuv1S1_SAACgYKARkSARISFQHGX2MiZLsNiquz4b_ws-hK3xFS1xoVAUF8yKpD5lMvMGmUj7oUDUo4_WAM0076', 'APISID': 'dsHbICFrXcQzfSai/Ad6zVTRACqrVf0geo', 'SSID': 'APjFejBdBbqZCpgli', 'SAPISID': 'egql_kJi9bnGoDCF/Ar6RUuZK-H7ESZLJM', 'HSID': 'AiDQEQfXRB9fy9iGP', 'NID': '527=qfA3uirAMsjjOzWy8h2LhNFfPecGBvv2zRFSlKHI-0yc_rDJ0AgLnimfQf3QQOUukR9Zqt2OIL8xabQh8BgoTln4vPzIubdqhNAh9K_V4Z0FMILUqY_6JBpk9XH33YMavyJJfhMUiOu1Axx5iJLoHBiYavHZzUW5E9eD3lGPXcnQfqmIawr32rHBwlmLk2dUECcu0p74WGAXYZ-ZT-ky1ha2ugNNPoIhmnnBCsFLVPIzRmolJBb0EmvIsbBv6uFBgPhaYCBSloWgcUP5oDiBbNtSerXYZza54f8SwtVXh2i4qiHQgPv1wJoSt8_VyQyBxSgYVD_32-8_y39AT3G6jL-T5aQEIglXiYoFyvt-vfbDHq6ZbDr8zVp7uF5UZXSMOGCJympu-9xngnF5mirOnG2DP9EbeQAzv4wtk1dTEeDeFzbBgUnKxKlhiyYHp47y2yu7ypAN53fUUs26VaCcqoBHdVN9d7BMTbwXvSY06X6XZe0FNSzfA3IZeOffeBag_z_HQeMxYqpVdJgdLa5h3E2cp1q48y-8n_yhXbPqLpKuOJCBpYEZh7pgpGFY4dus7cxp-605E2JwFdIz8sSinScxHqI_Ekzp5iX00bFpoYeC3HFWynGaflu1Y1xdkbxTrJrZh_P5oqhnue5pD86PGuHDezc-wDtyQPsmT0tq6Q', '__Secure-3PSID': 'g.a0004ggf539KI_fLEWcHdh0OL_sKZaqnu72noK134ByUFhAKvmJoU_oxK82zRhDbU6daUitiNgACgYKATISARISFQHGX2Mim9yTDGPeiFRW5O8vp907GhoVAUF8yKralwKXqGZAnCIUgpAg8xmW0076', '__Secure-BUCKET': 'CKYD', '__Secure-1PSID': 'g.a0004ggf539KI_fLEWcHdh0OL_sKZaqnu72noK134ByUFhAKvmJoAGSs07DTyMnZ0gXOzvd7tAACgYKAS0SARISFQHGX2MirHs2f_5_hfXrg2pMbnF9URoVAUF8yKooQUgHpd7y1w4aM0UNh2lQ0076', '__Secure-OSID': 'g.a0004ggf51HvPLMI8APTV8YexAbACoWl532r36vudmBr-hGahwXEkbJJaevFOJc4HS_2a_h_2wACgYKAdISARISFQHGX2Mig_1-XxIu-eh1V543nW0HMhoVAUF8yKqCfcZQ07gH46kmLX4LKn1c0076', '__Secure-3PAPISID': 'egql_kJi9bnGoDCF/Ar6RUuZK-H7ESZLJM', '__Secure-1PAPISID': 'egql_kJi9bnGoDCF/Ar6RUuZK-H7ESZLJM', 'SID': 'g.a0004ggf539KI_fLEWcHdh0OL_sKZaqnu72noK134ByUFhAKvmJoEM63_7OX58CC6hfAkOpwLgACgYKAQUSARISFQHGX2Mi_ucZAReliULaoeheFFrY5RoVAUF8yKqHQXvjcN-9HHLiz1QV4xi10076'}

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
