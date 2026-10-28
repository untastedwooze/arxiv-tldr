"""Mailer: the send interface, and its Gmail SMTP implementation."""

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol


@dataclass(frozen=True)
class Message:
    subject: str
    html: str
    text: str
    recipients: list[str]


class Mailer(Protocol):
    def send(self, message: Message) -> None:
        """Send the message; raise if the server does not accept it."""


class GmailMailer:
    """Gmail SMTP over TLS, authenticated with an App Password."""

    def __init__(
        self, address: str, app_password: str, host: str = "smtp.gmail.com", port: int = 465
    ):
        self._address, self._password, self._host, self._port = address, app_password, host, port

    def send(self, message: Message) -> None:
        mail = EmailMessage()
        mail["Subject"] = message.subject
        mail["From"] = self._address
        mail["To"] = ", ".join(message.recipients)
        mail.set_content(message.text)
        mail.add_alternative(message.html, subtype="html")
        with smtplib.SMTP_SSL(self._host, self._port, context=ssl.create_default_context(), timeout=60) as smtp:
            smtp.login(self._address, self._password)
            smtp.send_message(mail)
