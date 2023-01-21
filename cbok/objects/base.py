from oslo_versionedobjects import base as ovoo_base


class CBoKObjectRegistry(ovoo_base.VersionedObjectRegistry):
    pass


class CBoKObject(ovoo_base.VersionedObject):

    def obj_load_attr(self, attrname):
        pass

    def save(self, context):
        pass

    OBJ_SERIAL_NAMESPACE = 'cbok_object'
    OBJ_PROJECT_NAMESPACE = 'cbok'


class ObjectListBase(ovoo_base.ObjectListBase):
    pass


obj_make_list = ovoo_base.obj_make_list
