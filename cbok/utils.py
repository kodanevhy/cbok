"""Utilities and helper functions."""

import inspect
import time

from oslo_concurrency import lockutils
from oslo_log import log as logging
from oslo_utils import timeutils

import cbok.conf
from cbok import exception

CONF = cbok.conf.CONF

LOG = logging.getLogger(__name__)

synchronized = lockutils.synchronized_with_prefix('cbok-')

_FILE_CACHE = {}


if hasattr(inspect, 'getfullargspec'):
    getargspec = inspect.getfullargspec
else:
    getargspec = inspect.getargspec


def isotime(at=None):
    """Current time as ISO string,
    as timeutils.isotime() is deprecated

    :returns: Current time in ISO format
    """
    if not at:
        at = timeutils.utcnow()
    date_string = at.strftime("%Y-%m-%dT%H:%M:%S")
    tz = at.tzinfo.tzname(None) if at.tzinfo else 'UTC'
    date_string += ('Z' if tz in ['UTC', 'UTC+00:00'] else tz)
    return date_string


def strtime(at):
    return time.strptime(at, '%Y-%m-%d %H:%M:%S')
