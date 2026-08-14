import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite for simplicity/time constraints — swap DATABASE_URL for Postgres in prod.
# File-based SQLite persists across restarts as long as the volume/disk is retained
# (e.g. Railway volume, Fly.io volume). This is documented as a trade-off in the README.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./patients.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
