"""
Smoke + regression tests for LinguaMedica RW.

Run from the project root:   pytest

Covers public pages, search, the suggestion flow, and admin auth, plus
regression guards for the open-redirect (#5) and stored-XSS (#29) fixes.
"""
import os

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "testadmin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "testpass")


# --- Public pages & search -------------------------------------------------

def test_homepage_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"LinguaMedica" in r.data


def test_api_terms_returns_seed_data(client):
    r = client.get("/api/terms")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list) and len(data) > 0


def test_api_search_finds_a_known_term(client):
    # Pull a real seeded term, then search for it — robust to the seed contents.
    sample = client.get("/api/terms").get_json()[0]["english"]
    r = client.get("/api/search", query_string={"q": sample})
    assert r.status_code == 200
    assert any(t["english"] == sample for t in r.get_json())


# --- Suggestion flow -------------------------------------------------------

def test_suggestion_is_persisted(client, app):
    r = client.post("/suggest", data={
        "english_word": "Tachycardia",
        "context": "from a cardiology note",
    })
    assert r.status_code in (302, 303)
    with app.app_context():
        from models import Suggestion
        s = Suggestion.query.filter_by(english_word="Tachycardia").first()
        assert s is not None
        assert s.context == "from a cardiology note"
        assert s.resolved is False


# --- Admin authentication --------------------------------------------------

def test_dashboard_requires_login(client):
    r = client.get("/admin")
    assert r.status_code == 302
    assert "/admin/login" in r.headers["Location"]


def test_admin_login_succeeds(client):
    r = client.post("/admin/login", data={
        "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD,
    })
    assert r.status_code == 302
    assert client.get("/admin").status_code == 200


def test_admin_login_rejects_wrong_password(client):
    r = client.post("/admin/login", data={
        "username": ADMIN_USERNAME, "password": "definitely-wrong",
    })
    assert r.status_code == 200                      # re-renders the login page
    assert client.get("/admin").status_code == 302   # still locked out


# --- Regression guards for the security fixes ------------------------------

def test_login_ignores_offsite_redirect(client):
    """#5: a hostile ?next= must never redirect off-site."""
    r = client.post(
        "/admin/login?next=https://evil.example.com/steal",
        data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert r.status_code == 302
    assert "evil.example.com" not in r.headers["Location"]


def test_dashboard_confirm_dialog_is_not_injectable(admin_client):
    """#29: a crafted suggestion name must not reach an inline JS handler."""
    payload = 'pwn");alert(1)//'
    admin_client.post("/suggest", data={"english_word": payload})
    html = admin_client.get("/admin").get_data(as_text=True)
    # The Resolve confirm is now a static string (no term interpolation).
    assert "Mark this suggestion as resolved?" in html
    # The payload must not appear inside any onclick handler.
    for chunk in html.split('onclick="')[1:]:
        onclick_value = chunk.split('"')[0]
        assert "alert(1)" not in onclick_value