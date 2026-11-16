import configparser
import os

from cbok.conf import config


def resolve_cbok_conf_path(base_dir):
    conf_path = os.environ.get("CBOK_CONF", "").strip()
    if conf_path:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(conf_path)))
    return os.path.join(base_dir, "cbok.conf")


def read_cbok_conf(conf_path):
    conf = configparser.ConfigParser()
    conf.read(conf_path)
    default = config.DEFAULT
    if conf.has_section(default.name):
        for opt in default.options:
            if not opt.required and opt.default is not None:
                if not conf.get(default.name, opt.name, fallback="").strip():
                    conf.set(default.name, opt.name, str(opt.default))
    return conf
