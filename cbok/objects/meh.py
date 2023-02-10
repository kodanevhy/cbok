from oslo_log import log as logging

from cbok import config
from cbok import exception
from cbok.bookkeeping import common
from cbok.db import api as db_api
from cbok.db.sqlalchemy import models
from cbok.objects import base
from cbok.objects import fields

LOG = logging.getLogger(__name__)
CONF = config.CONF


@base.CBoKObjectRegistry.register
class Meh(base.CBoKPersistentObject, base.CBoKObject,
          base.CBoKObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'uuid': fields.UUIDField(),
        # TODO(kodanevhy): Add explanation.
        'type': fields.StringField(),
        # TODO(kodanevhy): Add explanation.
        'relationship': fields.UUIDField(),
        'amount': fields.FloatField(nullable=False),
        'description': fields.StringField(nullable=False),
        # TODO(kodanevhy): Add explanation.
        'worthy': fields.BooleanField(nullable=True),
        'ready': fields.BooleanField(nullable=True)
        }

    def __init__(self, *args, **kwargs):
        super(Meh, self).__init__(args, **kwargs)

    def obj_load_attr(self, attrname):
        pass

    def save(self):
        pass

    @staticmethod
    def _from_db_object(meh, db_meh):
        for name, field in meh.fields.items():
            value = db_meh[name]
            if isinstance(field, fields.IntegerField):
                value = value if value is not None else 0
            meh[name] = value

        meh.obj_reset_changes()
        return meh

    @classmethod
    def get_by_uuid(cls, uuid):
        db_meh = db_api.meh_get(uuid)
        return cls._from_db_object(cls(), db_meh)
