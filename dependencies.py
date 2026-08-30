from types import SimpleNamespace

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from config import SUPABASE_URL
from database import get_db
from models.models import Users

_JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
_jwk_client = jwt.PyJWKClient(_JWKS_URL)  # cachet de publieke sleutel(s) zelf


def get_current_user(authorization: str = Header(...)):
    """Verifies the Supabase access token locally, using Supabase's public JWKS
    (no network call to Supabase per request - the JWKS client caches keys).

    Expects header: Authorization: Bearer <access_token>

    Returns:
        A SimpleNamespace with .id and .email, mirroring the parts of the
        Supabase user object the rest of the API relies on.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )

    token = authorization.removeprefix("Bearer ").strip()

    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return SimpleNamespace(id=payload["sub"], email=payload.get("email"))


def get_current_verified_user(
    current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    """Same as get_current_user, but blocks unverified accounts.

    Use this instead of get_current_user on any endpoint that should be
    unreachable until the user has confirmed their email address.
    """
    user = db.query(Users).filter_by(id=current_user.id).first()
    if user is None or not user.email_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    return current_user


def get_bearer_token(authorization: str = Header(...)) -> str:
    """Raw token string, e.g. to pass along to a user-scoped Supabase client."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )
    return authorization.removeprefix("Bearer ").strip()
