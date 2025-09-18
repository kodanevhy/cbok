import logging
import time

import undetected_chromedriver as uc
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from alert.login import base

LOG = logging.getLogger(__name__)


class ElementAction(object):

    @property
    def click(self):
        return 'click'

    @property
    def enter(self):
        return 'enter'

    def get(self, send_key):
        return self.enter if send_key else self.click


class GoogleLogin(base.BaseLogin):
    URL = 'https://accounts.google.com/ServiceLogin'

    def __init__(self, username, password):
        super().__init__(username, password)
        self.email = username
        self.password = password
        self.driver = uc.Chrome(headless=False)
        self.elem_action = ElementAction()

    def quit(self):
        self.driver.quit()

    def retrieve_cookies(self):
        self.login()
        LOG.info(f'Login {self.target} successfully')

        # We'd better to sleep here, for entirely retrieving cookies
        time.sleep(20)

        cookies = self.driver.get_cookies()
        self.quit()
        return cookies

    def wait(self, by, value):
        try:
            element = WebDriverWait(self.driver, timeout=20, poll_frequency=0.5).until(
                ec.visibility_of_element_located((by, value))
            )
        except TimeoutException as e:
            LOG.exception(e)
            return None
        return element

    def forward(self, element, send_key=None):
        action = self.elem_action.get(send_key)

        if action == self.elem_action.enter:
            element.send_keys(send_key)
            element.send_keys(Keys.ENTER)
        elif action == self.elem_action.click:
            element.click()

    def login(self):

        self.driver.get(self.URL)

        identifier = self.wait(By.NAME, 'identifier')
        if identifier:
            self.forward(identifier, send_key=self.email)

        password = self.wait(By.XPATH, '//input[@type="password" and @name="Passwd"]')
        if password:
            self.forward(password, send_key=self.password)
            return

        try_o = self.wait(By.XPATH, '//button[.//span[text()="试试其他方式"]]')
        self.forward(try_o)
        password = self.wait(By.XPATH, '//input[@type="password" and @name="Passwd"]')
        self.forward(password, send_key=self.password)
