from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

try:
    from config_cron import DATABASE_URL
except ImportError:
    from config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"prepare_threshold": None},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: geeft een DB-sessie, sluit hem sowieso weer af."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
