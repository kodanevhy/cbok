import ast
import logging
import re
import time
import urllib.parse

from bs4 import BeautifulSoup

from alert import common
from alert.login import google
from alert.manager import base

LOG = logging.getLogger(__name__)


class GoogleAlertManager(base.BaseAlertManager):
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

        self.session.headers.update(common.HEADERS)
        # session_cookies = {cookie['name']: cookie['value'] for cookie in cookies}
        # print(session_cookies)
        session_cookies = {'__Secure-1PSIDCC': 'AKEyXzXXpT9ulpUwNrhRHAoQbJTarZ0pM-G8Crj-lzfDhs_0k0e7IevXkWti5wM4Wg5b2hn5AA', 'SIDCC': 'AKEyXzVpSXsrHxRm13g6T0sBTcmkvDAwcD4b4Uv_QquCbcrvQaOpfnBpycpIaYiEMUzOYCmo', '__Secure-3PSIDTS': 'sidts-CjEB7pHptWQBKpfh646v_Ha2lWpTjSLsxv9IyeUbdLhmu7G9ZiFTOj_8es-1BlCNjf0TEAA', '__Secure-OSID': 'g.a000wAgf5-g10csqP8a6dO7YQun7sDOVHLPrBZx95VJy21opwagA9NNLg8oJrFzen2U7PSgpKwACgYKAVkSARISFQHGX2Mi6GKd1uUc_vzqmTHiQEJMxRoVAUF8yKpKvu5g-fU2PICqqtDtYoZn0076', 'OTZ': '8048882_24_24__24_', 'OSID': 'g.a000wAgf5-g10csqP8a6dO7YQun7sDOVHLPrBZx95VJy21opwagAZeQ4fldraQtliHFfdV873AACgYKASoSARISFQHGX2MikXiEiHaLAqP0uN2uFz3PxhoVAUF8yKrwdGhl9O-7LbS68Vjg0ro10076', '__Secure-3PAPISID': 'ZewdmDA5TFTkTray/A2jZZ-Xa7dkdQ9Bir', 'SAPISID': 'ZewdmDA5TFTkTray/A2jZZ-Xa7dkdQ9Bir', '__Secure-1PSIDTS': 'sidts-CjEB7pHptWQBKpfh646v_Ha2lWpTjSLsxv9IyeUbdLhmu7G9ZiFTOj_8es-1BlCNjf0TEAA', 'SID': 'g.a000wAgf5wFZgZIQc7Z1Q3RRDO1HKGIAyEEfdDy-cFK7nLQSfCV99f5w9XzSTeM1nfGlQKNTLgACgYKAQESARISFQHGX2Mi3g-wSa4SU4KTYldIYogv2hoVAUF8yKo3M2urDS3nGkI1wQ_cCfDI0076', '__Secure-3PSIDCC': 'AKEyXzWSTnpMFyBuU2qWb7fKnsl1gQEFoKE4Bbk2yVHsJuraMZdh-m4KeYlLfw7bK3doCPw', '__Secure-3PSID': 'g.a000wAgf5wFZgZIQc7Z1Q3RRDO1HKGIAyEEfdDy-cFK7nLQSfCV9tdNeo56EJUXjak6j1wU63AACgYKAVcSARISFQHGX2MiI1Rjh-XMaYmyJd8wKh-FiRoVAUF8yKq5ikja-YzDGL_g28oTEqLj0076', 'HSID': 'A2QBMStqIvox4N_bT', '__Secure-1PAPISID': 'ZewdmDA5TFTkTray/A2jZZ-Xa7dkdQ9Bir', 'APISID': 'IBsTHgbB49zy3mZZ/ALh1FpRXm2cjOc9yu', 'NID': '523=Ke5gIuwGtXI2mMqR2N0q-aoK4qfQRR-4C1_LLKpPHZhxnCTqcr5cmzr6AblxO3ckzoV02110ZR1-YY_guISbRms0gY8J_vz7OMKfji5KtKQObBc7rmfIB_VunJc5uYNJsgpGr7BgPkBz0X9QaVAmd_P8nuqVM5hUgwnNtNzhU6WaorwbpUi_qF5Qt7Jzrs_cy79QeULytX5jReF4ALx05A8xt4t3oXlnn--51hJ0vPGsv8e4QSUMhnsoZuVEYfEO0boXnTX4Wt-Lu9uG1cIM_7kxyuwoap0hBNi2dhYFUhce9Cuyp-4fXBfpKj4V94rfwWKVOKmZyAe9D7zVEAGH9JBKSG3s0C8iFPBkpPnQ2bfkUdh35iEV4uNXRRosYrfvZX_6ZJ-Rin4nvMXE7bClEVruANPm8qgY8byc0mbMos1efA-xI_DUcRPJvP12Xn6gmfBHnC4C4Bv_lNzW7BeYDxwf5G0zge-cGEtZyg0-X1xXKAzTGhP4BgV9w4h9FCTewO0OnXgcLwse5Ia56o7WAs4tj4Yg_bEpI_Q1yjOybhcgRZaaPcK7CqfGrdqZ9m7jYQB8rpUCcx01k0N2Cs1qBeFcFmliz39W_I1Ms0oSSjHu3pC4jm27ol9XWh8z29TnpxsPJRbtZklSfOHxZFk_Sy7wpeRLrjtJEO6U', 'SSID': 'A56SLulMZrnwzzYYd', '__Secure-1PSID': 'g.a000wAgf5wFZgZIQc7Z1Q3RRDO1HKGIAyEEfdDy-cFK7nLQSfCV9eLCujJ3mQQSwhnDv-91d0wACgYKAb4SARISFQHGX2Mi-p56cXjhVkm-nR4PUWOgXxoVAUF8yKr_gFLJx5uXGU2cJL0RZMLA0076'}

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
                return r
            except SyntaxError:
                print("解析失败，可能是数据格式不符合 Python 语法。")
        else:
            print("未找到 window.STATE 字段。")


    def analysis_history(self, name):
        now = int(time.time())
        # Based data from the first 7 days, I do not recommend
        # you to turn it up, cuz it's usually useless
        d = 604800 * 1
        params = f'[null,null,{now},{d}]'
        sid = self.analysis_index()[name]
        url = f'{self.HISTORY}?params={urllib.parse.quote(params)}&s={sid}'
        session_cookies = {'__Secure-1PSIDCC': 'AKEyXzXhaMIooZbRsJzQni-Emz2V7z_go7qGnsYatjyPTyv0e9uGo-kYjatAVQ1UbblrjsIT', 'SIDCC': 'AKEyXzXoWt2he7PEcIkMi-F028BCE1anOcUt-lwkbahYle-UtSx_Xic66zdqKOOTwt4G2OZhlA', '__Secure-3PSIDTS': 'sidts-CjEB7pHptYMJL7LlMloMZ2Y7PXQ2p0ZMov_maF-uQGuGZJJGVe3XNsufgARcn91ZcwLlEAA', '__Secure-OSID': 'g.a000wAgf54x5w4eV8eP6F2zw5KE2KXFFhiu_me1WTu01oLieIoHS9U9tW5IQxXLSWzcnSsYcqQACgYKAWMSARISFQHGX2MizBmRKxN8HmJNWGXrYxRuqBoVAUF8yKrSUVFioJDJaKw91xOSQ-J10076', 'OTZ': '8048921_24_24__24_', 'OSID': 'g.a000wAgf54x5w4eV8eP6F2zw5KE2KXFFhiu_me1WTu01oLieIoHSxUG6-ThOdglaoy2rrn73hQACgYKAUoSARISFQHGX2MioF-UfiiyvYb-ZB_XYDo_CxoVAUF8yKoBvbpd7_F51NRm1CQ6JWfY0076', '__Secure-3PAPISID': 'WJpxO0qol6873PJf/ASNrXbdWDRKj0qE8G', 'SAPISID': 'WJpxO0qol6873PJf/ASNrXbdWDRKj0qE8G', '__Secure-1PSIDTS': 'sidts-CjEB7pHptYMJL7LlMloMZ2Y7PXQ2p0ZMov_maF-uQGuGZJJGVe3XNsufgARcn91ZcwLlEAA', 'SID': 'g.a000wAgf5xBEtPItfG2JFEvF9szskOVLMUfcQ9Fz-uD3NKSYQN6JmvclRYaymZHNRZh4ePS_5wACgYKASYSARISFQHGX2MiHGZ19358qme06Kz08L3gaRoVAUF8yKpiZPcLGXCcgr1rbTQrmSQu0076', '__Secure-3PSIDCC': 'AKEyXzWkAwNgNuGRFgRHdWDcYvTEUawcO78FjHWrqwjMN_I7pvWUaMlkDTfYd2BrkYrcSJZTng', '__Secure-3PSID': 'g.a000wAgf5xBEtPItfG2JFEvF9szskOVLMUfcQ9Fz-uD3NKSYQN6JVobDK7uBd8bkEO1R2lro1wACgYKAfMSARISFQHGX2MiCtqg5LO1mZNhFlTobdGIFBoVAUF8yKqTsF6ejItLQQSaHp5xL17C0076', 'HSID': 'AWnr_2tg5_Y53jkmh', '__Secure-1PAPISID': 'WJpxO0qol6873PJf/ASNrXbdWDRKj0qE8G', 'APISID': 'O_lHLn3Zva6IlT2h/AOpas3rQKDM2v9xAj', 'NID': '523=cmIa_aCITzlVRL1ClITQTimijN9DlbYkKLTD3azCLk6hpAlOjlIQ17d02-NyBBsXmTnKfb0RcyOEiAeCoi1APFYNYHRNTYnqRQz4DN11lDQxxHpkC5XeCMi6ZBZaKHU7acuJASUV1wDVQEL--Bia0Uonv6EBP1O-bQr3D8Zp6ETRbhVeKPfpHwTfDqkOyeptJLkhJ4mNtpoMgBMM09RqFJ2VTPIJOp_YsmQR3PDs2UatusZiWObdNCFwAKQFjbuE84AX-wCWxeSCXcNzHd6MjPmChrKFtkQodavZ5xjBD-alS2fB3FzCunBz5ydp4HykPz02DD69y0TcMo5Md-n2fqqNw0DmhbT__e4wP9KQsHJv_RrBDwd1ShA0hoL6Z1qd2I8weKGLwscQW-F8v_VA5rSJwNttKNoLk40Z5UmswNpQjukk56uBmw4UnPhc_YZdCPNQ1QlSbL5FpEUo30E3vqXeTXTU4_4z3nrW2VdIj4QnBwj4N_zBZ1jYIK_ai8s1Eb35h-5SWkXArIcS7G4TjR7XjpX5koteE-tU6jVpPQ7sCEl7f4cmLhuRsjjgNrAwqR1rPYd9js2tTomW4g-U83W7AK63fAhNkPMhD8OekNLKI-G6DbjmUmaZFNQKwU1UF7io-gkW6CUxGlPTnE_f3-qm4Y-4-ZVSU7TZ', 'SSID': 'A7l7czY1LzRrexjBI', '__Secure-1PSID': 'g.a000wAgf5xBEtPItfG2JFEvF9szskOVLMUfcQ9Fz-uD3NKSYQN6JQ72UJ2KiGY23A_d7ZSdV-wACgYKAVkSARISFQHGX2MiWej5KC_nSwCCT5-OQ0ZGARoVAUF8yKrkv-qJ1xigeDKxcLap5GAW0076'}

        r = self.session.get(url, cookies=session_cookies)
        # 先取前七天作为基础数据，然后再一天一天地取

        html = r.text.encode('utf-8')

        soup = BeautifulSoup(html, 'html.parser')
        results = []

        history_divs = soup.find_all("div", class_="history_message")

        for div in history_divs:
            timestamp = div.get("data-timestamp", "")
            items = div.find_all("li", class_="result")

            for item in items:
                title_tag = item.find("a", class_="result_title_link")
                source_tag = item.find("div", class_="result_source")
                snippet_tag = item.find("span", class_="snippet")

                if title_tag and snippet_tag and source_tag:
                    title = title_tag.get_text(strip=True).replace('\xa0', '')
                    snippet = snippet_tag.get_text(strip=True).replace('\xa0', '')
                    source = source_tag.get_text(strip=True).replace('\xa0', '')

                    result = {
                        "timestamp": timestamp,
                        "title": title,
                        "link": title_tag.get("href"),
                        "snippet": snippet,
                        "source": source
                    }
                    results.append(result)

        # 打印结果
        for r in results:
            print(r)
        print(len(results))
        from datetime import datetime
        print(datetime.fromtimestamp(1743598729))


if __name__ == '__main__':
    test = GoogleAlertManager()
    test.analysis_history('乒乓球')
