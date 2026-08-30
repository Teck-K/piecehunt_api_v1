# routers/reports.py
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from config import NO_REPLY_EMAIL
from database import get_db
from dependencies import get_current_verified_user
from models.models import Users
from services.email.sender import send_email

router = APIRouter(prefix="/reports", tags=["reports"])

MAX_REPORT_FILE_SIZE = 5 * 1024 * 1024
ALLOWED_REPORT_TYPES = {
    "application/pdf",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png",
    "image/jpeg",
    "image/webp",
}
ALLOWED_REPORT_EXTENSIONS = {".pdf", ".xls", ".xlsx", ".png", ".jpg", ".jpeg", ".webp"}


async def _read_validated_report_file(file: UploadFile) -> bytes:
    filename = (file.filename or "").lower()
    extension = Path(filename).suffix.lower()
    content_type = (file.content_type or "").lower()

    if (
        extension not in ALLOWED_REPORT_EXTENSIONS
        and content_type not in ALLOWED_REPORT_TYPES
    ):
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Allowed: PDF, XLS, XLSX, PNG, JPG, JPEG, WEBP.",
        )

    contents = await file.read()
    if len(contents) > MAX_REPORT_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum size is 5 MB.",
        )

    await file.seek(0)
    return contents


@router.post("/missing-parts/email")
async def email_missing_parts_report(
    file: UploadFile = File(...),
    part_count: int = Form(...),
    set_count: int = Form(...),
    include_spares: bool = Form(...),
    current_user=Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Receives a generated report file from the desktop app and emails it
    to the requesting (verified) user.

    The report itself is generated client-side, since it currently embeds
    part/set images that only exist locally.
    """
    user = db.query(Users).filter_by(id=current_user.id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    contents = await _read_validated_report_file(file)

    with tempfile.NamedTemporaryFile(
        suffix=Path(file.filename).suffix, delete=False
    ) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        await send_email(
            to_address=user.email,
            from_address=NO_REPLY_EMAIL,
            subject="PieceHunt – Missing Parts Report",
            template_name="missing_parts_report",
            attachments=[tmp_path],
            username=user.email,
            part_count=part_count,
            set_count=set_count,
            spares_note="Included" if include_spares else "Excluded",
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    return {"detail": "Report emailed"}
