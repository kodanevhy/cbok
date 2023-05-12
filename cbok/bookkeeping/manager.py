import functools
import json

from oslo_log import log as logging
from oslo_utils import uuidutils

from cbok import config
from cbok import manager
from cbok.bookkeeping.report import Email
from cbok.bookkeeping.report import Message
from cbok.objects import meh as meh_obj

LOG = logging.getLogger(__name__)
CONF = config.CONF


def wrap_report(function):
    @functools.wraps(function)
    def wrapped(self, *args, **kwargs):
        batched_meh = function(self, *args, **kwargs)
        reporter = Email(CONF.email.receiver)
        message = Message(subject='BILL FLOW', text=json.dumps(batched_meh),
                          from_to=reporter.from_to)
        reporter.send(message)
        return batched_meh
    return wrapped


class MehManager(manager.Manager):
    """Manages the meh from creation to destruction."""
    def __init__(self):
        super(MehManager, self).__init__()

    @staticmethod
    def get_meh(meh_id):
        return meh_obj.Meh.get_by_uuid(meh_id)

    @staticmethod
    @wrap_report
    def create_meh(create_kwargs):
        batched = []
        for meh_meta in create_kwargs:
            meh_uuid = uuidutils.generate_uuid()
            meh = meh_obj.Meh()
            meh.uuid = meh_uuid
            meh.transaction = meh_meta['transaction']
            meh.counterparty = meh_meta['counterparty']
            meh.commodity = meh_meta['commodity']
            meh.trade_type = meh_meta['trade_type']
            meh.payment_method = meh_meta['payment_method']
            meh.trade_state = meh_meta['trade_state']
            meh.trade_date = meh_meta['trade_date']
            r_meh = meh_obj.Meh.get_by_uuid(meh_meta.get('relationship', ''))
            if r_meh:
                meh.relationship = r_meh.uuid
            meh.amount = meh_meta['amount']
            meh.description = meh_meta['description']
            meh.worthy = meh_meta['worthy']
            meh.ready = meh_meta.get('ready', '')
            meh.create()
            batched.append({'meh': meh_meta})

        return batched
