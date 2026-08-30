import base64
import logging
from pathlib import Path

import requests

from config import RESEND_API_KEY


class ImageSMTPHandler(logging.Handler):
    """A custom logging handler that sends log records via email with an optional image attachment.

    Extends the standard logging.Handler to support sending emails via Resend API.
    An image can be attached per log call via extra={"image_path": "..."}
    or as a fixed attachment via the image_path constructor argument.

    Args:
        fromaddr: The sender email address.
        toaddrs: A list of recipient email addresses.
        subject: The email subject line.
        image_path: Optional fixed path to an image to attach to every email.
    """

    def __init__(
        self,
        fromaddr: str,
        toaddrs: list[str],
        subject: str,
        image_path: str | None = None,
    ):
        super().__init__()
        self.fromaddr = fromaddr
        self.toaddrs = toaddrs
        self.subject = subject
        self.image_path = image_path

    def emit(self, record):
        """Formats the log record and sends it as an email via Resend.

        If an image path is available via the log record's extra data
        or the handler's fixed image_path, it is attached to the email.

        Args:
            record: The log record to process.
        """
        try:
            log_message = self.format(record)

            payload = {
                "from": self.fromaddr,
                "to": self.toaddrs,
                "subject": self.subject,
                "text": log_message,
            }

            image_path = getattr(record, "image_path", self.image_path)
            if image_path:
                path = Path(image_path)
                with open(path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                payload["attachments"] = [{"filename": path.name, "content": encoded}]

            requests.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                timeout=10.0,
            )

        except Exception:
            self.handleError(record)
