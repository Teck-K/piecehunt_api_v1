import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # leest .env in bij lokale development; op de server staan de vars al in de omgeving

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SUPABASE_JWT_SECRET = os.environ[
    "SUPABASE_JWT_SECRET"
]  # nieuw: voor lokale tokenverificatie
DATABASE_URL = os.environ["DATABASE_URL"]

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / "logs" / "output"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
EMAIL_TEMPLATES_DIR = BASE_DIR / "services" / "email" / "templates"
WEB_TEMPLATES_DIR = BASE_DIR / "services" / "web" / "templates"

REBRICKABLE_KEY = os.environ["REBRICKABLE_KEY"]

DEVELOPER_EMAIL = os.environ["DEVELOPER_EMAIL"]
NO_REPLY_EMAIL = os.environ["NO_REPLY_EMAIL"]
FEEDBACK_EMAIL = os.environ["FEEDBACK_EMAIL"]
