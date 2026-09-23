from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Nome do arquivo do banco SQLite local
SQLALCHEMY_DATABASE_URL = "sqlite:///./carbono.db"

# connect_args={"check_same_thread": False} é necessário apenas no SQLite
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()