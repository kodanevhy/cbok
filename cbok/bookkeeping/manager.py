from oslo_log import log as logging
from oslo_utils import uuidutils

from cbok import config
from cbok import manager
from cbok.objects import meh as meh_obj

LOG = logging.getLogger(__name__)
CONF = config.CONF


class MehManager(manager.Manager):
    """Manages the meh from creation to destruction."""
    def __init__(self):
        super(MehManager, self).__init__()

    @staticmethod
    def get_meh(meh_id):
        return meh_obj.Meh.get_by_uuid(meh_id)

    def create_meh(self, transaction=None, counterparty=None, commodity=None,
                   trade_type=None, payment_method=None, trade_state=None,
                   trade_date=None, relationship=None, amount=None,
                   description=None, worthy=0, ready=False):
        meh_uuid = uuidutils.generate_uuid()
        # r_meh = meh_obj.Meh.get_by_uuid(relationship)
        meh = meh_obj.Meh()
        meh.uuid = meh_uuid
        meh.transaction = transaction
        meh.counterparty = counterparty
        meh.commodity = commodity
        meh.trade_type = trade_type
        meh.payment_method = payment_method
        meh.trade_state = trade_state
        meh.trade_date = trade_date
        # meh.relationship = r_meh.uuid
        meh.amount = amount
        meh.description = '1'
        meh.worthy = '1'
        meh.ready = '1'
        meh.create()
        return meh
