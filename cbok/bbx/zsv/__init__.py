__all__ = [
    "UPGRADE_TYPES",
    "ZSphereTracker",
]


def __getattr__(name):
    if name in __all__:
        from cbok.bbx.zsv import service
        return getattr(service, name)
    raise AttributeError(name)
