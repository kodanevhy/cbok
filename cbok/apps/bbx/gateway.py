from cbok.apps.bbx.chrome_plugins.auto_login.server import manager
from cbok import utils as cbok_utils

class ChromePlugins():
    def __init__(self):
        pass

    def auto_login_sync(self):
        manager.run()


@cbok_utils.periodic_task(interval=3600)
def sync_auto_login():
    ChromePlugins().auto_login_sync()
