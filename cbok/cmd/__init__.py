import sys

import eventlet

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


is_debug = True if sys.gettrace() else False

if is_debug:
    LOG.warning('In debugging mode, do not monkey_patch original thread.')
    eventlet.monkey_patch(thread=False)
else:
    eventlet.monkey_patch()
