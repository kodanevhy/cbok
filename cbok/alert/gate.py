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
