"""Defines interface for DB access.

Functions in this module are imported into the cbok.db namespace. Call these
functions from cbok.db namespace, not the cbok.db.api namespace.

All functions in this module return objects that implement a dictionary-like
interface. Currently, many of these objects are sqlalchemy objects that
implement a dictionary interface. However, a future goal is to have all of
these objects be simple dictionaries.

"""

from oslo_log import log as logging

import cbok.conf
from cbok.db import constants
from cbok.db.sqlalchemy import api as sa_api


CONF = cbok.conf.CONF
LOG = logging.getLogger(__name__)
# NOTE(kodanevhy): These constants are re-defined in this module to preserve
# existing references to them.
MAX_INT = constants.MAX_INT
SQL_SP_FLOAT_MAX = constants.SQL_SP_FLOAT_MAX

IMPL = sa_api


def meh_get(meh_id):
    """Get a meh or raise if it does not exist."""
    return IMPL.meh_get(meh_id)
