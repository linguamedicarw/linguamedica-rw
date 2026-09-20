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

# ---------------------------------------------------------------------------
# Variants — alternative Kinyarwanda forms, searchable but never scored
# ---------------------------------------------------------------------------
def _add_term(admin_client, **over):
    data = {
        "english": "Infertility test term",
        "kinyarwanda": "Kutabyara",
        "variants": "Ubugumba",
        "category": "Reproductive Health",
    }
    data.update(over)
    return admin_client.post("/admin/add", data=data, follow_redirects=True)


def test_admin_can_store_variants(admin_client, app):
    from models import Term
    _add_term(admin_client)
    with app.app_context():
        term = Term.query.filter_by(english="Infertility test term").first()
        assert term.kinyarwanda == "Kutabyara"
        assert term.variants == "Ubugumba"


def test_variants_are_normalised_and_blank_becomes_none(admin_client, app):
    from models import Term
    _add_term(admin_client, english="Messy variants", variants="  A /  / B  /C/ ")
    _add_term(admin_client, english="No variants", variants="   ")
    with app.app_context():
        assert Term.query.filter_by(english="Messy variants").first().variants == "A / B / C"
        assert Term.query.filter_by(english="No variants").first().variants is None


def test_search_finds_a_term_by_its_variant(admin_client, client):
    _add_term(admin_client)
    r = client.get("/api/search?q=ubugumba")
    assert r.status_code == 200
    assert any(t["english"] == "Infertility test term" for t in r.get_json())


def test_variants_reach_the_public_page_but_not_the_scored_string(admin_client, client, app):
    from models import Term
    _add_term(admin_client)
    assert b"Ubugumba" in client.get("/").data
    with app.app_context():
        term = Term.query.filter_by(english="Infertility test term").first()
        # The canonical rendering carries no variant, so the string a reviewer
        # is shown and the string recorded in shown_rw stay single.
        assert "/" not in term.kinyarwanda


def test_editing_a_term_can_clear_its_variants(admin_client, app):
    from models import Term, db
    _add_term(admin_client)
    with app.app_context():
        term_id = Term.query.filter_by(english="Infertility test term").first().id
    admin_client.post(f"/admin/edit/{term_id}", data={
        "english": "Infertility test term",
        "kinyarwanda": "Kutabyara",
        "variants": "",
    }, follow_redirects=True)
    with app.app_context():
        assert db.session.get(Term, term_id).variants is None


def test_variants_migration_adds_the_column_to_an_older_sqlite_database(tmp_path):
    """A database created before `variants` existed gains it at boot, rows intact."""
    import sqlite3
    from app import create_app, migrate_add_variants
    from models import db, Term

    db_path = tmp_path / "old.db"
    # Build the schema as it stood before this change: every column except
    # `variants`, which is what an existing deployment actually looks like.
    pre_variants = [
        c for c in Term.__table__.columns if c.name != "variants"
    ]
    cols = ", ".join(
        f"{c.name} {'INTEGER PRIMARY KEY' if c.primary_key else 'TEXT'}"
        for c in pre_variants
    )
    conn = sqlite3.connect(db_path)
    conn.execute(f"CREATE TABLE terms ({cols})")
    conn.execute(
        "INSERT INTO terms (english, kinyarwanda, validation_status) "
        "VALUES ('Anemia', 'Kubura amaraso', 'unreviewed')"
    )
    conn.commit()
    conn.close()

    application = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with application.app_context():
        migrate_add_variants(application)
        present = {r[1] for r in sqlite3.connect(db_path).execute("PRAGMA table_info(terms)")}
        assert "variants" in present
        anemia = Term.query.filter_by(english="Anemia").first()
        assert anemia is not None
        assert anemia.kinyarwanda == "Kubura amaraso"
        assert anemia.variants is None
        # Idempotent: a second boot must not raise.
        migrate_add_variants(application)


def test_edit_form_never_shows_the_word_none_for_an_empty_field(admin_client, app):
    """Jinja prints a None value as "None"; an empty optional field must be blank.

    Without the guard, opening a term with no example and pressing Save stores
    the literal string "None" in that field.
    """
    from models import Term, db
    admin_client.post("/admin/add", data={
        "english": "Bare term", "kinyarwanda": "Ijambo",
    }, follow_redirects=True)
    with app.app_context():
        term_id = Term.query.filter_by(english="Bare term").first().id
    html = admin_client.get(f"/admin/edit/{term_id}").get_data(as_text=True)
    assert ">None<" not in html
    assert 'value="None"' not in html
    # And a round-trip through the form leaves the empty fields empty.
    admin_client.post(f"/admin/edit/{term_id}", data={
        "english": "Bare term", "kinyarwanda": "Ijambo",
        "variants": "", "category": "", "source": "",
        "example_en": "", "example_rw": "", "etymology": "",
    }, follow_redirects=True)
    with app.app_context():
        term = db.session.get(Term, term_id)
        for field in ("variants", "category", "source",
                      "example_en", "example_rw", "etymology"):
            assert getattr(term, field) is None, field
