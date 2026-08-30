# rate_limit.py
"""Rate limiting configuration for the API.

Uses the real client IP as the limiting key, accounting for the
reverse proxy Railway (or similar platforms) sits behind in production.
Falls back to the direct connection IP for local development, where
no proxy header is present.
"""

from slowapi import Limiter
from starlette.requests import Request


def get_client_ip(request: Request) -> str:
    """Returns the real client IP, accounting for reverse proxies (e.g. Railway).

    Falls back to the direct connection IP when no proxy header is present,
    which is the case for local development.

    Note: verify this still matches Railway's actual proxy header behavior
    at deploy time - the exact header/format can vary between platforms.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # X-Forwarded-For kan een komma-gescheiden lijst zijn (client, proxy1, proxy2, ...)
        # het eerste adres is het origineel van de client
        return forwarded.split(",")[0].strip()
    return request.client.host


limiter = Limiter(key_func=get_client_ip)
