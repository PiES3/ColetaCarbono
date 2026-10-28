import os
import sqlite3
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.app import app
from src.core.database import get_db

TEST_DATABASE_URL = "sqlite:///./test_carbono.db"
test_engine = create_engine(
    TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def reseed_database() -> None:
    base_dir = os.path.dirname(os.path.dirname(__file__))
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
        script_path = os.path.join(base_dir, "src", script)
        if os.path.exists(script_path):
            with open(script_path, encoding="utf-8") as f:
                con.executescript(f.read())
    con.commit()
    con.close()


@pytest.fixture(scope="session", autouse=True)
def teardown_test_db_after_session() -> Generator[None, None, None]:
    yield
    if os.path.exists("test_carbono.db"):
        os.remove("test_carbono.db")


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
