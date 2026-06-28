"""
Pytest fixtures for the LinguaMedica RW test suite.

Each test gets a fresh app backed by a throwaway SQLite file, with CSRF and
rate-limiting disabled so the test client can post forms directly.
"""
import os
import tempfile

import pytest

# Seeded-admin credentials. seed_data reads these at import time, so set them
# before importing the app — then the auto-seeded admin has known credentials.
os.environ.setdefault("ADMIN_USERNAME", "testadmin")
os.environ.setdefault("ADMIN_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app import create_app  # noqa: E402  (must import after env is set)

ADMIN_USERNAME = os.environ["ADMIN_USERNAME"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]


@pytest.fixture
def app():
    """A fresh app with an isolated SQLite database, torn down after each test."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    application = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    yield application
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(client):
    """A test client already logged in as the seeded admin."""
    client.post("/admin/login", data={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
    })
    return client