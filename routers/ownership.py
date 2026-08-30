from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.models import UserSets


def get_owned_userset(db: Session, user_set_id: int, user_id: str) -> UserSets:
    """Ownership-check: geeft de UserSets-rij terug, of 404 als ze niet van deze user is.

    Shared between routers/sets.py and routers/parts.py to avoid duplicating
    this security-critical check.
    """
    userset = db.query(UserSets).filter_by(id=user_set_id, user_id=user_id).first()
    if userset is None:
        raise HTTPException(status_code=404, detail="Userset not found")
    return userset
