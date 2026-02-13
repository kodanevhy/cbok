from typing import List

from cbok.notification.email import template
from cbok.notification.email import backend

email_service = backend.DjangoEmailService()


def send_welcome_email(to: List[str], username: str):
    html = template.render_email_template(
        "alert/welcome.html",
        {"username": username},
    )

    email_service.send(
        subject="Welcome!",
        to=to,
        html_body=html,
    )


def send_initialized_alert_email(to: List[str], topic_name: str, items: list):
    """Send topic initialized summary: question, answer, source article per item."""
    html = template.render_email_template(
        "alert/initialized_alert.html",
        {
            "topic_name": topic_name,
            "items": items,
        },
    )
    email_service.send(
        subject=topic_name,
        to=to,
        html_body=html,
    )


def send_alert_email(to: List[str], title: str, content: str):
    html = template.render_email_template(
        "alert/evolving_alert.html",
        {
            "title": title,
            "content": content,
        },
    )

    email_service.send(
        subject=f"[Alert] {title}",
        to=to,
        html_body=html,
    )
