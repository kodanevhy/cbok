from abc import ABC

from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_utils import uuidutils

from cbok import config
from cbok import exception
from cbok.db import api as db_api
from cbok.objects import base
from cbok.objects import fields

LOG = logging.getLogger(__name__)
CONF = config.CONF


@base.CBoKObjectRegistry.register
class Caper(base.CBoKPersistentObject, base.CBoKObject,
            base.CBoKObjectDictCompat, ABC):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'uuid': fields.UUIDField(),
        'name': fields.StringField(),
        'description': fields.StringField(nullable=True),
        'meh': fields.ListOfObjectsField('Meh', nullable=True),
        'progressing': fields.BooleanField(nullable=False, default=False)
        }

    def __init__(self, *args, **kwargs):
        super(Caper, self).__init__(args, **kwargs)

    def obj_load_attr(self, attrname):
        pass

    @staticmethod
    def _caper_create(values):
        try:
            db_caper = db_api.caper_create(values)
        except db_exc.DBDuplicateEntry as e:
            if 'uuid' in e.columns:
                raise exception.CaperUUIDExists(caper_uuid=values['uuid'])
            raise exception.CaperExists(id=values['id'])
        except Exception as e:
            raise db_exc.DBError(e)

        return db_caper

    def create(self):
        """Unify object creation.

        Idea is that the creation fixed procedures throughout the CBoK:
        1.Dict for arguments
        2.call next layer: API model
        3.Get the return and return (must)
        """
        caper_uuid = uuidutils.generate_uuid()
        if self.get_by_uuid(caper_uuid):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')

        updates = self.obj_get_changes()
        db_caper = self._caper_create(updates)
        self._from_db_object(db_caper)
        return db_caper

    def _from_db_object(self, db_caper):
        for name, field in self.fields.items():
            value = db_caper[name]
            if isinstance(field, fields.IntegerField):
                value = value if value is not None else 0
            self[name] = value

        self.obj_reset_changes()
        return self

    @classmethod
    def get_by_uuid(cls, uuid):
        if not uuid:
            return None
        db_caper = db_api.caper_get(uuid)
        meh = db_api.meh_get_by_caper(uuid)
        db_caper.update({'meh': meh})
        return cls._from_db_object(cls(), db_caper)


@base.CBoKObjectRegistry.register
class CaperList(base.ObjectListBase, base.CBoKObject, ABC):
    # Version 1.0: Initial Version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Caper'),
    }
