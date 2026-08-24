import configparser
import os


def resolve_cbok_conf_path(base_dir):
    conf_path = os.environ.get("CBOK_CONF", "").strip()
    if conf_path:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(conf_path)))
    return os.path.join(base_dir, "cbok.conf")


def read_cbok_conf(conf_path):
    conf = configparser.ConfigParser()
    conf.read(conf_path)
    return conf
