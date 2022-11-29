from oslo_config import cfg

idea_group = cfg.OptGroup('idea',
                          title='idea options',
                          help='Options under this group are used to define'
                               ' idea.')

TEMPLATE_OPTS = [
    cfg.ListOpt(
        'entry',
        default=['Question now', 'To Study', 'To archive', 'Other immediate'],
        help="""
        Some successive stages of ideas.
        
        * Question now: The idea is still a question now, just make a record.
        * To Study: Prepare to take time to study the idea.
        * To archive: Represent that the idea is ready to be writen to the doc.
        * Other immediate: Other ideas not include in the above but do need 
          to make a record.
        """
    ),
]

IDEA_OPTS = []

ALL_OPTS = (TEMPLATE_OPTS +
            IDEA_OPTS)


def register_opts(conf):
    conf.register_group(idea_group)
    conf.register_opts(ALL_OPTS, group=idea_group)


def list_opts():
    return {idea_group: ALL_OPTS}
