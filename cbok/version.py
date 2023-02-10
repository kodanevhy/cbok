import pbr.version

CBoK_VENDOR = "CBoK"
CBoK_PRODUCT = "CBoK"
CBoK_PACKAGE = None  # OS distro package version suffix
CBoK_SUPPORT = (
    "Please report this at https://github.com/kodanevhy/cbok "
    "and attach the CBoK API log if possible.")

loaded = False
version_info = pbr.version.VersionInfo('cbok')
version_string = version_info.version_string


def _load_config():
    # Don't load in global context, since we can't assume
    # these modules are accessible when distutils uses
    # this module
    import configparser

    from oslo_config import cfg

    from oslo_log import log as logging

    global loaded, CBoK_VENDOR, CBoK_PRODUCT, CBoK_PACKAGE, CBoK_SUPPORT
    if loaded:
        return

    loaded = True

    cfgfile = cfg.CONF.find_file("release")
    if cfgfile is None:
        return

    try:
        cfg = configparser.RawConfigParser()
        cfg.read(cfgfile)

        if cfg.has_option("CBoK", "vendor"):
            CBoK_VENDOR = cfg.get("CBoK", "vendor")

        if cfg.has_option("CBoK", "product"):
            CBoK_PRODUCT = cfg.get("CBoK", "product")

        if cfg.has_option("CBoK", "package"):
            CBoK_PACKAGE = cfg.get("CBoK", "package")

        if cfg.has_option("CBoK", "support"):
            CBoK_SUPPORT = cfg.get("CBoK", "support")
    except Exception as ex:
        LOG = logging.getLogger(__name__)
        LOG.error("Failed to load %(cfgfile)s: %(ex)s",
                  {'cfgfile': cfgfile, 'ex': ex})


def vendor_string():
    _load_config()

    return CBoK_VENDOR


def product_string():
    _load_config()

    return CBoK_PRODUCT


def package_string():
    _load_config()

    return CBoK_PACKAGE


def version_string_with_package():
    if package_string() is None:
        return version_info.version_string()
    else:
        return "%s-%s" % (version_info.version_string(), package_string())


def support_string():
    _load_config()

    return CBoK_SUPPORT
