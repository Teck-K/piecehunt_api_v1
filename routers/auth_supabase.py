"""Authentication routes using Supabase GoTrue API.

Provides endpoints for user login, registration, and token refresh.
These replace direct Supabase client calls from the app.
"""

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Supabase configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError(
        "Missing SUPABASE_URL or SUPABASE_ANON_KEY environment variables"
    )

SUPABASE_AUTH_URL = f"{SUPABASE_URL}/auth/v1"


# Pydantic models
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    user_id: str
    access_token: str
    refresh_token: str
    email: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterResponse(BaseModel):
    success: bool
    needs_email_confirmation: bool
    user_id: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    email: str | None = None
    error: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """Sign in a user with email and password.

    Args:
        body: Email and password credentials

    Returns:
        LoginResponse with user_id, access_token, refresh_token, and email

    Raises:
        HTTPException: If login fails (invalid credentials, etc.)
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SUPABASE_AUTH_URL}/token?grant_type=password",
                json={
                    "email": body.email,
                    "password": body.password,
                },
                headers={"apikey": SUPABASE_ANON_KEY},
                timeout=10.0,
            )
            response.raise_for_status()

        data = response.json()

        if not data.get("access_token") or not data.get("user"):
            logger.warning(
                "Login returned incomplete response for email: %s", body.email
            )
            raise HTTPException(status_code=401, detail="Invalid email or password")

        logger.info("User logged in: %s", body.email)

        return LoginResponse(
            user_id=data["user"]["id"],
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            email=body.email,
        )

    except httpx.HTTPStatusError as e:
        logger.warning("Login failed for email: %s (%s)", body.email, e)
        if e.response.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        raise HTTPException(status_code=502, detail="Authentication service error")

    except Exception:
        logger.exception("Login error for email: %s", body.email)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/register", response_model=RegisterResponse)
async def register(body: RegisterRequest):
    """Register a new user with email and password.

    Behavior depends on Supabase configuration:
    - If email confirmation is disabled: returns access/refresh tokens immediately
    - If email confirmation is enabled: user must confirm email before login

    Args:
        body: Email and password for new account

    Returns:
        RegisterResponse with success status and optional tokens

    Raises:
        HTTPException: If registration fails (email already exists, etc.)
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SUPABASE_AUTH_URL}/signup",
                json={
                    "email": body.email,
                    "password": body.password,
                },
                headers={"apikey": SUPABASE_ANON_KEY},
                timeout=10.0,
            )
            response.raise_for_status()

        data = response.json()

        if not data.get("user"):
            logger.warning("Registration returned no user for email: %s", body.email)
            raise HTTPException(
                status_code=400, detail="Unknown error during registration"
            )

        user = data["user"]
        session = data.get("session")

        if session:
            # Email confirmation not required
            logger.info("User registered and logged in: %s", body.email)
            return RegisterResponse(
                success=True,
                needs_email_confirmation=False,
                user_id=user["id"],
                access_token=session.get("access_token"),
                refresh_token=session.get("refresh_token"),
                email=body.email,
            )
        else:
            # Email confirmation required
            logger.info("User registered, needs email confirmation: %s", body.email)
            return RegisterResponse(
                success=True,
                needs_email_confirmation=True,
                user_id=user["id"],
                email=body.email,
            )

    except httpx.HTTPStatusError as e:
        logger.warning("Registration failed for email: %s (%s)", body.email, e)
        if e.response.status_code == 422:
            raise HTTPException(
                status_code=400, detail="Email already registered or invalid password"
            )
        raise HTTPException(status_code=502, detail="Authentication service error")

    except Exception:
        logger.exception("Registration error for email: %s", body.email)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(body: RefreshRequest):
    """Refresh an access token using a refresh token.

    Called when access token expires to get a new one without re-logging in.

    Args:
        body: Refresh token from previous login/refresh

    Returns:
        RefreshResponse with new access_token, refresh_token, and user_id

    Raises:
        HTTPException: If refresh token is invalid or expired
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SUPABASE_AUTH_URL}/token?grant_type=refresh_token",
                json={"refresh_token": body.refresh_token},
                headers={"apikey": SUPABASE_ANON_KEY},
                timeout=10.0,
            )
            response.raise_for_status()

        data = response.json()

        if not data.get("access_token") or not data.get("user"):
            logger.warning("Refresh returned incomplete response")
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        logger.info("Session refreshed for user: %s", data["user"]["id"])

        return RefreshResponse(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            user_id=data["user"]["id"],
        )

    except httpx.HTTPStatusError as e:
        logger.warning("Refresh failed (%s)", e)
        if e.response.status_code in (401, 422):
            raise HTTPException(
                status_code=401, detail="Invalid or expired refresh token"
            )
        raise HTTPException(status_code=502, detail="Authentication service error")

    except Exception:
        logger.exception("Refresh error")
        raise HTTPException(status_code=500, detail="Internal server error")
