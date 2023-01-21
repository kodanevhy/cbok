from oslo_log import log as logging

from cbok import config
from cbok.objects import base
from cbok.objects import fields

LOG = logging.getLogger(__name__)
CONF = config.CONF


@base.CBoKObjectRegistry.register
class Catkin(base.CBoKObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'count': fields.StringField(),
        'source': fields.StringField(),
        'relationship': fields.StringField(),
        'ready': fields.BooleanField(nullable=True),
        'uuid': fields.UUIDField(),
        }

    def obj_load_attr(self, attrname):
        pass

    def save(self, context):
        pass
