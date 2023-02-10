from oslo_log import log as logging

from cbok import config
from cbok import manager
from cbok.objects import meh as meh_obj
from oslo_utils import uuidutils

LOG = logging.getLogger(__name__)
CONF = config.CONF


class MehManager(manager.Manager):
    """Manages the meh from creation to destruction."""
    def __init__(self):
        super(MehManager, self).__init__()

    @staticmethod
    def get_meh(meh_id):
        return meh_obj.Meh.get_by_uuid(meh_id)

    @staticmethod
    def create_meh(meh_type, amount, desc, relationship=None):
        meh_uuid = uuidutils.generate_uuid()
        r_meh = meh_obj.Meh.get_by_uuid(relationship)
        meh = meh_obj.Meh()
        meh.uuid = meh_uuid
        meh.type = meh_type
        meh.amount = amount
        meh.description = desc
        meh.relationship = r_meh.uuid
        meh.save()
        return meh
