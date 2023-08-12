import os

from migrate import exceptions as versioning_exceptions
from migrate.versioning import api as versioning_api
from migrate.versioning.repository import Repository
from oslo_log import log as logging
import sqlalchemy
from sqlalchemy.sql import null

from cbok.db.sqlalchemy import api as db_session
from cbok import exception

INIT_VERSION = {'main': 0}
_REPOSITORY = {}

LOG = logging.getLogger(__name__)


def get_engine(database='main'):
    if database == 'main':
        return db_session.get_engine()


def db_sync(version=None, database='main'):
    if version is not None:
        try:
            version = int(version)
        except ValueError:
            raise exception.CBoKException("version should be an integer.")

    current_version = db_version(database)
    repository = _find_migrate_repo(database)
    if version is None or version > current_version:
        return versioning_api.upgrade(get_engine(database),
                                      repository, version)
    else:
        return versioning_api.downgrade(get_engine(database),
                                        repository, version)


def db_version(database='main'):
    repository = _find_migrate_repo(database)

    # NOTE(kodanevhy): This is a crude workaround for races in _db_version. The 2
    # races we have seen in practise are:
    # * versioning_api.db_version() fails because the migrate_version table
    #   doesn't exist, but meta.tables subsequently contains tables because
    #   another thread has already started creating the schema. This results in
    #   the 'Essex' error.
    # * db_version_control() fails with pymysql.error.InternalError(1050)
    #   (Create table failed) because of a race in sqlalchemy-migrate's
    #   ControlledSchema._create_table_version, which does:
    #     if not table.exists(): table.create()
    #   This means that it doesn't raise the advertised
    #   DatabaseAlreadyControlledError, which we could have handled explicitly.
    #
    # I believe the correct fix should be:
    # * Delete the Essex-handling code as unnecessary complexity which nobody
    #   should still need.
    # * Fix the races in sqlalchemy-migrate such that version_control() always
    #   raises a well-defined error, and then handle that error here.
    #
    # Until we do that, though, we should be able to just try again if we
    # failed for any reason. In both of the above races, trying again should
    # succeed the second time round.
    try:
        return _db_version(repository, database)
    except Exception:
        return _db_version(repository, database)


def _db_version(repository, database):
    try:
        return versioning_api.db_version(get_engine(database),
                                         repository)
    except versioning_exceptions.DatabaseNotControlledError as exc:
        meta = sqlalchemy.MetaData()
        engine = get_engine(database)
        meta.reflect(bind=engine)
        tables = meta.tables
        if len(tables) == 0:
            db_version_control(INIT_VERSION[database],
                               database)
            return versioning_api.db_version(
                        get_engine(database), repository)
        else:
            LOG.exception(exc)
            # Some pre-Essex DB's may not be version controlled.
            # Require them to upgrade using Essex first.
            raise exception.CBoKException(
                "Upgrade DB using Essex release first.")


def db_initial_version(database='main'):
    return INIT_VERSION[database]


def _process_null_records(table, col_name, check_fkeys, delete=False):
    """Queries the database and optionally deletes the NULL records.

    :param table: sqlalchemy.Table object.
    :param col_name: The name of the column to check in the table.
    :param check_fkeys: If True, check the table for foreign keys back to the
        instances table and if not found, return.
    :param delete: If true, run a delete operation on the table, else just
        query for number of records that match the NULL column.
    :returns: The number of records processed for the table and column.
    """
    records = 0
    if col_name in table.columns:
        # NOTE(kodanevhy): filter out tables that don't have a foreign key back
        # to the instances table since they could have stale data even if
        # instances.uuid wasn't NULL.
        if check_fkeys:
            fkey_found = False
            fkeys = table.c[col_name].foreign_keys or []
            for fkey in fkeys:
                if fkey.column.table.name == 'instances':
                    fkey_found = True

            if not fkey_found:
                return 0

        if delete:
            records = table.delete().where(
                table.c[col_name] == null()
            ).execute().rowcount
        else:
            records = len(list(
                table.select().where(table.c[col_name] == null()).execute()
            ))
    return records


def db_version_control(version=None, database='main'):
    repository = _find_migrate_repo(database)
    versioning_api.version_control(get_engine(database),
                                   repository,
                                   version)
    return version


def _find_migrate_repo(database='main'):
    """Get the path for the migrate repository."""
    global _REPOSITORY
    rel_path = 'migrate_repo'
    if database == 'main':
        rel_path = os.path.join('main_migrations', 'migrate_repo')
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                        rel_path)
    assert os.path.exists(path)
    if _REPOSITORY.get(database) is None:
        _REPOSITORY[database] = Repository(path)
    return _REPOSITORY[database]
