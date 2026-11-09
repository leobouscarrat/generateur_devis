"""SQLAlchemy engine et session pour la base de données SQLite."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = "sqlite:///./data/devis.db"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def get_session() -> Session:
    """Return a new SQLAlchemy session."""
    return SessionLocal()
