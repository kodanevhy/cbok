from oslo_config import cfg

common_group = cfg.OptGroup('common',
                            title='common options',
                            help='Options under this group are used to define'
                                 ' common config.')

COMMON_OPTS = [
    cfg.StrOpt(
        'workspace',
        default='Workspace',
        help='An extremely outer directory name for starting up. You may set '
             '"workspace" and "workspace_abs_path" in your favor.'
    ),
    cfg.StrOpt(
        'workspace_abs_path',
        default='~/',
        help='The absolute directory path of workspace.'
    )
]


def register_opts(conf):
    conf.register_group(common_group)
    conf.register_opts(COMMON_OPTS, group=common_group)


def list_opts():
    return {common_group: COMMON_OPTS}
