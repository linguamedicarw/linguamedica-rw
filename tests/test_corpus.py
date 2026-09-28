"""
Annotation corpus v1 tests for LinguaMedica RW.

Covers the frozen corpus file (checksum against its manifest, shape, credit),
the one-time import at startup (unpublished, idempotent, never undoing a later
edit), the public filter (site, API, search, data export), the review phases
(pilot, round, all) and the column migration on an older SQLite database.

Run from the project root:   pytest
"""
import csv
import hashlib
import os
import re
import sqlite3
import sys
from collections import Counter

import pytest

from models import db, Term, TermReview, Reviewer
from app import (
    ANNOTATION_CORPORA,
    COMPOUND_ENTRY_FIXES,
    COMPOUND_ENTRY_SPLITS,
    CONTRIBUTOR_CORRECTIONS,
    REVIEW_EXCLUDED_TERMS,
    REVIEWER_NAMES,
    create_app,
    import_annotation_corpus,
    migrate_add_corpus_columns,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_CSV = os.path.join(ROOT, ANNOTATION_CORPORA["v1"])
MANIFEST = os.path.join(ROOT, "data", "ANNOTATION_CORPUS_v1.md")
DOMAINS = {"Diagnostics": 74, "Infectious Disease": 51, "Obstetrics": 34, "Pharmacology": 30}
EDITOR = REVIEWER_NAMES["CM"]


def _rows():
    with open(CORPUS_CSV, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _reviewer(app, code, username):
    with app.app_context():
        r = Reviewer(code=code, display_name=REVIEWER_NAMES[code], username=username,
                     must_change_password=False)
        r.set_password(f"{username}-pass")
        db.session.add(r)
        db.session.commit()


def _login(client, username):
    return client.post("/review/login",
                       data={"username": username, "password": f"{username}-pass"})


# --- The frozen file ---------------------------------------------------------

def test_corpus_file_matches_the_checksum_in_its_manifest():
    """The freeze: any edit to the file after it was recorded fails here."""
    with open(MANIFEST, encoding="utf-8") as fh:
        recorded = re.search(r"SHA-256 \| `([0-9a-f]{64})`", fh.read()).group(1)
    with open(CORPUS_CSV, "rb") as fh:
        actual = hashlib.sha256(fh.read()).hexdigest()
    assert actual == recorded


def test_the_test_set_rule_names_the_frozen_corpus():
    """The evaluation rule was fixed against this exact file; if the corpus is
    ever rebuilt, the rule has to be looked at again, not left pointing at an
    older version."""
    with open(os.path.join(ROOT, "data", "EVALUATION_TEST_SET_v1.md"), encoding="utf-8") as fh:
        rule = fh.read()
    with open(CORPUS_CSV, "rb") as fh:
        actual = hashlib.sha256(fh.read()).hexdigest()
    assert actual in rule


def test_corpus_file_has_the_agreed_shape():
    rows = _rows()
    assert len(rows) == 189
    assert Counter(r["domain"] for r in rows) == DOMAINS
    assert len({r["key"] for r in rows}) == 189
    assert len({r["english"].casefold() for r in rows}) == 189
    for r in rows:
        # One headword and one rendering: the stimulus is never a compound.
        assert "/" not in r["english"] and "/" not in r["kinyarwanda"], r["key"]
        assert r["english"].strip() == r["english"] and r["english"], r["key"]
        assert r["kinyarwanda"].strip() == r["kinyarwanda"] and r["kinyarwanda"], r["key"]
        assert r["pilot"] in ("yes", "no"), r["key"]
        assert r["provenance"], r["key"]


def test_credit_follows_the_rendering():
    rows = _rows()
    assert Counter(r["contributor"] for r in rows) == {
        "Sarah Izabayo": 93, "Virginie Mpuhwezimana": 88, EDITOR: 8}
    for r in rows:
        if r["change"] in ("Correction", "Definition to headword"):
            assert r["contributor"] == EDITOR, r["key"]
            # The collector is still named, as the one who recorded the term.
            assert r["provenance"].startswith("Recorded by "), r["key"]
        else:
            assert r["contributor"] != EDITOR, r["key"]
            assert r["provenance"].startswith(f"Recorded by {r['contributor']}"), r["key"]


def test_pilot_is_six_per_domain_and_every_reviewer_can_score_it():
    rows = _rows()
    pilot = [r for r in rows if r["pilot"] == "yes"]
    assert Counter(r["domain"] for r in pilot) == {d: 6 for d in DOMAINS}
    reviewers = set(REVIEWER_NAMES.values())
    assert not [r["key"] for r in pilot if r["contributor"] in reviewers]


def test_pilot_draw_follows_the_published_rule():
    """Anyone can re-run the draw from the manifest and get the same 24."""
    rows = _rows()
    reviewers = set(REVIEWER_NAMES.values())
    expected = set()
    for domain in DOMAINS:
        eligible = sorted(
            (r["key"] for r in rows
             if r["domain"] == domain and r["contributor"] not in reviewers),
            key=lambda k: hashlib.sha256(f"linguamedica-pilot-v1:{k}".encode()).hexdigest())
        expected.update(eligible[:6])
    assert {r["key"] for r in rows if r["pilot"] == "yes"} == expected


def test_corpus_headwords_never_collide_with_the_dictionary_or_its_migrations():
    """Several startup migrations find a term by its English. A corpus headword
    equal to one of those keys, a starter term or a guideline anchor could be
    picked up by the wrong rule, so none may exist."""
    import ast
    with open(os.path.join(ROOT, "seed_data.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    starter = next(ast.literal_eval(n.value) for n in tree.body
                   if isinstance(n, ast.Assign)
                   and getattr(n.targets[0], "id", None) == "STARTER_TERMS")
    taken = {t["english"].casefold() for t in starter}
    taken |= {k.casefold() for k in COMPOUND_ENTRY_FIXES}
    taken |= {f["english"].casefold() for f in COMPOUND_ENTRY_FIXES.values() if "english" in f}
    taken |= {k.casefold() for k in COMPOUND_ENTRY_SPLITS}
    taken |= {p["create"]["english"].casefold() for p in COMPOUND_ENTRY_SPLITS.values()}
    taken |= {k.casefold() for k in CONTRIBUTOR_CORRECTIONS}
    taken |= {k.casefold() for k in REVIEW_EXCLUDED_TERMS}
    clashes = [r["english"] for r in _rows() if r["english"].casefold() in taken]
    assert clashes == []


# --- The import --------------------------------------------------------------

def test_corpus_is_loaded_unpublished_at_startup(app):
    with app.app_context():
        terms = Term.query.filter_by(corpus_version="v1").all()
        assert len(terms) == 189
        assert all(t.published is False for t in terms)
        assert sum(1 for t in terms if t.pilot) == 24
        assert Counter(t.domain for t in terms) == DOMAINS
        assert all(t.validation_status == "unreviewed" for t in terms)

        dbc = Term.query.filter_by(corpus_key="S237").one()
        assert dbc.english == "Differential blood count"
        assert dbc.contributed_by == EDITOR
        assert dbc.variants_rw.count(" / ") == 4          # five variants, app convention
        assert len(dbc.variants_rw) > 300                 # why the column is TEXT
        assert "Sarah Izabayo" in dbc.source

        placenta = Term.query.filter_by(corpus_key="V43").one()
        assert placenta.kinyarwanda == "Nyababyeyi"
        assert placenta.variants_rw == "Ingobyi"
        assert placenta.category == "Anatomy" and placenta.domain == "Obstetrics"
        assert placenta.contributed_by == "Virginie Mpuhwezimana"
        assert placenta.corpus_note                        # the editor's note travels
        assert placenta.etymology is None                  # but not into the public field


def test_import_loads_once_and_never_undoes_a_later_edit(app):
    with app.app_context():
        assert import_annotation_corpus(app, "v1") == 0
        assert Term.query.filter_by(corpus_version="v1").count() == 189

        # An adjudicated rendering and a deliberately removed term both survive
        # the next boot: the file is the frozen record, the table the working copy.
        edited = Term.query.filter_by(corpus_key="S84").one()
        edited.kinyarwanda = "Edited after the round"
        db.session.delete(Term.query.filter_by(corpus_key="S228").one())
        db.session.commit()
        assert import_annotation_corpus(app, "v1") == 0
        assert Term.query.filter_by(corpus_key="S84").one().kinyarwanda == "Edited after the round"
        assert Term.query.filter_by(corpus_key="S228").first() is None
        assert Term.query.filter_by(corpus_version="v1").count() == 188


def test_a_second_boot_on_the_same_database_adds_nothing(app):
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    again = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": uri,
                        "WTF_CSRF_ENABLED": False, "RATELIMIT_ENABLED": False})
    with again.app_context():
        assert Term.query.filter_by(corpus_version="v1").count() == 189
        assert Term.query.filter(Term.corpus_version.is_(None)).count() == \
            Term.query.filter(Term.published.is_(True)).count()


def test_admin_edit_keeps_a_corpus_term_in_the_corpus_and_unpublished(admin_client, app):
    with app.app_context():
        term = Term.query.filter_by(corpus_key="S146").one()
        term_id, was_pilot = term.id, term.pilot
    admin_client.post(f"/admin/edit/{term_id}", data={
        "english": "Pharmacokinetics", "kinyarwanda": "Urusobe rw'uko umubiri uyobokwa n'imiti",
        "variants_rw": "", "variants_en": "", "category": "Pharmacology",
        "source": "unchanged in spirit", "example_en": "", "example_rw": "", "etymology": "",
    }, follow_redirects=True)
    with app.app_context():
        term = db.session.get(Term, term_id)
        assert term.published is False
        assert term.corpus_version == "v1" and term.corpus_key == "S146"
        assert term.pilot == was_pilot and term.domain == "Pharmacology"


# --- The public filter -------------------------------------------------------

def test_corpus_terms_stay_off_the_public_site_and_api(client):
    home = client.get("/").get_data(as_text=True)
    assert "Differential blood count" not in home
    assert "Njyamitsi" not in home
    assert "Hypertension" in home                          # the dictionary itself is there

    listed = {t["english"] for t in client.get("/api/terms").get_json()}
    assert "Intravenous" not in listed and "Placenta" not in listed
    assert "Hypertension" in listed
    assert all(t["published"] for t in client.get("/api/terms").get_json())

    assert client.get("/api/search?q=njyamitsi").get_json() == []
    assert client.get("/api/search?q=ingobyi").get_json() == []   # variants too
    assert any(t["english"] == "Hypertension"
               for t in client.get("/api/search?q=hypertension").get_json())


def test_homepage_counts_the_terms_under_review_without_showing_them(client):
    home = client.get("/").get_data(as_text=True)
    assert "+ 189 new terms under independent review, results in November" in home
    assert "Njyamitsi" not in home and "Intravenous" not in home


def test_homepage_line_disappears_when_nothing_is_under_review(app, client):
    with app.app_context():
        for term in Term.query.filter_by(corpus_version="v1"):
            term.published = True
        db.session.commit()
    home = client.get("/").get_data(as_text=True)
    assert "under independent review" not in home


def test_homepage_line_can_drop_the_month(app, client):
    app.config["REVIEW_RESULTS_EXPECTED"] = ""
    home = client.get("/").get_data(as_text=True)
    assert "+ 189 new terms under independent review</p>" in home
    assert "results in" not in home


def test_public_payload_never_carries_the_editor_note(client):
    for t in client.get("/api/terms").get_json():
        assert "corpus_note" not in t and "corpus_key" not in t and "pilot" not in t


def test_the_data_export_writes_published_terms_only(app, tmp_path, monkeypatch):
    """data/terms.json is the store the RAG build reads: no unreviewed corpus term."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    try:
        import export_terms
    finally:
        sys.path.pop(0)
    monkeypatch.setenv("DATABASE_URL", app.config["SQLALCHEMY_DATABASE_URI"])
    # Write into a temporary folder, never over the repo's own data files.
    monkeypatch.setattr(export_terms, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(export_terms, "DATA_DIR", tmp_path)
    monkeypatch.setattr(export_terms, "JSON_PATH", tmp_path / "terms.json")
    monkeypatch.setattr(export_terms, "CSV_PATH", tmp_path / "terms.csv")
    export_terms.main()
    import json
    payload = json.loads((tmp_path / "terms.json").read_text(encoding="utf-8"))
    exported = {t["english"] for t in payload["terms"]}
    with app.app_context():
        public = {t.english for t in Term.query.filter(Term.published.is_(True))}
        corpus = {t.english for t in Term.query.filter_by(corpus_version="v1")}
    assert exported == public
    assert not exported & corpus


# --- The review phases -------------------------------------------------------

def test_pilot_phase_serves_only_the_pilot(app, client):
    _reviewer(app, "OU", "olive")
    _login(client, "olive")
    with app.app_context():
        pilot_ids = {t.id for t in Term.query.filter_by(corpus_version="v1", pilot=True)}
        other_corpus = Term.query.filter_by(corpus_version="v1", pilot=False).first().id
        public = Term.query.filter_by(english="Hypertension").one().id
    first = client.get("/review")
    assert int(first.headers["Location"].rstrip("/").split("/")[-1]) in pilot_ids
    page = client.get(first.headers["Location"])
    assert b"scored 0 of 24" in page.data
    assert client.get(f"/review/term/{other_corpus}").status_code == 403
    assert client.get(f"/review/term/{public}").status_code == 403
    assert client.post(f"/review/term/{other_corpus}/score",
                       data={"score": "4"}).status_code == 403
    with app.app_context():
        assert TermReview.query.count() == 0


def test_round_phase_serves_the_corpus_minus_the_reviewers_own_terms(app, client):
    app.config["REVIEW_PHASE"] = "round"
    _reviewer(app, "CM", "khris")
    _login(client, "khris")
    with app.app_context():
        own = Term.query.filter_by(corpus_key="V183").one().id      # Intravenous, his correction
        theirs = Term.query.filter_by(corpus_key="S84").one().id     # Sarah's, not in the pilot
        public = Term.query.filter_by(english="Hypertension").one().id
    page = client.get(f"/review/term/{theirs}")
    assert page.status_code == 200
    assert b"scored 0 of 181" in page.data                           # 189 minus his 8
    assert client.get(f"/review/term/{own}").status_code == 403
    assert client.get(f"/review/term/{public}").status_code == 403


def test_pilot_scores_stay_counted_when_the_round_opens(app, client):
    _reviewer(app, "OU", "olive")
    _login(client, "olive")
    with app.app_context():
        pilot_term = Term.query.filter_by(corpus_version="v1", pilot=True).first().id
    client.post(f"/review/term/{pilot_term}/score", data={"score": "4"})
    app.config["REVIEW_PHASE"] = "round"
    nxt = client.get("/review").headers["Location"]
    assert not nxt.endswith(f"/review/term/{pilot_term}")
    assert b"scored 1 of 189" in client.get(nxt).data


def test_score_page_for_a_real_corpus_term_hides_credit_and_notes(app, client):
    _reviewer(app, "OU", "olive")
    _login(client, "olive")
    with app.app_context():
        term = Term.query.filter_by(corpus_key="S146").one()        # a pilot term with a note
        term_id, note = term.id, term.corpus_note
    page = client.get(f"/review/term/{term_id}").get_data(as_text=True)
    assert "Pharmacokinetics" in page
    assert "Sarah Izabayo" not in page
    assert "Recorded by" not in page
    assert note and note[:30] not in page


def test_all_phase_serves_every_term(app, client):
    app.config["REVIEW_PHASE"] = "all"
    _reviewer(app, "OU", "olive")
    _login(client, "olive")
    with app.app_context():
        public = Term.query.filter_by(english="Hypertension").one().id
    assert client.get(f"/review/term/{public}").status_code == 200


def test_an_unknown_phase_falls_back_to_the_pilot(tmp_path):
    application = create_app({
        "TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'p.db'}",
        "WTF_CSRF_ENABLED": False, "RATELIMIT_ENABLED": False,
        "REVIEW_PHASE": "rounds",
    })
    assert application.config["REVIEW_PHASE"] == "pilot"


def test_admin_dashboard_marks_corpus_terms_and_names_the_phase(admin_client):
    body = admin_client.get("/admin").get_data(as_text=True)
    assert "Review phase: <strong>pilot</strong>" in body
    assert "not public · v1 · pilot" in body
    assert "+ 189 not public yet (annotation corpus)" in body


# --- The column migration ----------------------------------------------------

def test_corpus_migration_upgrades_an_older_sqlite_database(tmp_path):
    """A database from before this change gains the columns at boot, keeps its
    rows public, and gets the corpus loaded beside them."""
    db_path = tmp_path / "old.db"
    new_columns = {"published", "corpus_version", "corpus_key", "pilot",
                   "domain", "corpus_note"}
    old = [c for c in Term.__table__.columns if c.name not in new_columns]
    cols = ", ".join(
        f"{c.name} {'INTEGER PRIMARY KEY' if c.primary_key else 'TEXT'}" for c in old)
    conn = sqlite3.connect(db_path)
    conn.execute(f"CREATE TABLE terms ({cols})")
    conn.execute("INSERT INTO terms (english, kinyarwanda, validation_status) "
                 "VALUES ('Hypertension', 'Umuvuduko w''amaraso', 'unreviewed')")
    conn.commit()
    conn.close()

    application = create_app({
        "TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        "WTF_CSRF_ENABLED": False, "RATELIMIT_ENABLED": False,
    })
    with application.app_context():
        present = {r[1] for r in sqlite3.connect(db_path).execute("PRAGMA table_info(terms)")}
        assert new_columns <= present
        old_row = Term.query.filter_by(english="Hypertension").one()
        assert old_row.published is True and old_row.corpus_version is None
        assert Term.query.filter_by(corpus_version="v1").count() == 189
        migrate_add_corpus_columns(application)                     # idempotent
        indexes = {r[1] for r in sqlite3.connect(db_path).execute("PRAGMA index_list(terms)")}
        assert "ix_terms_corpus_key" in indexes


def test_corpus_key_is_unique(app):
    from sqlalchemy.exc import IntegrityError
    with app.app_context():
        db.session.add(Term(english="Copy", kinyarwanda="Kopi", corpus_key="S84"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
