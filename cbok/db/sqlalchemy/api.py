"""Implementation of SQLAlchemy backend."""

import collections
import copy
import datetime
import functools
import inspect
import sys

from oslo_db import api as oslo_db_api
from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import update_match
from oslo_db.sqlalchemy import utils as sqlalchemyutils
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import sqlalchemy as sa
from sqlalchemy import and_
from sqlalchemy import Boolean
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import or_
from sqlalchemy.orm import aliased
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import noload
from sqlalchemy.orm import subqueryload
from sqlalchemy.orm import undefer
from sqlalchemy.schema import Table
from sqlalchemy import sql
from sqlalchemy.sql.expression import asc
from sqlalchemy.sql.expression import cast
from sqlalchemy.sql.expression import desc
from sqlalchemy.sql.expression import UpdateBase
from sqlalchemy.sql import false
from sqlalchemy.sql import func
from sqlalchemy.sql import null
from sqlalchemy.sql import true

import cbok.conf
from cbok.db.sqlalchemy import models
from cbok import exception

profiler_sqlalchemy = importutils.try_import('osprofiler.sqlalchemy')

CONF = cbok.conf.CONF


LOG = logging.getLogger(__name__)

bookkeeping_context_manager = enginefacade.transaction_context()


def _get_db_conf(conf_group, connection=None):
    kw = dict(conf_group.items())
    if connection is not None:
        kw['connection'] = connection
    return kw


def configure(conf):
    bookkeeping_context_manager.configure(**_get_db_conf(conf.bookkeeping_database))

    if profiler_sqlalchemy and CONF.profiler.enabled \
            and CONF.profiler.trace_sqlalchemy:

        bookkeeping_context_manager.append_on_engine_create(
            lambda eng: profiler_sqlalchemy.add_tracing(sa, eng, "db"))


def _context_manager_from_context(context):
    if context:
        try:
            return context.db_connection
        except AttributeError:
            pass


def get_context_manager(context):
    """Get a database context manager object.

    :param context: The request context that can contain a context manager
    """
    return _context_manager_from_context(context) or bookkeeping_context_manager


def get_engine(use_slave=False, context=None):
    """Get a database engine object.

    :param use_slave: Whether to use the slave connection
    :param context: The request context that can contain a context manager
    """
    ctxt_mgr = get_context_manager(context)
    if use_slave:
        return ctxt_mgr.reader.get_engine()
    return ctxt_mgr.writer.get_engine()
