"""
  CLI interface for cbok management.
"""

import functools
import sys
import traceback

from oslo_config import cfg
from oslo_log import log as logging

from cbok.cmd import common as cmd_common
import cbok.conf
from cbok import config
from cbok.db import migration
from cbok import objects
from cbok import version

CONF = cbok.conf.CONF
LOG = logging.getLogger(__name__)

# Keep this list sorted and one entry per line for readability.
_EXTRA_DEFAULT_LOG_LEVELS = ['oslo_concurrency=INFO',
                             'oslo_db=INFO',
                             'oslo_policy=INFO']

# Consts indicating whether allocations need to be healed by creating them or
# by updating existing allocations.
_CREATE = 'create'
_UPDATE = 'update'

# Decorators for actions
args = cmd_common.args
action_description = cmd_common.action_description


class DbCommands(object):
    """Class for managing the cbok database."""

    def __init__(self):
        pass

    @args('version', metavar='VERSION', nargs='?', help='Database version')
    def sync(self, version=None):
        """Sync the database up to the most recent version."""
        return migration.db_sync(version, database='main')

    def version(self):
        """Print the current database version."""
        print(migration.db_version(database='main'))


CATEGORIES = {
    'db': DbCommands,
}


add_command_parsers = functools.partial(cmd_common.add_command_parsers,
                                        categories=CATEGORIES)


category_opt = cfg.SubCommandOpt('category',
                                 title='Command categories',
                                 help='Available categories',
                                 handler=add_command_parsers)

post_mortem_opt = cfg.BoolOpt('post-mortem',
                              default=False,
                              help='Allow post-mortem debugging')


def main():
    """Parse options and call the appropriate class/method."""
    CONF.register_cli_opts([category_opt, post_mortem_opt])
    config.parse_args(sys.argv)
    logging.set_defaults(
        default_log_levels=logging.get_default_log_levels() +
        _EXTRA_DEFAULT_LOG_LEVELS)
    logging.setup(CONF, "cbok")
    objects.register_all()

    if CONF.category.name == "version":
        print(version.version_string_with_package())
        return 0

    if CONF.category.name == "bash-completion":
        cmd_common.print_bash_completion(CATEGORIES)
        return 0

    try:
        fn, fn_args, fn_kwargs = cmd_common.get_action_fn()
        ret = fn(*fn_args, **fn_kwargs)
        # rpc.cleanup()
        return ret
    except Exception:
        if CONF.post_mortem:
            import pdb
            pdb.post_mortem()
        else:
            print("An error has occurred:\n%s" % traceback.format_exc())
        return 255


if __name__ == '__main__':
    main()
