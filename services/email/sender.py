"""Email sending service for PieceHunt via Resend (async).

Sends HTML emails to users using predefined templates.
Each template requires a .txt and .html file in the templates directory.
The PieceHunt logo is automatically embedded as an inline image.
"""

import base64
import logging
from pathlib import Path

import aiofiles
import httpx

from config import EMAIL_TEMPLATES_DIR, NO_REPLY_EMAIL, RESEND_API_KEY

logger = logging.getLogger(__name__)


def _embed_logo_in_html(html_body: str) -> str:
    """Embed the PieceHunt logo as base64 in HTML.

    Replaces <img ... src="cid:logo" ...> with inline base64 data URL.
    """
    logo_path = EMAIL_TEMPLATES_DIR / "piecehunt_logo3.png"

    if not logo_path.exists():
        logger.warning("Logo file not found at %s, skipping embed", logo_path)
        return html_body

    with open(logo_path, "rb") as f:
        logo_base64 = base64.b64encode(f.read()).decode("utf-8")

    # Replace cid:logo references with data URL
    data_url = f"data:image/png;base64,{logo_base64}"
    html_body = html_body.replace('src="cid:logo"', f'src="{data_url}"')

    return html_body


async def send_email(
    to_address: str,
    subject: str,
    template_name: str,
    attachments: list[Path] | None = None,
    from_address: str = NO_REPLY_EMAIL,
    **kwargs,
) -> bool:
    """Sends an HTML email to a user using a predefined template via Resend (async).

    Both a plain text and HTML version are sent for compatibility.
    The PieceHunt logo is embedded inline as base64.
    Optionally attaches one or more files to the email.

    Args:
        to_address: The recipient email address.
        subject: The email subject line.
        template_name: The name of the template files (without extension).
            Both a .txt and .html version must exist in the templates directory.
        attachments: Optional list of Path objects to attach to the email.
        **kwargs: Template variables passed to str.format() for both versions.

    Returns:
        bool: True if email was sent successfully, False otherwise.
    """

    # Load templates
    try:
        async with aiofiles.open(
            EMAIL_TEMPLATES_DIR / f"{template_name}.txt", "r"
        ) as f:
            text_body = (await f.read()).format(**kwargs)
        async with aiofiles.open(
            EMAIL_TEMPLATES_DIR / f"{template_name}.html", "r"
        ) as f:
            html_body = (await f.read()).format(**kwargs)
    except FileNotFoundError as e:
        logger.error("Template file not found: %s", e)
        return False

    # Embed logo as base64
    html_body = _embed_logo_in_html(html_body)

    # Prepare attachments
    resend_attachments = []
    if attachments:
        for file_path in attachments:
            file_path = Path(file_path)
            if not file_path.exists():
                logger.warning("Attachment not found: %s, skipping", file_path)
                continue

            async with aiofiles.open(file_path, "rb") as f:
                resend_attachments.append(
                    {
                        "filename": file_path.name,
                        "content": base64.b64encode(await f.read()).decode("utf-8"),
                    }
                )

    # Send via Resend API (async)
    api_key = RESEND_API_KEY
    if not api_key:
        logger.error("RESEND_API_KEY environment variable not set")
        return False

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "from": from_address,
                "to": to_address,
                "subject": subject,
                "html": html_body,
                "text": text_body,
            }

            if resend_attachments:
                payload["attachments"] = resend_attachments

            response = await client.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30.0,
            )

            if response.status_code in (200, 201):
                logger.info("Email sent to %s, subject: %s", to_address, subject)
                return True
            else:
                error_text = response.text
                logger.error(
                    "Resend API error %d for %s: %s",
                    response.status_code,
                    to_address,
                    error_text,
                )
                return False

    except Exception as e:
        logger.exception("Failed to send email to %s: %s", to_address, e)
        return False
