from email.mime.text import MIMEText
import smtplib

from cbok import conf

CONF = conf.CONF


class Message(MIMEText):
    """Class for message."""
    def __init__(self, subject: str, text: str, from_to: dict):
        """Create a message document.

        subject, text is of title and body in email, and from_to claims
        the sender and receiver.
        """
        super().__init__(text, 'plain', 'utf-8')
        self['Subject'] = subject
        self['From'] = from_to.get('from')
        self['To'] = from_to.get('to')


class Email:
    def __init__(self, receiver):
        self.server = 'smtp.163.com'
        self.sender = 'yormng@163.com'
        self.port = 25
        self.key = 'PDSRSAJDHTZSBEYC'
        self.use_tls = False
        self.receiver = receiver

    def authenticate(self):
        smtp_obj = smtplib.SMTP()
        smtp_obj.connect(self.server, self.port)
        smtp_obj.login(self.sender, self.key)
        return smtp_obj

    @property
    def from_to(self):
        return {'from': self.sender, 'to': self.receiver}

    def send(self, message: Message):
        smtp_obj = self.authenticate()

        smtp_obj.sendmail(self.sender, self.receiver, message.as_string())
        smtp_obj.quit()
