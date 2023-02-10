import cbok.conf
from cbok.db.sqlalchemy import api as sqlalchemy_api

CONF = cbok.conf.CONF


def parse_args(argv):
    default_config_files = ['/etc/cbok/cbok.conf']
    CONF(argv[1:],
         project='cbok',
         version='0.0.1',
         default_config_files=default_config_files)
