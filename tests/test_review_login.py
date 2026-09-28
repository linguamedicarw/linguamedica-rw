"""
Reviewer login, as the reviewers will meet it on a phone.

Phones capitalise the first letter of a text box, so the username must be
found whatever its capitals; the password stays exact. The email that
brings the reviewers in links to /review/guideline, so signing in from that
link must land on the guideline, not on a term.
"""
from urllib.parse import urlparse

import pytest

from models import db, Reviewer

PASSWORD = "test-only-password"


def _add_reviewer(app, code, username, active=True, display_name=None):
    with app.app_context():
        r = Reviewer(code=code, display_name=display_name or username.title(),
                     username=username, active=active)
        r.set_password(PASSWORD)
        db.session.add(r)
        db.session.commit()


@pytest.fixture
def olive(app):
    _add_reviewer(app, "OU", "olive")


def _login(client, username, password=PASSWORD, url="/review/login"):
    return client.post(url, data={"username": username, "password": password})


def _path(response):
    return urlparse(response.headers.get("Location", "")).path


@pytest.mark.parametrize("typed", ["olive", "Olive", "OLIVE", " olive ", "Olive "])
def test_username_ignores_capitals_and_spaces(client, olive, typed):
    r = _login(client, typed)
    assert r.status_code == 302
    assert _path(r) == "/review"
    assert client.get("/review/guideline").status_code == 200


def test_password_stays_exact(client, olive):
    r = _login(client, "Olive", password=PASSWORD.upper())
    assert r.status_code == 200
    assert b"Invalid username or password." in r.data
    assert client.get("/review/guideline").status_code == 302


def test_unknown_username_is_refused(client, olive):
    r = _login(client, "Olivia")
    assert r.status_code == 200
    assert b"Invalid username or password." in r.data


def test_inactive_account_is_refused_whatever_the_capitals(app, client):
    _add_reviewer(app, "OU", "olive", active=False)
    r = _login(client, "Olive")
    assert r.status_code == 200
    assert b"Invalid username or password." in r.data


def test_capitals_only_help_when_one_account_fits(app, client):
    # Two accounts that differ only in capitals: an exact match still works,
    # a guess that fits both is refused rather than picking one.
    _add_reviewer(app, "AA", "ana", display_name="Ana Lower")
    _add_reviewer(app, "AB", "Ana", display_name="Ana Upper")
    refused = _login(client, "ANA")
    assert refused.status_code == 200
    assert b"Invalid username or password." in refused.data
    r = client.post("/review/login", data={"username": "ana", "password": PASSWORD},
                    follow_redirects=True)
    assert b"Welcome, Ana Lower." in r.data


def test_login_box_tells_phones_not_to_capitalise(client):
    page = client.get("/review/login")
    assert page.status_code == 200
    assert b'autocapitalize="none"' in page.data
    assert b'autocorrect="off"' in page.data


def test_guideline_link_lands_on_the_guideline_after_sign_in(client, olive):
    first = client.get("/review/guideline")
    assert first.status_code == 302
    login_url = first.headers["Location"]
    assert urlparse(login_url).path == "/review/login"
    r = _login(client, "Olive", url=login_url)
    assert r.status_code == 302
    assert _path(r) == "/review/guideline"
    page = client.get("/review/guideline")
    assert page.status_code == 200
    assert b"Reviewer guideline" in page.data
