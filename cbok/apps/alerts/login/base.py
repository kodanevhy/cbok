import tldextract

class BaseLogin(object):
    URL = 'https://www.baselogin.com'

    def __init__(self, username, password):
        self.username = username
        self.password = password

    @property
    def target(self):
        return tldextract.extract(self.URL).domain

    def login(self):
        pass

    def retrieve_cookies(self):
        self.login()
