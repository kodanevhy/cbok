"""
SQLAlchemy models for cbok data.
"""

from oslo_config import cfg
from oslo_db.sqlalchemy import models
from sqlalchemy import (Column, Index, Integer, String)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import orm
from sqlalchemy import Boolean, Text, Float

CONF = cfg.CONF
BASE = declarative_base()


def MediumText():
    return Text().with_variant(MEDIUMTEXT(), 'mysql')


class CBoKBase(models.TimestampMixin,
               models.ModelBase):
    metadata = None

    def __copy__(self):
        """Implement a safe copy.copy().

        SQLAlchemy-mapped objects travel with an object
        called an InstanceState, which is pegged to that object
        specifically and tracks everything about that object.  It's
        critical within all attribute operations, including gets
        and deferred loading.   This object definitely cannot be
        shared among two instances, and must be handled.

        The copy routine here makes use of session.merge() which
        already essentially implements a "copy" style of operation,
        which produces a new instance with a new InstanceState and copies
        all the data along mapped attributes without using any SQL.

        The mode we are using here has the caveat that the given object
        must be "clean", e.g. that it has no database-loaded state
        that has been updated and not flushed.   This is a good thing,
        as creating a copy of an object including non-flushed, pending
        database state is probably not a good idea; neither represents
        what the actual row looks like, and only one should be flushed.

        """
        session = orm.Session()

        copy = session.merge(self, load=False)
        session.expunge(copy)
        return copy


class Meh(BASE, CBoKBase, models.SoftDeleteMixin):
    """Represents a meh."""

    __tablename__ = 'meh'
    __table_args__ = (
        Index('meh_uuid_idx', 'uuid', unique=True),
    )

    id = Column(Integer, primary_key=True)
    uuid = Column(String(length=36), nullable=False)
    transaction = Column(String(length=255), nullable=True)
    counterparty = Column(String(length=255), nullable=True)
    commodity = Column(String(length=255), nullable=True)
    trade_type = Column(String(length=255), nullable=True)
    payment_method = Column(String(length=255), nullable=True)
    trade_state = Column(String(length=255), nullable=True)
    trade_date = Column(String(length=255), nullable=True)
    relationship = Column(String(length=36), nullable=True)
    amount = Column(Float, nullable=False, default=0)
    description = Column(String(length=255), nullable=False)
    worthy = Column(Float, nullable=True)
    ready = Column(Boolean, nullable=True)
    caper = Column(String(length=36), nullable=True)


class Caper(BASE, CBoKBase, models.SoftDeleteMixin):
    """Represents a caper."""

    __tablename__ = 'caper'
    __table_args__ = (
        Index('caper_uuid_idx', 'uuid', unique=True),
    )

    id = Column(Integer, primary_key=True)
    uuid = Column(String(length=36), nullable=False)
    name = Column(String(length=255), nullable=False)
    description = Column(String(length=255), nullable=True)
    progressing = Column(Boolean, nullable=False, default=False)
