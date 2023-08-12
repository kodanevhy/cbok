"""Implementation of SQLAlchemy backend."""
import contextlib

from sqlalchemy.engine import create_engine
from sqlalchemy.orm import sessionmaker
from oslo_db import exception as db_exc
from oslo_log import log as logging

import cbok.conf
from cbok.db.sqlalchemy import models
from cbok import exception

CONF = cbok.conf.CONF

LOG = logging.getLogger(__name__)


@contextlib.contextmanager
def session_constructor():
    """Get a database engine object and execute.
    """
    engine = create_engine(CONF.db.connection, echo=False)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.commit()
    session.close()


def meh_get(meh_id):
    try:
        with session_constructor() as session:
            meh = session.query(models.Meh).filter_by(uuid=meh_id).first()
        if not meh:
            raise exception.MehNotFound(meh_id=meh_id)
        return meh
    except db_exc.DBError:
        LOG.warning("Invalid meh id %s in request", meh_id)
        raise exception.InvalidID(id=meh_id)


def meh_get_nearly():
    with session_constructor() as session:
        meh = session.query(models.Meh).order_by('trade_date').first()
    if not meh:
        LOG.warning('None of any meh found.')
        meh = None
    return meh


def meh_create(meh):
    with session_constructor() as session:
        db_meh = models.Meh()
        db_meh.update(meh)
        session.add(db_meh)

    return {key: value for key, value in db_meh}


def meh_update(meh_id, meh):
    with session_constructor() as session:
        pass


def meh_get_by_caper(caper_uuid):
    try:
        with session_constructor() as session:
            meh = session.query(models.Caper).filter_by(caper=caper_uuid)
    except db_exc.DBError:
        LOG.warning("Invalid caper id %s in request", caper_uuid)
        raise exception.InvalidID(id=caper_uuid)

    return {key: value for key, value in meh}


def caper_get(caper_uuid):
    try:
        with session_constructor() as session:
            caper = session.query(models.Caper).filter_by(uuid=caper_uuid).first()
        if not caper:
            raise exception.CaperNotFound(caper_id=caper_uuid)
        return caper
    except db_exc.DBError:
        LOG.warning("Invalid caper id %s in request", caper_uuid)
        raise exception.InvalidID(id=caper_uuid)


def caper_create(caper):
    with session_constructor() as session:
        db_caper = models.Caper()
        db_caper.update(caper)
        session.add(db_caper)

    return {key: value for key, value in db_caper}
