from abc import ABC

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


class CBoKObject(ovoo_base.VersionedObject, ABC):

    def obj_load_attr(self, attrname):
        pass

    # NOTE(Koda): Do not use context now, set it None.
    def save(self, context=None):
        pass

    OBJ_SERIAL_NAMESPACE = 'cbok_object'
    OBJ_PROJECT_NAMESPACE = 'cbok'


class ObjectListBase(ovoo_base.ObjectListBase):
    pass


obj_make_list = ovoo_base.obj_make_list
