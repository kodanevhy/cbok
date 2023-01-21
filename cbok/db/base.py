"""Base class for classes that need database access."""

import cbok.db.api


class Base(object):
    """DB driver is injected in the init method."""

    def __init__(self):
        super(Base, self).__init__()
        self.db = cbok.db.api
