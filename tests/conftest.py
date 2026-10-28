"""
Configura o ambiente e o banco de dados de testes.

As variáveis de ambiente são definidas antes de importar a aplicação para que
todos os módulos (inclusive o `lifespan`) utilizem o banco de teste em vez do
`carbono.db` de desenvolvimento.
"""

import os
import sqlite3
from collections.abc import Generator
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test_carbono.db"
os.environ["SEED_DEV_DATA"] = "true"
os.environ["SMTP_HOST"] = ""
os.environ["SECRET_KEY"] = "chave-secreta-dos-testes-com-mais-de-32-caracteres"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from src.app import app  # noqa: E402
from src.core.database import get_db  # noqa: E402

TEST_DATABASE_URL = "sqlite:///./test_carbono.db"
test_engine = create_engine(
    TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def reseed_database() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    con = sqlite3.connect("test_carbono.db")
    cursor = con.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF;")
    query_tables = (
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%';"
    )
    tables = [row[0] for row in cursor.execute(query_tables).fetchall()]
    for table in tables:
        cursor.execute(f"DROP TABLE IF EXISTS {table};")
    cursor.execute("PRAGMA foreign_keys = ON;")

    for script in ("create_db.sql", "seed_dev.sql"):
        script_path = base_dir / "src" / script
        if script_path.exists():
            con.executescript(script_path.read_text(encoding="utf-8"))
    con.commit()
    con.close()


@pytest.fixture(scope="session", autouse=True)
def teardown_test_db_after_session() -> Generator[None, None, None]:
    Path("test_carbono.db").unlink(missing_ok=True)
    reseed_database()
    yield
    Path("test_carbono.db").unlink(missing_ok=True)


@pytest.fixture(scope="module", autouse=True)
def clean_db_per_module() -> Generator[None, None, None]:
    reseed_database()
    yield


def override_get_db() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db() -> Generator[Session, None, None]:
    db_session = TestingSessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()
