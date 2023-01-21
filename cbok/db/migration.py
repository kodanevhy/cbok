"""Database setup and migration commands."""

from cbok.db.sqlalchemy import migration

IMPL = migration


def db_sync(version=None, database='main', context=None):
    """Migrate the database to `version` or the most recent version."""
    return IMPL.db_sync(version=version, database=database, context=context)


def db_version(database='main', context=None):
    """Display the current database version."""
    return IMPL.db_version(database=database, context=context)


def db_initial_version(database='main'):
    """The starting version for the database."""
    return IMPL.db_initial_version(database=database)
