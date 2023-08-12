import functools
import json

from cbok.db import base
from cbok.objects import meh as meh_obj
from cbok.bookkeeping.report import Email
from cbok.bookkeeping.report import Message


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


class API(base.Base):
    def __init__(self, **kwargs):
        super(API, self).__init__()

    @staticmethod
    def get(meh_uuid):
        return meh_obj.Meh.get_by_uuid(meh_uuid)

    @staticmethod
    @wrap_report
    def create(create_kwargs):
        batched = []
        for meh_meta in create_kwargs:
            r_meh = meh_obj.Meh.get_by_uuid(meh_meta.get('relationship', ''))
            meh_meta['relationship'] = r_meh.uuid
            meh = meh_obj.Meh(meh_meta)
            persistence = meh.create()
            batched.append({'meh': persistence})

        return batched

    @staticmethod
    def update(meh, updates):
        meh.update(updates)
        meh.save()
        return meh
