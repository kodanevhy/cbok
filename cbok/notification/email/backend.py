from typing import List, Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from cbok.notification.email import base


class DjangoEmailService(base.BaseEmailService):
    def send(
        self,
        subject: str,
        to: List[str],
        body: Optional[str] = None,
        html_body: Optional[str] = None,
    ) -> None:
        if not body and not html_body:
            raise ValueError("Either body or html_body must be provided")

        msg = EmailMultiAlternatives(
            subject=subject,
            body=body or "",
            from_email=settings.EMAIL_FROM,
            to=to,
        )

        if html_body:
            msg.attach_alternative(html_body, "text/html")

        msg.send(fail_silently=False)
