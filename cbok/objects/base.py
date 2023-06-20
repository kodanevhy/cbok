import re

from oslo_versionedobjects import base as ovoo_base

from cbok import utils
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
        self.obj_filled = None

    def construct(self):
        raise NotImplementedError('You must implement construct.')

    @staticmethod
    def match_type(field_type):
        field_type_pattern = "(fields.)(.*)(Field\()(.*)(\))"   # noqa
        matched = re.match(field_type_pattern, str(field_type))
        return matched


class DBModel(Branch):

    branch_type = 'model'

    def construct(self):
        constructed = []
        for field, field_type in self.obj_dict:
            target = {'model_type': str, 'nullable': str, 'primary': str}
            if field == 'id':
                target['model_type'] = 'Integer'
                target['primary'] = 'primary_key=True'

            matched = self.match_type(field_type)
            if matched:
                target['model_type'] = matched.group(2)
                target['nullable'] = matched.group(4)

                if not target['model_type']:
                    raise
                else:
                    length = '36' if field == 'UUID' else '255'
                    target['model_type'] += '(length=' + length + ')'

            for item in target:
                if item:
                    item += ', '

            sentence = field + ' = Column(' \
                               + target['model_type'] \
                               + target['nullable'] \
                               + target['primary'] + ')'
            constructed.append(sentence)


class APIView(Branch):

    branch_type = 'view'

    def construct(self):
        assert self.obj_filled is not None, 'Branch view: ' \
                                            'No filled object provided.'
        constructed = {}
        for field, field_type in self.obj_dict:
            if field == 'id':
                continue
            filled_data = getattr(self.obj_filled, field)
            from cbok.objects import fields
            if isinstance(filled_data, fields.DateTimeField):
                filled_data = utils.isotime(filled_data)
            matched = self.match_type(field_type)

            if filled_data is None:
                if matched.group(2) == 'Bool':
                    filled_data = False
                elif matched.group(2) == 'Float':
                    filled_data = 0.0
                elif matched.group(2) == 'Integer':
                    filled_data = 0
                elif matched.group(2) == 'String':
                    filled_data = ''
            constructed.update({field: filled_data})

        return constructed
