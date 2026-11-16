"""Small named registries for explicitly installed application extensions."""

import re


class Registry:
    def __init__(self, kind):
        self.kind = kind
        self._entries = {}

    def register(self, name, value):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", name):
            raise ValueError(f"Invalid {self.kind} registration name: {name!r}")
        if name in self._entries:
            raise ValueError(f"Duplicate {self.kind} registration: {name}")
        self._entries[name] = value
        return value

    def get(self, name):
        try:
            return self._entries[name]
        except KeyError:
            raise KeyError(f"Unknown {self.kind}: {name}") from None

    def items(self):
        return tuple(sorted(self._entries.items()))
