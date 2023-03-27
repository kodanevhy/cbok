"""Implementation of SQLAlchemy backend."""

from sqlalchemy.engine import create_engine
from sqlalchemy.orm import sessionmaker

from oslo_db import exception as db_exc
from oslo_log import log as logging

import cbok.conf
from cbok.db.sqlalchemy import models
from cbok import exception

CONF = cbok.conf.CONF


LOG = logging.getLogger(__name__)


def get_engine():
    """Get a database engine object.
    """
    engine = create_engine(CONF.db.connection, echo=False)
    return engine


def meh_get(meh_id):
    try:
        session = sessionmaker(bind=get_engine())
        meh = session().query(models.Meh).filter_by(uuid=meh_id).first()
        if not meh:
            raise exception.MehNotFound(meh_id=meh_id)
        return meh
    except db_exc.DBError:
        LOG.warning("Invalid meh id %s in request", meh_id)
        raise exception.InvalidID(id=meh_id)


def meh_get_nearly():
    session = sessionmaker(bind=get_engine())
    meh = session().query(models.Meh).order_by('trade_date').first()
    if not meh:
        LOG.warning('None of any meh found.')
        meh = None
    return meh


def meh_create(meh):
    session = sessionmaker(bind=get_engine())
    db_meh = models.Meh()
    db_meh.update(meh)
    db_meh.save(session)
