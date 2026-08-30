import logging
import os
import tempfile
from enum import Enum
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from config import DEVELOPER_EMAIL, FEEDBACK_EMAIL
from dependencies import get_current_verified_user
from services.email.sender import send_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])

MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class FeedbackType(str, Enum):
    missing_image = "missing_image"
    false_positive = "false_positive"
    app_error = "app_error"
    other = "other"


async def _read_validated_image(file: UploadFile) -> bytes:
    filename = (file.filename or "").lower()
    extension = Path(filename).suffix.lower()
    content_type = (file.content_type or "").lower()

    if extension not in ALLOWED_IMAGE_EXTENSIONS and content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported image type. Allowed: PNG, JPG, JPEG, WEBP.",
        )

    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Image too large. Maximum size is 5 MB.",
        )

    await file.seek(0)
    return content


@router.post("/report")
async def report_feedback(
    type: FeedbackType = Form(...),
    description: str = Form(...),
    include_logs: bool = Form(False),
    image: UploadFile | None = File(None),
    user=Depends(get_current_verified_user),
):
    attachments: list[Path] = []

    if include_logs:
        log_path = Path("logs/app.log")
        if log_path.exists():
            attachments.append(log_path)
        else:
            logger.warning("Log file not found at %s, skipping attachment", log_path)

    tmp_path: Path | None = None
    if image and type == FeedbackType.false_positive:
        logger.info(
            "Image received: filename=%s, content_type=%s",
            image.filename,
            image.content_type,
        )
        content = await _read_validated_image(image)
        logger.info("Image content size: %s bytes", len(content))
        suffix = Path(image.filename).suffix if image.filename else ".png"
        fd, tmp_path_str = tempfile.mkstemp(suffix=suffix)
        tmp_path = Path(tmp_path_str)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        attachments.append(tmp_path)

    subject = f"[App Report] {type.value.replace('_', ' ').title()}"

    success = await send_email(
        to_address=DEVELOPER_EMAIL,
        subject=subject,
        template_name="feedback_report",
        attachments=attachments or None,
        from_address=FEEDBACK_EMAIL,
        feedback_type=type.value.replace("_", " ").title(),
        description=description,
        user_email=user.email,
        logs_attached="Yes" if any("app.log" in str(a) for a in attachments) else "No",
    )

    if tmp_path and tmp_path.exists():
        tmp_path.unlink()

    if not success:
        raise HTTPException(status_code=500, detail="Failed to send feedback email")

    logger.info("Feedback report sent by %s: type=%s", user.email, type)

    return {"status": "sent"}
