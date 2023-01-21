from oslo_config import cfg

api_group = cfg.OptGroup('api',
                         title='API options',
                         help="""
Options under this group are used to define CBoK API.
""")

API_OPTS = [
    cfg.StrOpt('host',
               default='0.0.0.0',
               help='CBoK server host.'),
    cfg.IntOpt('port',
               default=9515,
               help='CBoK server port.'),
    cfg.IntOpt('api_works',
               default=8,
               help='The number of api works.'),
    cfg.StrOpt('api_url',
               default='cbok'),
]


def register_opts(conf):
    conf.register_group(api_group)
    conf.register_opts(API_OPTS, group=api_group)


def list_opts():
    return {api_group: API_OPTS}
