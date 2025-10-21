from cbok.apps.bbx.chrome_plugins.auto_login.server import manager

class ChromePlugins():
    def __init__(self):
        pass

    def auto_login_sync(self):
        manager.run()


def startup():
    ChromePlugins().auto_login_sync()
