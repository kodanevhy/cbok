import re

from oslo_versionedobjects import base as ovoo_base

from cbok.objects import fields as obj_fields


CBoKObjectDictCompat = ovoo_base.VersionedObjectDictCompat


class CBoKObjectRegistry(ovoo_base.VersionedObjectRegistry):
    pass


class CBoKPersistentObject(object):
    """Mixin class for Persistent objects.

    This adds the fields that we use in common for most persistent objects.
    """
    fields = {
        'created_at': obj_fields.DateTimeField(nullable=True),
        'updated_at': obj_fields.DateTimeField(nullable=True),
        'deleted_at': obj_fields.DateTimeField(nullable=True),
        'deleted': obj_fields.BooleanField(default=False),
        }


class CBoKObject(ovoo_base.VersionedObject):

    def obj_load_attr(self, attrname):
        pass

    def save(self):
        pass

    OBJ_SERIAL_NAMESPACE = 'cbok_object'
    OBJ_PROJECT_NAMESPACE = 'cbok'


class ObjectListBase(ovoo_base.ObjectListBase):
    pass


obj_make_list = ovoo_base.obj_make_list


class Branch:
    """Unify object parent.

    Here wants to Unify object creation because there are 3 places to
    verify when object fields changing, which are OBJECT, DB MODEL and
    API VIEWS.
    """
    branch_type = None

    def __init__(self, obj_dict):
        """Parent for object which haven't been filled in."""
        self.obj_dict = obj_dict

    def construct(self):
        raise NotImplementedError('You must implement construct.')


class DBModel(Branch):

    branch_type = 'model'

    @staticmethod
    def get_type(o_type):
        if 'Integer' in o_type:
            return 'Integer'
        elif 'Float' in o_type:
            return 'Float'
        elif 'Bool' in o_type:
            return 'Boolean'
        else:
            return 'String'

    def get_null(self, o_type):
        if 'nullable=True' in o_type:
            return 'nullable=True'
        else:
            return 'nullable=False'

    def get_length(self, o_type):
        if 'UUID' in o_type:
            return '36'
        else:
            return '255'

    def construct(self):
        # class Meh(BASE, CBoKBase, models.SoftDeleteMixin):
        #     """Represents a meh."""
        #
        #     __tablename__ = 'meh'
        #     __table_args__ = (
        #         Index('meh_uuid_idx', 'uuid', unique=True),
        #     )
        #
        #     id = Column(Integer, primary_key=True)
        #     uuid = Column(String(length=36), nullable=False)
        #     transaction = Column(String(length=255), nullable=True)
        #     counterparty = Column(String(length=255), nullable=True)
        #     commodity = Column(String(length=255), nullable=True)
        #     trade_type = Column(String(length=255), nullable=True)
        #     payment_method = Column(String(length=255), nullable=True)
        #     trade_state = Column(String(length=255), nullable=True)
        #     trade_date = Column(String(length=255), nullable=True)
        #     relationship = Column(String(length=36), nullable=True)
        #     amount = Column(Float, nullable=False, default=0)
        #     description = Column(String(length=255), nullable=True)
        #     worthy = Column(Float, nullable=True)
        #     ready = Column(Boolean, nullable=True)
        yuju = []
        for field, field_type in self.obj_dict:
            if field == 'id':
                continue
            model_type = self.get_type(str(field_type))
            nullable = self.get_null(str(field_type))
            length = self.get_length(str(field_type))
            constructed = 'Column(' + model_type + '(length=' + length + ')' + ', ' + nullable + ')'
            yuju.append(constructed)


class APIView(Branch):

    branch_type = 'view'

    def construct(self):
        for field in self.obj_dict:
            pass
