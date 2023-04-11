from oslo_db import exception as db_exc
from oslo_log import log as logging

from cbok import config
from cbok import exception
from cbok.db import api as db_api
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
        'transaction': fields.StringField(nullable=True),
        'counterparty': fields.StringField(nullable=True),
        'commodity': fields.StringField(nullable=True),
        # NOTE(koda): Well, type means incoming or expenditure.
        'trade_type': fields.StringField(nullable=True),
        'payment_method': fields.StringField(nullable=True),
        'trade_state': fields.StringField(nullable=True),
        'trade_date': fields.DateTimeField(nullable=True),
        # NOTE(koda): The meh may relate to the others, in a case of that
        # type incoming may cause by an expenditure, so I use relationship
        # field to represent foreign key like.
        'relationship': fields.UUIDField(nullable=True),
        'amount': fields.FloatField(nullable=False),
        'description': fields.StringField(nullable=False),
        # NOTE(koda): Support to save a certain proportion of meh,
        # especially when type is expenditure.
        'worthy': fields.BooleanField(nullable=True),
        'ready': fields.BooleanField(nullable=True)
        }

    def __init__(self, *args, **kwargs):
        super(Meh, self).__init__(args, **kwargs)

    def obj_load_attr(self, attrname):
        pass

    @staticmethod
    def _meh_create(values):
        try:
            db_meh = db_api.meh_create(values)
        except db_exc.DBDuplicateEntry as e:
            if 'uuid' in e.columns:
                raise exception.MehUUIDExists(meh_uuid=values['uuid'])
            raise exception.MehExists(id=values['id'])
        except Exception as e:
            raise db_exc.DBError(e)

        return db_meh

    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')

        updates = self.obj_get_changes()
        db_meh = self._meh_create(updates)
        self._from_db_object(self, db_meh)

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

    @classmethod
    def nearly_one(cls):
        db_meh = db_api.meh_get_nearly()
        return cls._from_db_object(cls(), db_meh)


@base.CBoKObjectRegistry.register
class MehList(base.ObjectListBase, base.CBoKObject):
    # Version 1.0: Initial Version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Meh'),
    }

    # @staticmethod
    # def _db_instance_get_all_by_host(context, host, columns_to_join,
    #                                  use_slave=False):
    #     return db_api.instance_get_all_by_host(context, host,
    #                                        columns_to_join=columns_to_join)
    #
    # def get_by_host(cls, context, host, expected_attrs=None, use_slave=False):
    #     db_inst_list = cls._db_instance_get_all_by_host(
    #         context, host, columns_to_join=_expected_cols(expected_attrs),
    #         use_slave=use_slave)
    #     return _make_instance_list(context, cls(), db_inst_list,
    #                                expected_attrs)
