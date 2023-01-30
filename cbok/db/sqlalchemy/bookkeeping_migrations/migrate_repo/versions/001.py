from migrate.changeset.constraint import ForeignKeyConstraint
from migrate import UniqueConstraint
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import dialects
from sqlalchemy import Enum
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Text
from sqlalchemy import text
from sqlalchemy import Unicode

from cbok.db.sqlalchemy.models import MediumText


def InetSmall():
    return String(length=39).with_variant(
        dialects.postgresql.INET(), 'postgresql'
    )


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    catkin = Table('catkin', meta,
                   Column('created_at', DateTime),
                   Column('updated_at', DateTime),
                   Column('id', Integer, primary_key=True, nullable=False),
                   Column('uuid', String(length=36), nullable=False),
                   Column('name', String(length=255)),
                   Column('transport_url', Text()),
                   Column('database_connection', Text()),
                   # NOTE(stephenfin): These were originally added by sqlalchemy-migrate
                   # which did not generate the constraints
                   Column('disabled', Boolean(create_constraint=False), default=False),
                   UniqueConstraint('uuid', name='uniq_cell_mappings0uuid'),
                   Index('uuid_idx', 'uuid'),
                   mysql_engine='InnoDB',
                   mysql_charset='utf8'
                   )

    tables = [
        catkin,
    ]
    for table in tables:
        table.create(checkfirst=True)
