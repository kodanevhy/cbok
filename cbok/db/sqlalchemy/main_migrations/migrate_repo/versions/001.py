from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import dialects
from sqlalchemy import Float
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table


def InetSmall():
    return String(length=39).with_variant(
        dialects.postgresql.INET(), 'postgresql'
    )


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    meh = Table('meh', meta,
                Column('created_at', DateTime),
                Column('updated_at', DateTime),
                Column('deleted_at', DateTime),
                Column('deleted', Integer),
                Column('id', Integer, primary_key=True, nullable=False),
                Column('uuid', String(length=36), nullable=False),
                Column('transaction', String(length=36), nullable=True),
                Column('counterparty', String(length=36), nullable=True),
                Column('commodity', String(length=36), nullable=True),
                Column('trade_type', String(length=36), nullable=True),
                Column('payment_method', String(length=36), nullable=True),
                Column('trade_state', String(length=36), nullable=True),
                Column('trade_date', DateTime, nullable=True),
                Column('relationship', String(length=36), nullable=True),
                Column('amount', Float, nullable=False, default=0),
                Column('description', String(length=255), nullable=False),
                Column('worthy', Float, nullable=True),
                Column('ready', Boolean, nullable=True),
                Column('caper', String(length=36), nullable=True),
                Index('uuid_idx', 'uuid'),
                mysql_engine='InnoDB',
                mysql_charset='utf8'
                )
    caper = Table('caper', meta,
                  Column('created_at', DateTime),
                  Column('updated_at', DateTime),
                  Column('deleted_at', DateTime),
                  Column('deleted', Integer),
                  Column('id', Integer, primary_key=True, nullable=False),
                  Column('uuid', String(length=36), nullable=False),
                  Column('name', String(length=255), nullable=False),
                  Column('description', String(length=255), nullable=True),
                  Column('progressing', Boolean, nullable=False, default=False),
                  Index('uuid_idx', 'uuid'),
                  mysql_engine='InnoDB',
                  mysql_charset='utf8'
                  )

    tables = [
        meh,
        caper
    ]
    for table in tables:
        table.create(checkfirst=True)
