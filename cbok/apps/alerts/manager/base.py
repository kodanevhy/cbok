import requests

class BaseAlertManager(object):
    INDEX = str()

    def __init__(self):
        self.session = requests.Session()
        self.login_manager = None

    def login(self, username, password):
        pass
