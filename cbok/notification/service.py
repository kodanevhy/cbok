from typing import List
from cbok.notification.email import message


class EmailService:
    @staticmethod
    def welcome(to: List[str], username: str):
        message.send_welcome_email(to, username)

    @staticmethod
    def alert(to: List[str], title: str, content: str):
        message.send_alert_email(to, title, content)
