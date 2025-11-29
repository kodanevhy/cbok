import ast
import logging
import re
import time
import urllib.parse

from bs4 import BeautifulSoup

from cbok.apps.alert import common
from cbok.apps.alert.login import google
from cbok.apps.alert.manager import base

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
        session_cookies = {'__Secure-3PSIDCC': 'AKEyXzVs9E_1kQVHXrui3X0M0A0LuDg7OAEMfld5o_0McaOMDPFhKuYlITgBYO909d9bQQRd4g', '__Secure-1PSIDCC': 'AKEyXzVRUueu91YOJqmF1nLmsM6anFEVLDK6xXj-Djav3xE_xGVCENESoLqQBdIZryCPhW1x5g', 'SIDCC': 'AKEyXzXe4nD7mkMORwAbtbHZM1wzjUyl7JYwdZ42buCtTeX6beTSXYjUOh3qA0rH-ItTCmN36A', 'APISID': '-NzkO6mo-k2Ty5ii/ABjvRswadFDoG0gM3', 'SSID': 'ACq9kWmdgJa-bYS8-', 'NID': '526=VBw_VXjxZ0ar8GWr0yHpb0xZNmpxbDs70Aa0_dHtkWww-3inXkmcGNhvOcZ6OwvCi1gzaucNiqdJPlKMxyRylcnFpo0ywoKwHLHEwyD_13mmJXUkHhAZHewFb4Z5C1TTaEmdkcXIQyE8c7uSm02YlFerVzegye61CwPx_zgsl9rC4UXuvz6YcFG5o1WfKiM3G_xEc9ZP7UIUdXJ3paOytdCb4i4tZc8oDUtYKiX6VOxCznjaLUmzY-anIZy9C2SuEkZPA0ekAobxL4YxRff6dDCFag8zRtfotXu5b2ftE8o3-rasHFUv4xKCbgGqggRy0Dx2VGNu7nqPaYw4RvATJORftGOZzBi66iFttCygZfFoBUzIp68MFCBrsX8p8Qk9AMNg89E2RinMdf6EhIz9dC4G5z9V8oyZ-zS7PRX3QnG6w0R9bSEmyTb_8nw7m-1YLEmkTAl5MjSbok5woE2J3ZD3N8UIqytbx3hMxOh32QxyQ5XEwfcWlCjPa9B6ec2e9JGjwV5gBm4zW47O6GhTmpe7P-mF2sL85AEyfnDc-Ba2k0WOdnA8zmqE5RK5qt6YwSrfIyNu0csVNMVF40yBC0eG3KGgCjz62wMSEZc13h7VLLRZ2zOgVl90sxRMyn5nZXM7DkWUlj1O4QuAFyCoX5sUl28S7oFeL11rYQkOYw', '__Secure-3PSID': 'g.a0004Agf58wkvNaNEZTuk8uWEBiOeqd0CVngAa-MwCRjB2YzBkoZhqGN_WD5ea07Y54TsC0huwACgYKAegSARISFQHGX2MibRO_Z6MQPc4Qt57FGELeaxoVAUF8yKrj3CWzpAk43tWusvaQ7M3c0076', '__Secure-1PSID': 'g.a0004Agf58wkvNaNEZTuk8uWEBiOeqd0CVngAa-MwCRjB2YzBkoZ2fq9j3QopmuuvBn4TvUlDgACgYKATISARISFQHGX2Mi6SCRskWhF88tlYdqxipYqRoVAUF8yKqTqRGdNR4ZCBTV_3WZj6th0076', 'OTZ': '8368745_24_24__24_', '__Secure-3PAPISID': 'PBw-cY9-eVCCT8Wv/AtUQ5IMKJu0JUCoOD', '__Secure-1PAPISID': 'PBw-cY9-eVCCT8Wv/AtUQ5IMKJu0JUCoOD', 'SID': 'g.a0004Agf58wkvNaNEZTuk8uWEBiOeqd0CVngAa-MwCRjB2YzBkoZwdf22q3d8pc_EkpZDLv_swACgYKAWgSARISFQHGX2MiGT17UY5_h9vrwf1ymNKlmRoVAUF8yKqYKSkbqAJ9zdwhVer_mh5C0076', 'SAPISID': 'PBw-cY9-eVCCT8Wv/AtUQ5IMKJu0JUCoOD', 'HSID': 'Av1XRhLElgTnv_vxP'}

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


    def analysis_history(self, name, date=7):
        now = int(time.time())
        d = 86400 * date
        # That mean the past `date` days by default 
        params = f'[null,null,{now},{d}]'
        indexed, session_cookies = self.analysis_index()
        sid = indexed[name]
        url = f'{self.HISTORY}?params={urllib.parse.quote(params)}&s={sid}'
        
        r = self.session.get(url, cookies=session_cookies)

        html = r.text.encode('utf-8')

        import pdb; pdb.set_trace()
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
                url = title_elem.get('href', '')
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
                    'url': url,
                    'keywords': keywords
                })
        
        return results


if __name__ == '__main__':
    test = GoogleAlertManager()
    result = test.analysis_history('王楚钦')
    print(result)
    print(len(result))
