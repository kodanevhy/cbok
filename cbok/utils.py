import functools

from cbok import settings


def identify():
    """Verify if user is valid."""
    def inner(func):
        @functools.wraps(func)
        def wrapper():
            pass
        return func()
    return inner


def applications():
    return settings.CBoK_APPS
