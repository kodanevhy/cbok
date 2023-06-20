import functools
import json

from oslo_log import log as logging

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
        # TODO(koda): Fix the receiver now, but need to dynamic get receiver.
        reporter = Email('1923001710@qq.com')
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
            r_meh = meh_obj.Meh.get_by_uuid(meh_meta.get('relationship', ''))
            meh_meta['relationship'] = r_meh.uuid
            meh = meh_obj.Meh()
            persistence = meh.create(meh_meta)
            batched.append({'meh': persistence})

        return batched
