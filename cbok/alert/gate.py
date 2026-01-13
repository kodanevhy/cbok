import logging

from cbok.alert import models
from cbok import utils as cbok_utils

LOG = logging.getLogger(__name__)


@cbok_utils.periodic_task(interval=30)
def derive_and_notify():
    # TODO: find that topic created but not in initializing
    # need to reopen, maybe need to add a new topic status
    topic, _ = models.Topic.objects.get_or_create(
        name="乒乓球",
        defaults={"status": "created"},
    )
    if not topic.status == "initialized":
        LOG.info(f"Topic {topic.name} hadn't been initialized")
        return

    if topic.in_progress:
        pass
