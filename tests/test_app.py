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
        "variants_rw": "Ubugumba",
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
        assert term.variants_rw == "Ubugumba"


def test_variants_are_normalised_and_blank_becomes_none(admin_client, app):
    from models import Term
    _add_term(admin_client, english="Messy variants", variants_rw="  A /  / B  /C/ ")
    _add_term(admin_client, english="No variants", variants_rw="   ")
    with app.app_context():
        assert Term.query.filter_by(english="Messy variants").first().variants_rw == "A / B / C"
        assert Term.query.filter_by(english="No variants").first().variants_rw is None


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
        "variants_rw": "",
    }, follow_redirects=True)
    with app.app_context():
        assert db.session.get(Term, term_id).variants_rw is None


def test_variants_migration_adds_the_column_to_an_older_sqlite_database(tmp_path):
    """A database created before the variant columns existed gains it at boot, rows intact."""
    import sqlite3
    from app import create_app, migrate_add_variant_columns
    from models import db, Term

    db_path = tmp_path / "old.db"
    # Build the schema as it stood before this change: every column except
    # the variant columns, which is what an existing deployment looks like.
    pre_variants = [
        c for c in Term.__table__.columns if c.name != "variants_rw"
    ]
    cols = ", ".join(
        f"{c.name} {'INTEGER PRIMARY KEY' if c.primary_key else 'TEXT'}"
        for c in pre_variants
    )
    conn = sqlite3.connect(db_path)
    conn.execute(f"CREATE TABLE terms ({cols})")
    conn.execute(
        "INSERT INTO terms (english, kinyarwanda, validation_status) "
        "VALUES ('Malaria', 'Malariya', 'unreviewed')"
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
        migrate_add_variant_columns(application)
        present = {r[1] for r in sqlite3.connect(db_path).execute("PRAGMA table_info(terms)")}
        assert "variants_rw" in present
        # A row no recorded decision touches, so it must come through the
        # column migration exactly as it went in.
        malaria = Term.query.filter_by(english="Malaria").first()
        assert malaria is not None
        assert malaria.kinyarwanda == "Malariya"
        assert malaria.variants_rw is None
        assert malaria.variants_en is None
        # Idempotent: a second boot must not raise.
        migrate_add_variant_columns(application)


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
        "variants_rw": "", "category": "", "source": "",
        "example_en": "", "example_rw": "", "etymology": "",
    }, follow_redirects=True)
    with app.app_context():
        term = db.session.get(Term, term_id)
        for field in ("variants_rw", "category", "source",
                      "example_en", "example_rw", "etymology"):
            assert getattr(term, field) is None, field


# ---------------------------------------------------------------------------
# Compound entries — one English headword, one Kinyarwanda rendering
# ---------------------------------------------------------------------------
def test_no_seeded_entry_carries_a_compound_headword_or_rendering(app):
    """The stimulus a reviewer sees must be one term and one rendering."""
    from models import Term
    with app.app_context():
        compound_en = {t.english for t in Term.query.all() if "/" in t.english}
        compound_rw = {t.english for t in Term.query.all() if "/" in t.kinyarwanda}
    assert compound_en == set(), compound_en
    assert compound_rw == set(), compound_rw


def test_the_recorded_decisions_are_applied_to_the_seeded_corpus(app):
    from models import Term
    expected = {
        "Diabetes": ("Diyabete", "Indwara y'igisukari"),
        "Headache": ("Kubabara umutwe", "Kuribwa n'umutwe / Kuribwa umutwe"),
        "Traditional medicine": ("Ubuvuzi gakondo",
                                 "Ubuvuzi bukoresha imiti gakondo / Imiti ikomoka ku bimera"),
        "Infertility": ("Kutabyara", "Ubugumba"),
        "Epilepsy": ("Igicuri", "Indwara y'igicuri"),
    }
    with app.app_context():
        for english, (rw, variants) in expected.items():
            term = Term.query.filter_by(english=english).first()
            assert term is not None, english
            assert term.kinyarwanda == rw, english
            assert term.variants_rw == variants, english
        # English synonyms survive as searchable alternatives
        assert Term.query.filter_by(english="Doctor").first().variants_en == "Physician"
        traditional = Term.query.filter_by(english="Traditional medicine").first()
        assert traditional.variants_en == "Herbal remedies"
        # The etymology explains the headword rendering, not only the variants.
        assert "'Ubuvuzi' = treatment" in traditional.etymology


def test_search_finds_an_entry_by_its_english_synonym(client):
    r = client.get("/api/search?q=physician")
    assert r.status_code == 200
    assert any(t["english"] == "Doctor" for t in r.get_json())


def test_compound_migration_leaves_an_edited_rendering_alone(app):
    """If the Kinyarwanda was changed since the decision, keep the change but
    still resolve the English, so the seed cannot re-insert a duplicate."""
    from app import migrate_split_compound_entries
    from models import Term, db
    with app.app_context():
        term = Term(english="Healthcare assistance / Medical support",
                    kinyarwanda="Something Khris edited later")
        db.session.add(term)
        db.session.commit()
        migrate_split_compound_entries(app)
        moved = Term.query.filter_by(english="Healthcare assistance").all()
        edited = [t for t in moved if t.kinyarwanda == "Something Khris edited later"]
        assert len(edited) == 1
        assert edited[0].variants_en == "Medical support"
        assert Term.query.filter_by(
            english="Healthcare assistance / Medical support").first() is None


def test_compound_migration_is_idempotent(app):
    from app import migrate_split_compound_entries
    from models import Term
    with app.app_context():
        before = Term.query.filter_by(english="Diabetes").first()
        snapshot = (before.kinyarwanda, before.variants_rw)
        migrate_split_compound_entries(app)
        migrate_split_compound_entries(app)
        after = Term.query.filter_by(english="Diabetes").first()
        assert (after.kinyarwanda, after.variants_rw) == snapshot


