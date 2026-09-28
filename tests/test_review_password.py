"""
Reviewers choose their own password.

An account starts on a password someone else set: the one sent with the
invitation, or one set by an admin reset. At the next sign-in the reviewer
is sent to choose their own before anything else opens, and from then on
only they know it, so a score under their code can only have come from them.
They can change it again at any time, with their current password.
"""
import sqlite3
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from flask import abort

from app import PASSWORD_MIN_LENGTH, migrate_add_reviewer_password_columns
from models import db, Reviewer, TermReview

SENT = "sent-by-the-editor-2026"      # the temporary password in the invitation
OWN = "my own quiet phrase"           # what the reviewer chooses
TOGGLE_SCRIPT = b"js/password-toggle.js"


def _add(app, code="OU", username="olive", name="Olive Umuhoza", must_change=None):
    with app.app_context():
        r = Reviewer(code=code, username=username, display_name=name)
        if must_change is not None:
            r.must_change_password = must_change
        r.set_password(SENT)
        db.session.add(r)
        db.session.commit()
        return r.id


def _login(client, password=SENT, username="olive", url="/review/login"):
    return client.post(url, data={"username": username, "password": password})


def _choose(client, new=OWN, confirm=None, current=None, url="/review/password"):
    data = {"new_password": new, "confirm_password": new if confirm is None else confirm}
    if current is not None:
        data["current_password"] = current
    return client.post(url, data=data)


def _path(r):
    return urlparse(r.headers.get("Location", "")).path


def _next(r):
    return parse_qs(urlparse(r.headers.get("Location", "")).query).get("next", [None])[0]


def _state(app, rid):
    with app.app_context():
        r = db.session.get(Reviewer, rid)
        return r.must_change_password, r.password_changed_at, r.check_password(SENT)


# --- The first sign-in ---------------------------------------------------------

def test_a_new_account_starts_on_a_temporary_password(app):
    rid = _add(app)
    must_change, changed_at, _ = _state(app, rid)
    assert must_change is True and changed_at is None


def test_first_sign_in_goes_to_choosing_a_password(app, client):
    _add(app)
    r = _login(client)
    assert r.status_code == 302 and _path(r) == "/review/password"
    page = client.get("/review/password")
    assert page.status_code == 200
    assert b"Choose your own password" in page.data
    assert b'name="current_password"' not in page.data     # they just typed it
    assert b'autocomplete="new-password"' in page.data
    assert TOGGLE_SCRIPT in page.data


def test_nothing_else_opens_before_the_password_is_chosen(app, client):
    _add(app)
    _login(client)
    for path in ("/review", "/review/guideline", "/review/history"):
        r = client.get(path)
        assert r.status_code == 302 and _path(r) == "/review/password", path
        assert _next(r) == path
    # a form post is turned away too, and records nothing
    r = client.post("/review/term/1/score", data={"score": "4"})
    assert r.status_code == 302 and _path(r) == "/review/password" and _next(r) is None
    with app.app_context():
        assert TermReview.query.count() == 0
    # logging out stays possible
    out = client.get("/review/logout")
    assert out.status_code == 302 and _path(out) == "/"


def test_choosing_a_password_opens_the_site_and_retires_the_one_sent(app, client):
    rid = _add(app)
    _login(client)
    r = _choose(client)
    assert r.status_code == 302 and _path(r) == "/review"
    must_change, changed_at, sent_still_works = _state(app, rid)
    assert must_change is False and changed_at is not None and not sent_still_works
    assert client.get("/review/guideline").status_code == 200
    client.get("/review/logout")
    assert _login(client, SENT).status_code == 200           # refused
    again = _login(client, OWN)
    assert again.status_code == 302 and _path(again) == "/review"


def test_the_guideline_link_in_the_email_survives_the_password_step(app, client):
    _add(app)
    first = client.get("/review/guideline")
    signed_in = _login(client, url=first.headers["Location"])
    assert _path(signed_in) == "/review/password"
    assert _next(signed_in) == "/review/guideline"
    saved = _choose(client, url=signed_in.headers["Location"])
    assert saved.status_code == 302 and _path(saved) == "/review/guideline"
    page = client.get("/review/guideline")
    assert page.status_code == 200 and b"Reviewer guideline" in page.data


def test_weak_or_mistyped_choices_are_refused_and_nothing_changes(app, client):
    rid = _add(app)
    _login(client)
    cases = [
        ("too short", None, f"at least {PASSWORD_MIN_LENGTH} characters"),
        (OWN, OWN + " again", "not the same"),
        (SENT, None, "different from the one you were sent"),
    ]
    for new, confirm, message in cases:
        r = _choose(client, new=new, confirm=confirm)
        assert r.status_code == 200, new
        assert message.encode() in r.data, new
        assert _state(app, rid) == (True, None, True), new


