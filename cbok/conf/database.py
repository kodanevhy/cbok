from oslo_config import cfg

db_group = cfg.OptGroup('db',
                        title='Database Options',
                        help="""CBoK Database""")

db_opts = [
    # TODO(kodanevhy): This should probably have a required=True attribute
    cfg.StrOpt('connection',
        secret=True,
        # This help gets appended to the oslo.db help so prefix with a space.
        help=''),
    cfg.StrOpt('connection_parameters',
        default='',
        help=''),
    cfg.BoolOpt('sqlite_synchronous',
        default=True,
        help=''),
    cfg.StrOpt('slave_connection',
        secret=True,
        help=''),
    cfg.StrOpt('mysql_sql_mode',
        default='TRADITIONAL',
        help=''),
    cfg.IntOpt('connection_recycle_time',
        default=3600,
        deprecated_name='idle_timeout',
        help=''),
    # TODO(kodanevhy): We should probably default this to 5 to not rely on the
    # SQLAlchemy default. Otherwise we wouldn't provide a stable default.
    cfg.IntOpt('max_pool_size',
        help=''),
    cfg.IntOpt('max_retries',
        default=10,
        help=''),
    # TODO(kodanevhy): This should have a minimum attribute of 0
    cfg.IntOpt('retry_interval',
        default=10,
        help=''),
    # TODO(kodanevhy): We should probably default this to 10 to not rely on the
    # SQLAlchemy default. Otherwise we wouldn't provide a stable default.
    cfg.IntOpt('max_overflow',
        help=''),
    # TODO(kodanevhy): This should probably make use of the "choices" attribute.
    # "oslo.db" uses only the values [<0, 0, 50, 100] see module
    # /oslo_db/sqlalchemy/engines.py method "_setup_logging"
    cfg.IntOpt('connection_debug',
        default=0,
        help=''),
    cfg.BoolOpt('connection_trace',
        default=False,
        help=''),
    # TODO(kodanevhy): We should probably default this to 30 to not rely on the
    # SQLAlchemy default. Otherwise we wouldn't provide a stable default.
    cfg.IntOpt('pool_timeout',
        help='')
]  # noqa


def register_opts(conf):
    conf.register_opts(db_opts, group=db_group)


def list_opts():
    return {
        db_group: db_opts,
    }
