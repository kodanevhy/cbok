from cbok.apps.alert import manager
from cbok import utils as cbok_utils


@cbok_utils.periodic_task(interval=600)
def derive_and_notify():
    alert_manager = manager.AlertManager()
    alert_manager.crawl()
    alert_manager.derive()
    alert_manager.notify()
