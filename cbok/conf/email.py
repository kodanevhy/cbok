from oslo_config import cfg

email_group = cfg.OptGroup('email',
                           title='Email options',
                           help="""
Options under this group are used to define CBoK email.
""")

EMAIL_OPTS = [
    cfg.StrOpt('server',
               default='',
               help='CBoK email server.'),
    cfg.StrOpt('sender',
               default='',
               help='CBoK email sender.'),
    cfg.StrOpt('port',
               default='',
               help='CBoK email port.'),
    cfg.StrOpt('secret',
               default='',
               help='CBoK email server secret.'),
]


def register_opts(conf):
    conf.register_group(email_group)
    conf.register_opts(EMAIL_OPTS, group=email_group)


def list_opts():
    return {email_group: EMAIL_OPTS}
