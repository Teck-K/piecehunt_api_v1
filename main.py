from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler

from config import ALLOWED_ORIGINS
from logs.logging_config import setup_logging
from rate_limit import limiter
from routers import accounts, auth, auth_supabase, feedback, parts, reports, sets

setup_logging(debug_mode=False)

app = FastAPI(title="Piecehunt API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router)
app.include_router(sets.router)
app.include_router(parts.router)
app.include_router(auth.router)
app.include_router(auth_supabase.router)
app.include_router(reports.router)
app.include_router(feedback.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
