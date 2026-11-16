import logging

from cbok.alert import models
from cbok import utils as cbok_utils

LOG = logging.getLogger(__name__)


@cbok_utils.periodic_task(interval=3600)
def derive_and_notify():
    # TODO: find that topic created but not in initializing
    # need to reopen, maybe need to add a new topic status
    topic = models.Topic.objects.filter(name="乒乓球").first()
    if topic and topic.status != "initialized":
        LOG.info(f"Topic {topic.name} hadn't been initialized")
        return

    if topic and topic.in_progress:
        pass


@cbok_utils.periodic_task(interval=60)
def periodic_monitor():
    """Run registered checks only when explicitly enabled in settings."""
    from django.conf import settings
    if not getattr(settings, 'ALERT_MONITOR_ENABLED', False):
        return
    from cbok.alert.monitoring.service import run_due_checks, deliver_pending
    run_due_checks()
    deliver_pending()
