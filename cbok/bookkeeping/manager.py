from oslo_log import log as logging

from cbok import config

LOG = logging.getLogger(__name__)
CONF = config.CONF


class ConductorManager:
    """Manages the catkin from creation to destruction."""
    def __init__(self):
        pass

    def create_catkin(self):
        pass
