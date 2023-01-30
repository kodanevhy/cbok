"""Defines interface for DB access.

Functions in this module are imported into the cbok.db namespace. Call these
functions from cbok.db namespace, not the cbok.db.api namespace.

All functions in this module return objects that implement a dictionary-like
interface. Currently, many of these objects are sqlalchemy objects that
implement a dictionary interface. However, a future goal is to have all of
these objects be simple dictionaries.

"""

from oslo_db import concurrency
from oslo_log import log as logging

import cbok.conf
from cbok.db import constants


CONF = cbok.conf.CONF
# NOTE(kodanevhy): These constants are re-defined in this module to preserve
# existing references to them.
MAX_INT = constants.MAX_INT
SQL_SP_FLOAT_MAX = constants.SQL_SP_FLOAT_MAX

_BACKEND_MAPPING = {'sqlalchemy': 'cbok.db.sqlalchemy.api'}


IMPL = concurrency.TpoolDbapiWrapper(CONF, backend_mapping=_BACKEND_MAPPING)

LOG = logging.getLogger(__name__)
