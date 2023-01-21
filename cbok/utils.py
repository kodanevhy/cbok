"""Utilities and helper functions."""

import contextlib
import datetime
import functools
import hashlib
import inspect
import os
import random
import re
import shutil
import tempfile

import eventlet
from oslo_concurrency import lockutils
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils.secretutils import md5
from oslo_utils import strutils
from oslo_utils import timeutils

import cbok.conf
from cbok import exception

profiler = importutils.try_import('osprofiler.profiler')


CONF = cbok.conf.CONF

LOG = logging.getLogger(__name__)

synchronized = lockutils.synchronized_with_prefix('cbok-')

_FILE_CACHE = {}


if hasattr(inspect, 'getfullargspec'):
    getargspec = inspect.getfullargspec
else:
    getargspec = inspect.getargspec
