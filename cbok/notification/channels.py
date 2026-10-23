"""Explicitly registered synchronous notification transports.

A factory accepts channel configuration and returns an object whose
``send(message)`` returns None only after confirmed delivery, or raises.
Custom factories and sends must finish within 300 seconds total, including
connection, I/O and retries, leaving 60 seconds of the outbox lease for updates.
Every blocking operation needs a finite timeout. This trusted in-process
interface cannot terminate arbitrary plugin code; a lease is not a timeout.
The builtin email channel bounds each SMTP socket operation to at most 30 seconds,
not the total send: recipient count, multiple exchanges, DNS, and slow trickle
responses can extend total duration. Deployments needing a hard wall-clock bound
must use a transport/process supervisor that enforces it.
Importing this module does not configure Django or open a transport.
"""

from copy import deepcopy
from dataclasses import dataclass, field

from cbok.registry import Registry


@dataclass(frozen=True)
class NotificationMessage:
    subject: str
    body: str
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        # A caller can reuse or mutate its source metadata independently.
        object.__setattr__(self, "metadata", deepcopy(self.metadata))


_channels = Registry("notification channel")


def register_channel(name, factory):
    """Register a factory that obeys the bounded-send contract above."""
    if not callable(factory):
        raise ValueError("Notification channel factory must be callable")
    return _channels.register(name, factory)


def list_channels():
    """Return registered (name, factory) pairs in stable name order."""
    return _channels.items()


def send_notification(kind: str, config: dict, message: NotificationMessage) -> None:
    """Deliver one message, propagating transport and configuration failures."""
    channel = _channels.get(kind)(config)
    if channel.send(message) is not None:
        raise RuntimeError("Notification channel did not confirm delivery")


class EmailChannel:
    def __init__(self, config):
        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email

        if not isinstance(config, dict):
            raise ValueError("Email channel configuration must be a dictionary")
        recipients = config.get("to")
        if not isinstance(recipients, list) or not recipients:
            raise ValueError("Email channel 'to' must be a nonempty list of email addresses")
        for recipient in recipients:
            if not isinstance(recipient, str) or "\r" in recipient or "\n" in recipient:
                raise ValueError("Email channel contains an invalid recipient")
            try:
                validate_email(recipient)
            except ValidationError:
                raise ValueError("Email channel contains an invalid recipient") from None
        timeout = config.get('timeout', 30)
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise ValueError("Email channel timeout must be finite and between 0 and 30 seconds")
        self.timeout = float(timeout)
        self.recipients = list(recipients)

    def send(self, message: NotificationMessage) -> None:
        from cbok.notification.email.backend import DjangoEmailService

        DjangoEmailService().send(
            subject=message.subject, to=self.recipients, body=message.body, timeout=self.timeout,
        )


register_channel("email", EmailChannel)
