__all__ = ["DEFAULT_ISO_URL", "DEFAULT_NODES", "ZSphereTracker"]


def __getattr__(name):
    if name in __all__:
        from cbok.bbx.zsv import service
        return getattr(service, name)
    raise AttributeError(name)