def test_two_concept_entry_becomes_two_entries(app):
    """Miscarriage and abortion are different events and need separate rows."""
    from models import Term
    with app.app_context():
        assert Term.query.filter_by(english="Miscarriage/abortion").first() is None
        abortion = Term.query.filter_by(english="Abortion").first()
        miscarriage = Term.query.filter_by(english="Miscarriage").first()
        assert abortion is not None and miscarriage is not None
        assert abortion.kinyarwanda == "Gukuramo inda"
        assert miscarriage.kinyarwanda == "Inda yavuyemo"
        # Credit follows the rendering: hers stays hers, his is his.
        assert abortion.contributed_by == "Yvette Nkurunziza"
        assert miscarriage.contributed_by == "Christophe Mumaragishyika"
        assert "Yvette Nkurunziza" in miscarriage.source


def test_two_concept_split_is_idempotent_and_makes_no_duplicate(app):
    from app import migrate_split_two_concept_entries
    from models import Term
    with app.app_context():
        migrate_split_two_concept_entries(app)
        migrate_split_two_concept_entries(app)
        assert Term.query.filter_by(english="Miscarriage").count() == 1
        assert Term.query.filter_by(english="Abortion").count() == 1


# ---------------------------------------------------------------------------
# Contributions from the reviewer demo of 21 September 2026
# ---------------------------------------------------------------------------
def test_variant_contributors_are_credited_in_source(app):
    """Credit follows the rendering, so each variant names who gave it."""
    from models import Term
    with app.app_context():
        anemia = Term.query.filter_by(english="Anemia").first()
        assert anemia.kinyarwanda == "Kubura amaraso"        # headword unchanged
        assert anemia.variants_rw == "Amaraso makeya / Amaraso make"
        assert "Yvette Nkurunziza" in anemia.source
        assert "Virginie Mpuhwezimana" in Term.query.filter_by(english="Infertility").first().source
        assert "Sarah Izabayo" in Term.query.filter_by(english="Epilepsy").first().source


def test_stomach_ache_is_in_the_dictionary_but_never_scored(app):
    """It is a guideline anchor: present for readers, excluded from every queue."""
    from app import REVIEW_EXCLUDED_TERMS
    from models import Term
    with app.app_context():
        term = Term.query.filter_by(english="Stomach ache").first()
        assert term is not None
        assert term.kinyarwanda == "Kubabara mu gifu"
        assert "Kubabara mu kameme" in term.variants_rw
        assert "Yvette Nkurunziza" in term.source
    assert "Stomach ache" in REVIEW_EXCLUDED_TERMS


def test_search_finds_anemia_by_the_form_a_clinician_uses(client):
    r = client.get("/api/search?q=makeya")
    assert any(t["english"] == "Anemia" for t in r.get_json())


# ---------------------------------------------------------------------------
# Show / hide password toggle
# ---------------------------------------------------------------------------
TOGGLE_SCRIPT = b"js/password-toggle.js"


def test_every_page_with_a_password_field_loads_the_toggle(app, admin_client):
    # admin_client shares its session with `client`, so the logged-out pages
    # need a client of their own or they redirect to the dashboard.
    anonymous = app.test_client()
    assert TOGGLE_SCRIPT in anonymous.get("/review/login").data
    assert TOGGLE_SCRIPT in anonymous.get("/admin/login").data
    assert TOGGLE_SCRIPT in admin_client.get("/admin").data


def test_password_fields_are_hidden_without_javascript(app, admin_client):
    """The toggle only enhances; the server still sends real password fields,
    so a browser without JavaScript never shows a password in the clear."""
    anonymous = app.test_client()
    assert b'type="password" id="password"' in anonymous.get("/review/login").data
    assert b'type="password" id="password"' in anonymous.get("/admin/login").data
    # the reset boxes only render once a reviewer account exists
    from models import Reviewer, db
    with app.app_context():
        r = Reviewer(code="OU", username="olive", display_name="Olive Umuhoza")
        r.set_password("long-enough-password")
        db.session.add(r)
        db.session.commit()
    assert b'type="password" id="pw-' in admin_client.get("/admin").data


def test_toggle_script_is_served(client):
    r = client.get("/static/js/password-toggle.js")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # it must never become a submit button, and it must re-hide on submit
    assert 'button.type = "button"' in body
    assert "submit" in body


# ---------------------------------------------------------------------------
# Static asset versioning
# ---------------------------------------------------------------------------
def test_static_urls_carry_a_content_version(client):
    import re
    html = client.get("/review/login").get_data(as_text=True)
    m = re.search(r'href="/static/css/style\.css\?v=([0-9a-f]{10})"', html)
    assert m, "stylesheet URL should carry ?v=<hash>"
    assert re.search(r'src="/static/js/password-toggle\.js\?v=[0-9a-f]{10}"', html)
    # the versioned URL still serves the file
    assert client.get(f"/static/css/style.css?v={m.group(1)}").status_code == 200


def test_static_version_changes_only_when_the_file_changes(app, tmp_path):
    from app import static_file_version
    f = tmp_path / "a.css"
    f.write_text("body{}")
    v1 = static_file_version(str(tmp_path), "a.css")
    assert v1 == static_file_version(str(tmp_path), "a.css")   # stable
    import os, time
    f.write_text("body{color:red}")
    os.utime(f, None)
    v2 = static_file_version(str(tmp_path), "a.css")
    assert v2 != v1                                            # changed content, new version
    assert static_file_version(str(tmp_path), "missing.css") is None
