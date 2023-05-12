from oslo_config import cfg

email_group = cfg.OptGroup('email',
                           title='Email options',
                           help="""
Options under this group are used to define CBoK email.
""")

EMAIL_OPTS = [
    cfg.StrOpt('receiver',
               default='',
               help='CBoK email receiver.'),
    cfg.StrOpt('key_163',
               default='',
               help='CBoK email server key especially for 163.'),
]


def register_opts(conf):
    conf.register_group(email_group)
    conf.register_opts(EMAIL_OPTS, group=email_group)


def list_opts():
    return {email_group: EMAIL_OPTS}
