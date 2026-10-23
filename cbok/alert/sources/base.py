"""Transport-neutral source values and adapter contract."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json
from typing import Any, Protocol


def _json_dict(value):
    result = asdict(value)
    json.dumps(result, allow_nan=False)
    return result


@dataclass
class SourceItem:
    external_id: str
    title: str = ''
    url: str = ''
    published_at: Any = None
    content: str = ''
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return _json_dict(self)


@dataclass
class Observation:
    format: str
    data: Any
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return _json_dict(self)


class SourceError(Exception):
    def __init__(self, code, message, evidence=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.evidence = deepcopy(evidence)


class SourceAdapter(Protocol):
    def collect(self, section: dict, limit: int = 12) -> list[SourceItem]: ...

    def read(self, item: dict) -> SourceItem: ...

    def observe(self, section: dict, kind: str) -> Observation: ...
