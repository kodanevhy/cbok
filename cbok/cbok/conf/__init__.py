from oslo_config import cfg

from cbok.conf import common

CONF = cfg.CONF

common.register_opts(CONF)
