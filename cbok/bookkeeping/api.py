import datetime
import functools
import json

from oslo_utils import uuidutils

from cbok.db import base
from cbok.objects import meh as meh_obj
from cbok.bookkeeping.report import Email
from cbok.bookkeeping.report import Message


def wrap_report(function):
    class _DateEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, datetime.datetime):
                return obj.strftime("%Y-%m-%d %H:%M:%S")
            else:
                return json.JSONEncoder.default(self, obj)

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        batched_meh = function(*args, **kwargs)
        # TODO(koda): Fix the receiver now, but need to dynamic get receiver.
        reporter = Email('1923001710@qq.com')
        message = Message(subject='BILL FLOW',
                          text=json.dumps(batched_meh, cls=_DateEncoder),
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
        meh_uuid = uuidutils.generate_uuid()
        create_kwargs.update({'uuid': meh_uuid})
        create_kwargs.update({'description': create_kwargs['commodity']})
        meh = meh_obj.Meh(**create_kwargs)
        persistence = meh.create()

        return persistence

    @staticmethod
    def update(meh, updates):
        meh.update(updates)
        meh.save()
        return meh
