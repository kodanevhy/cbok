from oslo_config import cfg

COMMON_OPTS = [
    cfg.StrOpt(
        'workspace',
        default='workspace',
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
    conf.register_opts(COMMON_OPTS)


def list_opts():
    return {'DEFAULT': COMMON_OPTS}
