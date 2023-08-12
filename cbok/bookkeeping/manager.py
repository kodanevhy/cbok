from oslo_log import log as logging

from cbok import config
from cbok import manager

LOG = logging.getLogger(__name__)
CONF = config.CONF


class MehManager(manager.Manager):
    """Manages the meh from creation to destruction."""
    def __init__(self):
        super(MehManager, self).__init__()
