from abc import ABC, abstractmethod
from typing import List, Optional


class BaseEmailService(ABC):
    @abstractmethod
    def send(
        self,
        subject: str,
        to: List[str],
        body: Optional[str] = None,
        html_body: Optional[str] = None,
    ) -> None:
        pass
