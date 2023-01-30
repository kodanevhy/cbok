from oslo_config import cfg
from oslo_log import log as logging

from cbok.conf import api
from cbok.conf import common
from cbok.conf import idea
from cbok.conf import database

CONF = cfg.CONF

common.register_opts(CONF)
api.register_opts(CONF)
idea.register_opts(CONF)
database.register_opts(CONF)
logging.register_options(CONF)
