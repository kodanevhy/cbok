import abc
from abc import ABC
from typing import List, Optional


class BaseEmailService(ABC):
    @abc.abstractmethod
    def send(
        self,
        subject: str,
        to: List[str],
        body: Optional[str] = None,
        html_body: Optional[str] = None,
    ) -> None:
        pass
