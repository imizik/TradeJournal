"""Setup emails for the scanner (S1): one plain-text message per setup to the owner's inbox.

Sent through Gmail's SMTP with an app password kept in the server's private
environment (``SCANNER_SMTP_USER``, ``SCANNER_SMTP_PASSWORD``), to
``SCANNER_EMAIL_TO``. This is separate from the read-only Gmail connection that
imports fills: it holds no OAuth token and cannot read mail.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

HOST, PORT = "smtp.gmail.com", 465
TIMEOUT_SECONDS = 15


class MailError(Exception):
    pass


def configured() -> bool:
    return all(os.environ.get(k, "").strip() for k in ("SCANNER_EMAIL_TO", "SCANNER_SMTP_USER", "SCANNER_SMTP_PASSWORD"))


def send(subject: str, body: str) -> None:
    """Send one message; raises ``MailError`` when Gmail did not accept it."""
    user = os.environ.get("SCANNER_SMTP_USER", "").strip()
    message = EmailMessage()
    message["From"] = f"TradeJournal scanner <{user}>"
    message["To"] = os.environ.get("SCANNER_EMAIL_TO", "").strip()
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP_SSL(HOST, PORT, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context()) as smtp:
            smtp.login(user, os.environ.get("SCANNER_SMTP_PASSWORD", "").replace(" ", ""))
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Gmail did not accept the setup email ({type(exc).__name__}).") from exc
