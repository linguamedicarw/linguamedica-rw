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
def app(monkeypatch):
    """A fresh app with an isolated SQLite database, torn down after each test."""
    # create_app() seeds reviewer accounts from REVIEWER_ACCOUNTS at boot.
    # A developer running the local server exports that variable, and if it
    # leaks into the test process the fixture in tests/test_review.py that
    # creates the OU reviewer collides with the seeded row
    # (UNIQUE constraint failed: reviewers.code). Tests build the reviewers
    # they need themselves, so the test app must boot without it.
    monkeypatch.delenv("REVIEWER_ACCOUNTS", raising=False)

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