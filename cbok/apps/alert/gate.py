import logging

from cbok.apps.alert import manager
from cbok.apps.alert import models
from cbok import utils as cbok_utils

LOG = logging.getLogger(__name__)


@cbok_utils.periodic_task(interval=30)
def derive_and_notify():
    alert_manager = manager.AlertManager()
    topic, _ = models.Topic.objects.get_or_create(
        name="乒乓球",
        initialized=False,
    )
    if not topic.initialized:
        LOG.info(f"Topic {topic.name} haven't been initialized")
        return

    alert_manager.backfill(recent=1)
    import pdb; pdb.set_trace()
    alert_manager.derive(topic)

    if topic.has_evolving_answer:
        # parse AnswerChunk and notify
        pass