def test_the_username_is_not_accepted_as_a_password(app, client):
    rid = _add(app, username="oliveumuhoza")
    _login(client, username="oliveumuhoza")
    r = _choose(client, new="OliveUmuhoza")
    assert r.status_code == 200
    assert b"different from your username" in r.data
    assert _state(app, rid)[0] is True


# --- Changing it later -----------------------------------------------------------

def test_a_reviewer_can_change_it_later_with_the_current_one(app, client):
    rid = _add(app, must_change=False)
    assert _path(_login(client)) == "/review"
    page = client.get("/review/password")
    assert page.status_code == 200
    assert b"Change your password" in page.data
    assert b'name="current_password"' in page.data
    wrong = _choose(client, new="another quiet phrase", current="not my password")
    assert wrong.status_code == 200 and b"current password is not right" in wrong.data
    assert _state(app, rid)[2] is True                      # unchanged
    ok = _choose(client, new="another quiet phrase", current=SENT)
    assert ok.status_code == 302 and _path(ok) == "/review"
    client.get("/review/logout")
    assert _path(_login(client, "another quiet phrase")) == "/review"


def test_the_scoring_pages_link_to_the_password_page(app, client):
    _add(app, must_change=False)
    _login(client)
    score_page = client.get("/review", follow_redirects=True)
    assert b"Change password" in score_page.data and b"/review/password" in score_page.data
    history = client.get("/review/history")
    assert b"Change password" in history.data


def test_the_password_page_needs_a_reviewer(app, client, admin_client):
    assert _path(app.test_client().get("/review/password")) == "/review/login"
    assert admin_client.get("/review/password").status_code == 403


# --- The admin side -----------------------------------------------------------------

def test_an_admin_reset_makes_the_password_temporary_again(app, client, admin_client):
    rid = _add(app, must_change=False)
    r = admin_client.post(f"/admin/reviewer/{rid}/password",
                          data={"new_password": "reset-by-the-editor-99"}, follow_redirects=True)
    assert b"they will choose their own at their next sign-in" in r.data
    must_change, changed_at, _ = _state(app, rid)
    assert must_change is True and changed_at is None
    admin_client.get("/admin/logout")
    again = _login(client, "reset-by-the-editor-99")
    assert again.status_code == 302 and _path(again) == "/review/password"


def test_the_dashboard_shows_whose_password_is_their_own(app, admin_client):
    _add(app, code="OU", username="olive", name="Olive Umuhoza")
    rid = _add(app, code="YV", username="yvette", name="Yvette Nkurunziza", must_change=False)
    with app.app_context():
        r = db.session.get(Reviewer, rid)
        r.password_changed_at = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)
        db.session.commit()
    body = admin_client.get("/admin").data
    assert b"temporary, not changed yet" in body
    assert b"their own since 29 Sep" in body


# --- Login page and rate limit ------------------------------------------------------

def test_the_login_page_explains_the_first_sign_in(client):
    page = client.get("/review/login")
    assert b"First time here?" in page.data


def test_a_rate_limited_reviewer_stays_on_the_reviewer_login_page(app):
    # A route that answers 429 the way the limiter does, under /review.
    app.add_url_rule("/review/_too_many_tries", "too_many_tries", lambda: abort(429))
    r = app.test_client().get("/review/_too_many_tries")
    assert r.status_code == 429
    assert b"Reviewer Login" in r.data and b"Admin Login" not in r.data
    assert b"Too many login attempts" in r.data


# --- The migration ------------------------------------------------------------------

def test_the_migration_flags_existing_accounts_on_an_older_database(tmp_path):
    """Accounts from before this change must choose their own password at the
    next sign-in, because someone else set the one they have."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE reviewers (id INTEGER PRIMARY KEY, code VARCHAR(10), "
                 "display_name VARCHAR(200), username VARCHAR(80), "
                 "password_hash VARCHAR(256), active BOOLEAN NOT NULL DEFAULT 1, "
                 "created_at DATETIME)")
    conn.execute("INSERT INTO reviewers (code, display_name, username, password_hash) "
                 "VALUES ('OU', 'Olive Umuhoza', 'olive', 'x')")
    conn.commit()
    conn.close()

    class OldApp:
        config = {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"}

    migrate_add_reviewer_password_columns(OldApp)
    migrate_add_reviewer_password_columns(OldApp)            # idempotent
    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(reviewers)")}
    flag, changed_at = conn.execute(
        "SELECT must_change_password, password_changed_at FROM reviewers").fetchone()
    conn.close()
    assert {"must_change_password", "password_changed_at"} <= columns
    assert flag == 1 and changed_at is None
