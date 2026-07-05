"""Shared test fixtures. Uses a file-backed SQLite db so worker threads can
share the same database in the concurrency tests."""
import os
import tempfile

import pytest

# Configure the database BEFORE importing anything that builds the engine.
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["JWT_SECRET"] = "test-secret"

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models  # noqa: E402,F401
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.create_all(bind=engine)
    yield
    try:
        os.close(_DB_FD)
        os.unlink(_DB_PATH)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _clean_tables():
    """Wipe every table between tests for isolation."""
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_client(client):
    """A TestClient with an Authorization header for a fresh org/user."""
    r = client.post("/api/v1/auth/register", json={
        "organization_name": "Acme", "email": "owner@acme.example.com",
        "password": "password123", "full_name": "Owner",
    })
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
