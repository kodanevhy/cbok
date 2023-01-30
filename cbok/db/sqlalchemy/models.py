"""
SQLAlchemy models for cbok data.
"""

from oslo_config import cfg
from oslo_db.sqlalchemy import models
from oslo_utils import timeutils
from sqlalchemy import (Column, Index, Integer, BigInteger, Enum, String,
                        schema, Unicode)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import orm
from sqlalchemy import ForeignKey, DateTime, Boolean, Text, Float


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


class Catkin(BASE, CBoKBase, models.SoftDeleteMixin):
    """Represents an incoming."""

    __tablename__ = 'catkin'
    __table_args__ = (
        schema.UniqueConstraint("host", "topic", "deleted",
                                name="uniq_services0host0topic0deleted"),
        schema.UniqueConstraint("host", "binary", "deleted",
                                name="uniq_services0host0binary0deleted"),
        Index('services_uuid_idx', 'uuid', unique=True),
    )

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), nullable=True)
    host = Column(String(255))
    binary = Column(String(255))
    topic = Column(String(255))
    report_count = Column(Integer, nullable=False, default=0)
    disabled = Column(Boolean, default=False)
    disabled_reason = Column(String(255))
    last_seen_up = Column(DateTime, nullable=True)
    forced_down = Column(Boolean, default=False)
    version = Column(Integer, default=0)

    instance = orm.relationship(
        "Instance",
        backref='services',
        primaryjoin='and_(Service.host == Instance.host,'
                    'Service.binary == "nova-compute",'
                    'Instance.deleted == 0)',
        foreign_keys=host,
    )


class Meh(BASE, CBoKBase, models.SoftDeleteMixin):
    """Represents an expenditure."""

    __tablename__ = 'meh'
    __table_args__ = (
        schema.UniqueConstraint("host", "topic", "deleted",
                                name="uniq_services0host0topic0deleted"),
        schema.UniqueConstraint("host", "binary", "deleted",
                                name="uniq_services0host0binary0deleted"),
        Index('services_uuid_idx', 'uuid', unique=True),
    )

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), nullable=True)
    host = Column(String(255))
    binary = Column(String(255))
    topic = Column(String(255))
    report_count = Column(Integer, nullable=False, default=0)
    disabled = Column(Boolean, default=False)
    disabled_reason = Column(String(255))
    last_seen_up = Column(DateTime, nullable=True)
    forced_down = Column(Boolean, default=False)
    version = Column(Integer, default=0)

    instance = orm.relationship(
        "Instance",
        backref='services',
        primaryjoin='and_(Service.host == Instance.host,'
                    'Service.binary == "nova-compute",'
                    'Instance.deleted == 0)',
        foreign_keys=host,
    )