"""
Medical Dictionary — Main Application

This is the heart of the app. It:
1. Creates and configures the Flask app
2. Sets up authentication (so only you can admin)
3. Defines all the routes (URLs) users can visit
4. Handles search, suggestions, and admin operations

Security features:
- CSRF protection on all forms (Flask-WTF)
- Rate limiting on login route (Flask-Limiter)
- Content-Security-Policy header
- All credentials from environment variables
"""

import os
import csv
import hashlib
import sqlite3
from datetime import datetime, timezone, timedelta
from functools import wraps
from urllib.parse import urlparse
from markupsafe import Markup
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, abort, session
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import Config
from models import db, Term, TermReview, Suggestion, SearchLog, Admin, Reviewer
from sqlalchemy import func


# ---------------------------------------------------------------------------
# Helper — validate post-login redirect targets (prevents open redirects)
# ---------------------------------------------------------------------------
def is_safe_redirect_target(target):
    """Only allow redirects to local, relative paths — never off-site."""
    if not target:
        return False
    parsed = urlparse(target)
    # Must be a relative path: no scheme, no host, single leading slash
    return (
        not parsed.scheme
        and not parsed.netloc
        and target.startswith("/")
        and not target.startswith("//")
    )


# ---------------------------------------------------------------------------
# Static asset versioning — a changed stylesheet must never be served stale
# ---------------------------------------------------------------------------
_STATIC_VERSIONS = {}


def static_file_version(static_folder, filename):
    """A short hash of a static file's content, recomputed when the file
    changes on disk. Appended to the file's URL as ?v=..., so a browser that
    cached the old stylesheet fetches the new one the moment it changes,
    while an unchanged file stays cached. Returns None if the file is missing.
    """
    path = os.path.join(static_folder, filename)
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return None
    cached = _STATIC_VERSIONS.get(path)
    if cached is None or cached[0] != mtime:
        with open(path, "rb") as fh:
            cached = (mtime, hashlib.sha1(fh.read()).hexdigest()[:10])
        _STATIC_VERSIONS[path] = cached
    return cached[1]


# ---------------------------------------------------------------------------
# Database Migration — Add provenance columns to existing terms table
# ---------------------------------------------------------------------------
def _pg_add_columns_if_missing(table, columns):
    """Idempotently add columns on Postgres via ADD COLUMN IF NOT EXISTS.

    A safe no-op when the columns already exist. Wrapped in try/except so a
    hiccup never blocks startup — the app still boots on the existing schema.
    """
    from sqlalchemy import text
    try:
        with db.engine.begin() as conn:
            for name, ddl in columns:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}"
                ))
    except Exception as exc:
        print(f"[migrate] Postgres column check skipped for {table}: {exc}")


def migrate_add_provenance_columns(app):
    """Add contributed_by, source, and date_added columns if they don't exist."""
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('postgresql'):
        _pg_add_columns_if_missing("terms", [
            ("contributed_by", "VARCHAR(200) DEFAULT 'Christophe Mumaragishyika'"),
            ("source", "VARCHAR(300)"),
            ("date_added", "TIMESTAMP"),
        ])
        return
    if not db_uri.startswith('sqlite'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(terms)")
    existing = {row[1] for row in cursor.fetchall()}
    if 'contributed_by' not in existing:
        cursor.execute(
            "ALTER TABLE terms ADD COLUMN contributed_by VARCHAR(200) "
            "DEFAULT 'Christophe Mumaragishyika'"
        )
    if 'source' not in existing:
        cursor.execute("ALTER TABLE terms ADD COLUMN source VARCHAR(300)")
    if 'date_added' not in existing:
        cursor.execute("ALTER TABLE terms ADD COLUMN date_added DATETIME")
    conn.commit()
    conn.close()


def migrate_add_suggestion_resolved(app):
    """Add resolved and resolved_at columns to suggestions if they don't exist."""
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('postgresql'):
        _pg_add_columns_if_missing("suggestions", [
            ("resolved", "BOOLEAN DEFAULT FALSE"),
            ("resolved_at", "TIMESTAMP"),
        ])
        return
    if not db_uri.startswith('sqlite'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(suggestions)")
    existing = {row[1] for row in cursor.fetchall()}
    if 'resolved' not in existing:
        cursor.execute(
            "ALTER TABLE suggestions ADD COLUMN resolved BOOLEAN DEFAULT 0"
        )
    if 'resolved_at' not in existing:
        cursor.execute(
            "ALTER TABLE suggestions ADD COLUMN resolved_at DATETIME"
        )
    conn.commit()
    conn.close()


# Known contributor corrections. Three early community-suggested terms were
# seeded with the default author in `contributed_by`; the true contributor was
# only recorded in each row's `source`. This restores correct attribution.
# Guarded so a later deliberate edit is never overwritten (see function below).
DEFAULT_CONTRIBUTOR = "Christophe Mumaragishyika"
CONTRIBUTOR_CORRECTIONS = {
    "Palliative care": "Aimable Uwimana (Mugenzi)",
    "Interview (research methodology)": "Benithe Himbazwa",
    "Health management": "Benithe Himbazwa",
}


def migrate_add_variant_columns(app):
    """Add terms.variants_rw and terms.variants_en if they don't exist.

    Both hold alternative forms for the same entry, separated by " / ":
    other Kinyarwanda renderings, and other English names. They are
    searchable but never part of the stimulus, so a reviewer always sees one
    English headword and one Kinyarwanda rendering and an adequacy score
    means the same thing on every row of the corpus. Idempotent and safe on
    every startup.
    """
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('postgresql'):
        _pg_add_columns_if_missing("terms", [
            ("variants_rw", "VARCHAR(300)"),
            ("variants_en", "VARCHAR(300)"),
        ])
        return
    if not db_uri.startswith('sqlite'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(terms)")
    existing = {row[1] for row in cursor.fetchall()}
    if 'variants_rw' not in existing:
        cursor.execute("ALTER TABLE terms ADD COLUMN variants_rw VARCHAR(300)")
    if 'variants_en' not in existing:
        cursor.execute("ALTER TABLE terms ADD COLUMN variants_en VARCHAR(300)")
    conn.commit()
    conn.close()


# Compound entries split into a single headword plus searchable variants.
# Every choice below is Khris's, made on 19 September 2026 against the rule
# recorded with the corpus: keep the rendering that carries the concept most
# concretely for a native speaker; where two are equally concrete, keep the
# shorter; length is the tiebreaker, never the test.
#
# Keyed by the entry's English string BEFORE the fix. `expect_rw` guards each
# row: if the Kinyarwanda no longer matches, the entry has been edited since
# and the migration leaves it alone rather than overwriting a later decision.
COMPOUND_ENTRY_FIXES = {
    # --- one Kinyarwanda rendering chosen, the rest kept as variants ---
    "Diabetes": {
        "expect_rw": "Diyabete / Indwara y'igisukari",
        "kinyarwanda": "Diyabete", "variants_rw": "Indwara y'igisukari"},
    "Pregnancy": {
        "expect_rw": "Gutwita / Inda",
        "kinyarwanda": "Gutwita", "variants_rw": "Inda"},
    "Asthma": {
        "expect_rw": "Gusemeka / Isemeka",
        "kinyarwanda": "Gusemeka", "variants_rw": "Isemeka"},
    "Compensation": {
        "expect_rw": "Impozamarira / Inshumbusho / Igihembo",
        "kinyarwanda": "Impozamarira", "variants_rw": "Inshumbusho / Igihembo"},
    "Barriers to care": {
        "expect_rw": "Imbogamizi zibangamira kwitabwaho / Imbogamizi zibuza kuvurwa",
        "kinyarwanda": "Imbogamizi zibuza kuvurwa",
        "variants_rw": "Imbogamizi zibangamira kwitabwaho"},
    "Headache": {
        "expect_rw": "Kuribwa n'umutwe / Kuribwa umutwe / Kubabara umutwe",
        "kinyarwanda": "Kubabara umutwe",
        "variants_rw": "Kuribwa n'umutwe / Kuribwa umutwe"},
    "Swelling": {
        "expect_rw": "Kubyimba / Kubyimbagatana",
        "kinyarwanda": "Kubyimba", "variants_rw": "Kubyimbagatana"},
    "Palliative care": {
        "expect_rw": "Ubuvuzi mpozaburibwe / Ubufasha nyunganiramibereho",
        "kinyarwanda": "Ubufasha nyunganiramibereho",
        "variants_rw": "Ubuvuzi mpozaburibwe"},

    "Shortness of breath": {
        "expect_rw": "Guhera umwuka / Kubura umwuka",
        "kinyarwanda": "Guhera umwuka", "variants_rw": "Kubura umwuka"},

    # --- a variant added to an entry that was already single ---
    # Credit follows the rendering: each variant names the person who gave it.
    "Infertility": {
        "expect_rw": "Kutabyara", "variants_rw": "Ubugumba",
        "source": ("Community suggestion — Yvette Nkurunziza (April 2026); "
                   "variant 'Ubugumba' from Virginie Mpuhwezimana, "
                   "August 2026 collection")},
    "Epilepsy": {
        "expect_rw": "Igicuri", "variants_rw": "Indwara y'igicuri",
        "source": ("Community suggestion — Yvette Nkurunziza (April 2026); "
                   "variant 'Indwara y'igicuri' from Sarah Izabayo, "
                   "August 2026 collection")},
    # Added during the reviewer demo of 21 September 2026. The headword stays
    # as it was; Yvette contributed a further form clinicians use.
    "Anemia": {
        "expect_rw": "Kubura amaraso",
        "variants_rw": "Amaraso makeya / Amaraso make",
        "source": ("Original starter terms; variant 'Amaraso makeya / "
                   "Amaraso make' added by Yvette Nkurunziza, physician, "
                   "21 September 2026")},

    # --- one English headword chosen, the other kept as a searchable synonym ---
    "Health behavior / Lifestyle conduct": {
        "english": "Health behavior", "variants_en": "Lifestyle conduct"},
    "Clinical instructions / Doctor's recommendations": {
        "english": "Clinical instructions", "variants_en": "Doctor's recommendations"},
    "Health advice / Medical counseling": {
        "english": "Health advice", "variants_en": "Medical counseling"},
    "Information dissemination / Health sensitization": {
        "english": "Information dissemination", "variants_en": "Health sensitization"},
    "Health follow-up / Medical monitoring": {
        "english": "Health follow-up", "variants_en": "Medical monitoring"},
    "Doctor / Physician": {
        "english": "Doctor", "variants_en": "Physician"},
    "Division / Department": {
        "english": "Division", "variants_en": "Department"},
    "To fight/combat a disease": {
        "english": "To fight a disease", "variants_en": "To combat a disease"},
    "Partners in Health / Inshuti Mu Buzima (PIH/IMB)": {
        "english": "Partners in Health (PIH)",
        "variants_en": "Inshuti Mu Buzima (IMB)"},

    # --- compound on both sides, resolved to one entry on each ---
    "Healthcare assistance / Medical support": {
        "expect_rw": "Ubwunganizi bwita ku buzima / Ubwunganizi mu kuvurwa",
        "english": "Healthcare assistance", "variants_en": "Medical support",
        "kinyarwanda": "Ubwunganizi mu kuvurwa",
        "variants_rw": "Ubwunganizi bwita ku buzima"},
    # Sandrine's accepted conciseness suggestion lands here too: the canonical
    # rendering becomes the shorter form, and the longer one it replaces is
    # kept as a variant rather than lost.
    "Herbal remedies / Traditional medicine": {
        "expect_rw": "Imiti ikomoka ku bimera / Ubuvuzi bukoresha imiti gakondo",
        "english": "Traditional medicine", "variants_en": "Herbal remedies",
        "kinyarwanda": "Ubuvuzi gakondo",
        "variants_rw": "Ubuvuzi bukoresha imiti gakondo / Imiti ikomoka ku bimera",
        # The old etymology explained only the two forms that are now variants,
        # so it is re-pointed at the headword using the same glosses.
        "etymology": (
            "'Ubuvuzi' = treatment. 'Gakondo' = traditional, reflecting that traditional medication was based on herbal remedies. The variants are 'Ubuvuzi bukoresha imiti gakondo' = treatment using traditional medicine, and 'Imiti ikomoka ku bimera' = medicine that comes from plants.")},
}


def migrate_split_compound_entries(app):
    """Resolve compound entries into one headword plus searchable variants.

    Each entry is matched on its pre-fix English string and, where given, on
    its exact Kinyarwanda. A row that no longer matches has been edited since
    these decisions were made, so it is skipped and reported rather than
    overwritten. Idempotent: once an entry is fixed its English no longer
    matches the key, so later boots do nothing.
    """
    try:
        changed, skipped = 0, []
        for key, fix in COMPOUND_ENTRY_FIXES.items():
            term = Term.query.filter_by(english=key).first()
            if term is None:
                continue
            # Already in the intended state: nothing to do, and nothing to
            # report. Entries whose English headword does not change keep
            # matching this key forever, so without this check every later
            # boot would re-apply the same values and warn about a guard
            # mismatch that is really just the finished result.
            wanted = {f: fix[f] for f in
                      ("english", "kinyarwanda", "variants_rw",
                       "variants_en", "etymology", "source")
                      if f in fix}
            if all(getattr(term, f) == v for f, v in wanted.items()):
                continue
            # Split already done: the chosen headword is in place, and later
            # decisions (EDITOR_CORRECTIONS) have since added variants or a
            # note. Leave it quietly rather than warn on every boot.
            if ("kinyarwanda" in fix and term.kinyarwanda == fix["kinyarwanda"]
                    and term.english == fix.get("english", key)):
                continue

            # The Kinyarwanda guard is advisory, and deliberately does not
            # abort the whole row. If the rendering has been edited since
            # these decisions were made, that edit is kept and only the
            # English side is resolved. Skipping the English rename instead
            # would leave a compound headword in the database that the seed
            # then re-inserts under its new name, creating a duplicate.
            expect_rw = fix.get("expect_rw")
            rw_is_untouched = expect_rw is None or term.kinyarwanda == expect_rw
            if not rw_is_untouched:
                skipped.append(key)
            fields = ["english", "variants_en"]
            if rw_is_untouched:
                fields += ["kinyarwanda", "variants_rw", "etymology", "source"]
            for field in fields:
                if field in fix:
                    setattr(term, field, fix[field])
            changed += 1
        if changed:
            db.session.commit()
            print(f"[migrate] applied recorded editorial decisions to {changed} entr(ies)")
        for key in skipped:
            print(f"[migrate] '{key}': Kinyarwanda edited since the decision "
                  f"was recorded, so its rendering was left as it is")
    except Exception as exc:
        db.session.rollback()
        print(f"[migrate] compound entry split skipped: {exc}")



# One entry that was two concepts sharing a row. Khris separated them on
# 19 September 2026: *gukuramo* is to remove, *kuvamo* is to exit or leave, so
# one names a pregnancy deliberately ended and the other one that ended of
# itself. Conflating them is a clinically consequential error in a dictionary
# meant to ground a translation system, so they become two entries.
#
# The rendering Yvette Nkurunziza originally submitted stays with her under the
# entry it actually names. The second rendering is Khris's own, so it is
# credited to him with her entry named in its provenance.
SPLIT_ETYMOLOGY = (
    "'Gukuramo' = to remove; 'kuvamo' = to exit or leave. Both describe a "
    "pregnancy that has ended, but 'gukuramo inda' names one deliberately "
    "ended, while 'inda yavuyemo' names one that ended of itself."
)
COMPOUND_ENTRY_SPLITS = {
    "Miscarriage/abortion": {
        "expect_rw": "Gukuramo inda",
        "keep": {"english": "Abortion", "etymology": SPLIT_ETYMOLOGY},
        "create": {
            "english": "Miscarriage",
            "kinyarwanda": "Inda yavuyemo",
            "etymology": SPLIT_ETYMOLOGY,
            "category": "Reproductive Health",
            "contributed_by": "Christophe Mumaragishyika",
            "source": ("Separated from Yvette Nkurunziza's 'Miscarriage/abortion' "
                       "entry, editor's rendering, September 2026"),
        },
    },
}


def migrate_split_two_concept_entries(app):
    """Separate an entry that was carrying two distinct concepts into two.

    The surviving row keeps its id, provenance and review history; the second
    concept becomes a new entry. Guarded twice: the original must still hold
    the expected rendering, and the new headword is only created if nothing
    already uses it. Idempotent on every startup.
    """
    try:
        made = 0
        for key, plan in COMPOUND_ENTRY_SPLITS.items():
            term = Term.query.filter_by(english=key).first()
            if term is None:
                continue
            if term.kinyarwanda != plan["expect_rw"]:
                print(f"[migrate] '{key}': rendering edited since the decision, "
                      f"split skipped")
                continue
            new_english = plan["create"]["english"]
            if Term.query.filter_by(english=new_english).first() is None:
                db.session.add(Term(**plan["create"]))
                made += 1
            for field, value in plan["keep"].items():
                setattr(term, field, value)
        db.session.commit()
        if made:
            print(f"[migrate] separated {made} two-concept entr(ies) into their own rows")
    except Exception as exc:
        db.session.rollback()
        print(f"[migrate] two-concept split skipped: {exc}")


def migrate_fix_contributor_attribution(app):
    """Restore correct contributor attribution on the community-suggested terms.

    Idempotent and safe on every startup. Only rows still holding the default
    author (or NULL) are corrected, so any later deliberate change to a term's
    contributor is preserved rather than forced back on the next boot.
    """
    try:
        changed = 0
        for english, author in CONTRIBUTOR_CORRECTIONS.items():
            term = Term.query.filter_by(english=english).first()
            if term and term.contributed_by in (DEFAULT_CONTRIBUTOR, None):
                term.contributed_by = author
                changed += 1
        if changed:
            db.session.commit()
            print(f"[migrate] corrected contributor attribution on {changed} term(s)")
    except Exception as exc:
        db.session.rollback()
        print(f"[migrate] contributor attribution correction skipped: {exc}")


# The editor's corrections to entries that are already live, applied to the
# database at startup so that a commit and a push are enough to change the
# site. Each change names the value it replaces: a field is updated only while
# it still holds that exact old value, so an entry already fixed by hand in
# the admin panel, or changed again later, is left as it is. Idempotent: once
# applied, the old values no longer match. seed_data.py carries the same new
# values, so a fresh database starts corrected. Never list a term of an
# annotation corpus here while its round is open.
EDITOR_CORRECTIONS = [
    # 28 September 2026, Khris: hypertension is pressure above normal, which
    # 'ukabije' (excessive) carries; the entry named the pressure only.
    ("Hypertension", {
        "kinyarwanda": ("Umuvuduko w'amaraso", "Umuvuduko ukabije w'amaraso"),
        "example_rw": ("Umurwayi yasuzumwe afite umuvuduko w'amaraso.",
                       "Umurwayi yasuzumwe afite umuvuduko ukabije w'amaraso."),
        "etymology": (
            "'Umuvuduko' means pressure or force, 'w'amaraso' means of the blood "
            "— literally 'pressure of the blood.'",
            "'Umuvuduko' means pressure or force, 'ukabije' means excessive, and "
            "'w'amaraso' means of the blood: literally 'excessive pressure of the "
            "blood', pressure above normal."),
        "source": ("Original starter terms",
                   "Original starter terms; rendering corrected by the editor, "
                   "28 September 2026"),
    }),
    # 28 September 2026, Khris: variants added by the editor.
    ("Asthma", {
        "variants_rw": ("Isemeka", "Isemeka / Asima"),
        "source": ("Annie Chibwe consent form",
                   "Annie Chibwe consent form; variant 'Asima' added by the "
                   "editor, 28 September 2026"),
    }),
    ("Diabetes", {
        "variants_rw": ("Indwara y'igisukari",
                        "Indwara y'igisukari / Igisukari / Gisukari"),
        "source": ("Original starter terms",
                   "Original starter terms; variants 'Igisukari' and 'Gisukari' "
                   "added by the editor, 28 September 2026"),
    }),
]


def migrate_apply_editor_corrections(app):
    """Apply EDITOR_CORRECTIONS to the live entries they name.

    A field changes only while it still holds the recorded old value; a field
    already holding the new value is done; anything else was edited by hand
    and is reported, never overwritten. Safe on every startup.
    """
    try:
        applied, kept = [], []
        for english, changes in EDITOR_CORRECTIONS:
            term = Term.query.filter_by(english=english).first()
            if term is None:
                continue
            for field, (old, new) in changes.items():
                current = getattr(term, field)
                if current == new:
                    continue
                if current == old:
                    setattr(term, field, new)
                    applied.append(f"{english}: {field}")
                else:
                    kept.append(f"{english}: {field}")
        if applied:
            db.session.commit()
            print(f"[migrate] editor corrections applied ({'; '.join(applied)})")
        for item in kept:
            print(f"[migrate] editor correction left out for {item}: "
                  f"the field was edited since, so it stays as it is")
    except Exception as exc:
        db.session.rollback()
        print(f"[migrate] editor corrections skipped: {exc}")


def migrate_add_validation_status(app):
    """Add the computed validation_status column to terms if it doesn't exist.

    Existing rows are backfilled with 'unreviewed', which is exactly true:
    no review rows exist yet. Idempotent and safe to run on every startup.
    """
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('postgresql'):
        _pg_add_columns_if_missing("terms", [
            ("validation_status",
             "VARCHAR(20) NOT NULL DEFAULT 'unreviewed'"),
        ])
        return
    if not db_uri.startswith('sqlite'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(terms)")
    existing = {row[1] for row in cursor.fetchall()}
    if 'validation_status' not in existing:
        cursor.execute(
            "ALTER TABLE terms ADD COLUMN validation_status VARCHAR(20) "
            "NOT NULL DEFAULT 'unreviewed'"
        )
    conn.commit()
    conn.close()


def migrate_add_shown_rw(app):
    """Add term_reviews.shown_rw if it doesn't exist.

    Records the exact Kinyarwanda string a reviewer saw when scoring, so the
    stimulus is auditable and a genuinely blind round remains possible later.
    Idempotent and safe on every startup.
    """
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('postgresql'):
        _pg_add_columns_if_missing("term_reviews", [
            ("shown_rw", "VARCHAR(200)"),
        ])
        return
    if not db_uri.startswith('sqlite'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(term_reviews)")
    existing = {row[1] for row in cursor.fetchall()}
    if 'shown_rw' not in existing:
        cursor.execute("ALTER TABLE term_reviews ADD COLUMN shown_rw VARCHAR(200)")
    conn.commit()
    conn.close()


# Columns added for the annotation corpus, as (name, Postgres DDL, SQLite DDL).
# `published` defaults to true so every term already in the dictionary stays
# public exactly as before; only corpus terms are loaded unpublished.
CORPUS_COLUMNS = [
    ("published", "BOOLEAN NOT NULL DEFAULT TRUE", "BOOLEAN NOT NULL DEFAULT 1"),
    ("corpus_version", "VARCHAR(20)", "VARCHAR(20)"),
    ("corpus_key", "VARCHAR(20)", "VARCHAR(20)"),
    ("pilot", "BOOLEAN NOT NULL DEFAULT FALSE", "BOOLEAN NOT NULL DEFAULT 0"),
    ("domain", "VARCHAR(40)", "VARCHAR(40)"),
    ("corpus_note", "TEXT", "TEXT"),
]
CORPUS_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_terms_corpus_key ON terms (corpus_key)",
    "CREATE INDEX IF NOT EXISTS ix_terms_corpus_version ON terms (corpus_version)",
]


def migrate_add_corpus_columns(app):
    """Add the publication and annotation-corpus columns to terms, and widen
    the two variant columns to TEXT on Postgres.

    Must run before anything queries Term through the ORM: the model already
    names these columns, so on a database that lacks them every ORM query on
    terms would fail until this has run. Idempotent and safe on every startup.

    Widening: variants_rw began as VARCHAR(300), and Differential blood count
    carries five variants that together run past 300 characters. SQLite does
    not enforce VARCHAR lengths, so only Postgres needs the change; it is a
    catalogue-only change there (no table rewrite), and it is skipped once the
    column is already TEXT.
    """
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('postgresql'):
        from sqlalchemy import text
        _pg_add_columns_if_missing("terms", [
            (name, pg_ddl) for name, pg_ddl, _ in CORPUS_COLUMNS
        ])
        try:
            with db.engine.begin() as conn:
                for column in ("variants_rw", "variants_en"):
                    data_type = conn.execute(text(
                        "SELECT data_type FROM information_schema.columns "
                        "WHERE table_schema = current_schema() "
                        "AND table_name = 'terms' AND column_name = :column"
                    ), {"column": column}).scalar()
                    if data_type == "character varying":
                        conn.execute(text(
                            f"ALTER TABLE terms ALTER COLUMN {column} TYPE TEXT"
                        ))
                for ddl in CORPUS_INDEXES:
                    conn.execute(text(ddl))
        except Exception as exc:
            print(f"[migrate] corpus column widening/indexes skipped: {exc}")
        return
    if not db_uri.startswith('sqlite'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(terms)")
    existing = {row[1] for row in cursor.fetchall()}
    for name, _, sqlite_ddl in CORPUS_COLUMNS:
        if name not in existing:
            cursor.execute(f"ALTER TABLE terms ADD COLUMN {name} {sqlite_ddl}")
    for ddl in CORPUS_INDEXES:
        cursor.execute(ddl)
    conn.commit()
    conn.close()


# Reviewer password state: (name, Postgres DDL, SQLite DDL). Accounts that
# exist when the column arrives get must_change_password = TRUE, so everyone
# still on a password someone else set chooses their own at the next sign-in.
REVIEWER_PASSWORD_COLUMNS = [
    ("must_change_password", "BOOLEAN NOT NULL DEFAULT TRUE", "BOOLEAN NOT NULL DEFAULT 1"),
    ("password_changed_at", "TIMESTAMP", "DATETIME"),
]


def migrate_add_reviewer_password_columns(app):
    """Add the password-state columns to reviewers.

    Must run before anything queries Reviewer through the ORM: the model
    already names these columns. Idempotent and safe on every startup.
    """
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('postgresql'):
        _pg_add_columns_if_missing("reviewers", [
            (name, pg_ddl) for name, pg_ddl, _ in REVIEWER_PASSWORD_COLUMNS
        ])
        return
    if not db_uri.startswith('sqlite'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(reviewers)")
    existing = {row[1] for row in cursor.fetchall()}
    if existing:
        for name, _, sqlite_ddl in REVIEWER_PASSWORD_COLUMNS:
            if name not in existing:
                cursor.execute(f"ALTER TABLE reviewers ADD COLUMN {name} {sqlite_ddl}")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# The annotation corpus — the frozen set of terms the reviewers score
# ---------------------------------------------------------------------------
# One file per corpus version. The file is the frozen record: its SHA-256 is
# written in the manifest beside it (data/ANNOTATION_CORPUS_v1.md) and checked
# by the test suite, so an edit after the freeze cannot go unnoticed.
ANNOTATION_CORPORA = {
    "v1": os.path.join("data", "annotation_corpus_v1.csv"),
}


def import_annotation_corpus(app, version="v1"):
    """Load a frozen annotation corpus into terms, unpublished.

    Loads once. If any term of this corpus version is already in the
    database, nothing happens: from then on the database is the working copy
    and the file is the frozen record. That keeps an editor's later changes
    (an adjudicated rendering, a term deliberately removed) from being undone
    on the next deploy. All rows go in one transaction, so a failure leaves
    no half-loaded corpus behind and the next boot simply tries again.

    Returns the number of terms created.
    """
    relative = ANNOTATION_CORPORA.get(version)
    if relative is None:
        return 0
    path = os.path.join(app.root_path, relative)
    if not os.path.exists(path):
        return 0
    try:
        if Term.query.filter_by(corpus_version=version).first() is not None:
            return 0
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        for row in rows:
            db.session.add(Term(
                english=row["english"],
                kinyarwanda=row["kinyarwanda"],
                variants_en=row["english_variants"] or None,
                variants_rw=row["kinyarwanda_variants"] or None,
                example_rw=row["example_rw"] or None,
                category=row["category"] or None,
                domain=row["domain"] or None,
                contributed_by=row["contributor"],
                source=row["provenance"],
                corpus_note=row["note"] or None,
                corpus_version=version,
                corpus_key=row["key"],
                pilot=(row["pilot"].strip().lower() == "yes"),
                published=False,
            ))
        db.session.commit()
        print(f"[corpus] loaded annotation corpus {version}: {len(rows)} terms, "
              f"unpublished")
        return len(rows)
    except Exception as exc:
        db.session.rollback()
        print(f"[corpus] annotation corpus {version} not loaded: {exc}")
        return 0


# ---------------------------------------------------------------------------
# Validation status — computed from term_reviews, never set by hand
# ---------------------------------------------------------------------------
# Stable reviewer ids mapped to the contributor names used in
# terms.contributed_by. This mapping is what lets the recompute exclude
# a reviewer's judgment of a term they themselves contributed. Add a new
# reviewer's entry here BEFORE they start reviewing, or author-exclusion
# cannot see them.
REVIEWER_NAMES = {
    "CM": "Christophe Mumaragishyika",
    "OU": "Olive Umuhoza",
    "YV": "Yvette Nkurunziza",
}


def recompute_validation_status(term):
    """Recompute term.validation_status from its blind review rows.

    Rules (validation methodology v2):
    - Only blind scores count. Adjudication rows are excluded.
    - A reviewer's judgment of a term they contributed is excluded.
    - Only each reviewer's latest blind score counts, so a re-review
      replaces the earlier one rather than stacking.
    - Status:
        0 qualifying reviews -> unreviewed
        1                    -> single
        2 or more            -> dual_agreed when at least two reviewers
                                score 4 and none scores below 3 (this is
                                identical to unanimity at exactly two
                                reviewers), otherwise dual_conflict

    The caller is responsible for db.session.commit().
    """
    rows = (
        TermReview.query
        .filter_by(term_id=term.id, is_adjudication=False)
        .order_by(TermReview.reviewed_at.asc(), TermReview.id.asc())
        .all()
    )
    latest = {}
    for r in rows:
        author_name = REVIEWER_NAMES.get(r.reviewer)
        if author_name and term.contributed_by and author_name == term.contributed_by:
            continue  # authors cannot validate their own terms
        latest[r.reviewer] = r.score  # later rows overwrite: latest wins

    scores = list(latest.values())
    if not scores:
        status = "unreviewed"
    elif len(scores) == 1:
        status = "single"
    else:
        fours = sum(1 for s in scores if s == 4)
        status = "dual_agreed" if (fours >= 2 and min(scores) >= 3) else "dual_conflict"

    term.validation_status = status
    return status


# Terms used as worked anchor examples in REVIEWER_GUIDELINE.md. A reviewer
# who has seen a term scored in the guideline would score it the same way
# in the queue, so these never appear in the scoring queue.
REVIEW_EXCLUDED_TERMS = {
    "Anemia",
    "Malaria",
    "Tuberculosis",
    "Bone tuberculosis",
    "Uterine prolapse",
    "Stomach ache",
}


# ---------------------------------------------------------------------------
# Round settings.
# REVIEW_DAILY_GOAL is the rhythm agreed with the reviewers (ten a day on the
# days they can); the score page shows progress against it. "Today" is
# measured from local midnight in Kigali (UTC+2, no daylight saving), which
# REVIEW_TZ_OFFSET_HOURS fixes. REVIEW_ROUND_CLOSED freezes every reviewer's
# scores once the round ends, so adjudication and the agreement statistics
# run on a fixed set; set it to 1 in the environment to close the round.
# ---------------------------------------------------------------------------
REVIEW_DAILY_GOAL = int(os.environ.get("REVIEW_DAILY_GOAL", "10") or 10)
REVIEW_TZ_OFFSET_HOURS = int(os.environ.get("REVIEW_TZ_OFFSET_HOURS", "2") or 2)
REVIEW_ROUND_CLOSED = (
    os.environ.get("REVIEW_ROUND_CLOSED", "").strip().lower() in ("1", "true", "yes")
)

# Which terms the scoring queue serves. The round scores a frozen annotation
# corpus (REVIEW_CORPUS, "v1"), not the whole terms table:
#   pilot  only the corpus terms marked as the pilot (the default, so a
#          fresh deploy can never open the full round by accident)
#   round  every term in the corpus; pilot scores already given stay counted
#   all    every term in the table, the behaviour before the corpus existed;
#          kept for the test suite and local work, not for the live round
# Set REVIEW_PHASE=round in the environment when the pilot is done.
REVIEW_PHASES = ("pilot", "round", "all")
REVIEW_PHASE = os.environ.get("REVIEW_PHASE", "pilot").strip().lower() or "pilot"
REVIEW_CORPUS = os.environ.get("REVIEW_CORPUS", "v1").strip() or "v1"

# The homepage says how many new terms are with the reviewers, without
# showing any of them: "+ 189 new terms under independent review, results in
# November". The line disappears by itself once no term of the corpus is
# waiting. Set REVIEW_RESULTS_EXPECTED to another month if the date moves, or
# to an empty value to drop the ", results in ..." part.
REVIEW_RESULTS_EXPECTED = os.environ.get("REVIEW_RESULTS_EXPECTED", "November").strip()


def _review_tz():
    return timezone(timedelta(hours=REVIEW_TZ_OFFSET_HOURS))


def _naive_utc(dt):
    """Stored timestamps are naive UTC; normalise an aware value to match."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _local_day_start_utc(days_ago=0):
    """Naive UTC datetime of local midnight, `days_ago` days back."""
    now_local = datetime.now(_review_tz())
    start_local = (now_local - timedelta(days=days_ago)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc).replace(tzinfo=None)


def _local_date(dt):
    """Local calendar date (Kigali) of a stored naive-UTC timestamp."""
    return _naive_utc(dt).replace(tzinfo=timezone.utc).astimezone(_review_tz()).date()


def reviewer_progress(reviewer, days=14):
    """Counts for one reviewer: distinct terms scored, scored today, scored in
    the last seven days, latest activity, and a per-day series for the last
    `days` local days (oldest first). Blind scores only."""
    rows = (TermReview.query
            .filter_by(reviewer=reviewer.code, is_adjudication=False)
            .order_by(TermReview.reviewed_at.desc(), TermReview.id.desc())
            .all())
    total = len({r.term_id for r in rows})
    today_start = _local_day_start_utc(0)
    week_start = _local_day_start_utc(6)
    today = len({r.term_id for r in rows
                 if r.reviewed_at and _naive_utc(r.reviewed_at) >= today_start})
    week = len({r.term_id for r in rows
                if r.reviewed_at and _naive_utc(r.reviewed_at) >= week_start})
    latest = rows[0] if rows else None
    today_local = datetime.now(_review_tz()).date()
    series = []
    for i in range(days - 1, -1, -1):
        day = today_local - timedelta(days=i)
        count = len({r.term_id for r in rows
                     if r.reviewed_at and _local_date(r.reviewed_at) == day})
        series.append((day, count))
    return {
        "total": total, "today": today, "week": week,
        "latest": latest, "series": series,
    }


# ---------------------------------------------------------------------------
# Access control — admin and reviewer are different kinds of session
# ---------------------------------------------------------------------------
def _actual_user():
    return current_user._get_current_object() if current_user.is_authenticated else None


def admin_required(view):
    """Only an Admin session may pass. Reviewers get 403, guests get login."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _actual_user()
        if user is None:
            return redirect(url_for("admin_login", next=request.path))
        if not isinstance(user, Admin):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


# The same minimum for a password an admin sets and one a reviewer chooses.
PASSWORD_MIN_LENGTH = 12


def _password_step_url(next_page=None):
    """The page where a reviewer chooses a password, remembering where they
    were going so they land there once it is saved."""
    if next_page and is_safe_redirect_target(next_page):
        return url_for("review_password", next=next_page)
    return url_for("review_password")


def suggestion_matches(suggestions, terms):
    """For each suggestion, the entries its word already has in the table.

    A suggestion like "miscarriage/abortion" is split on "/" and each part is
    looked up by English headword, then by English variant, ignoring capitals
    and outer spaces. Returns {suggestion id: {"terms": [...], "all_public":
    bool, "in_round": bool}}, where all_public means every part is already a
    public entry, so resolving the suggestion loses nothing.
    """
    index = {}
    for t in terms:
        index.setdefault((t.english or "").strip().casefold(), t)
    for t in terms:
        for variant in (t.variants_en or "").split("/"):
            key = variant.strip().casefold()
            if key:
                index.setdefault(key, t)
    out = {}
    for s in suggestions:
        parts = [p.strip().casefold() for p in (s.english_word or "").split("/") if p.strip()]
        found = [index.get(p) for p in parts]
        hits = [t for t in found if t is not None]
        out[s.id] = {
            "terms": list(dict.fromkeys(hits)),
            "all_public": bool(parts) and all(t is not None and t.published for t in found),
            "in_round": any(t is not None and not t.published and t.corpus_version
                            for t in found),
        }
    return out


def reviewer_required(view):
    """Only a Reviewer session may pass. Admins get 403, guests get login.

    A reviewer still on a password someone else set is sent to choose their
    own first; until then the only other page open to them is logging out.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _actual_user()
        if user is None:
            return redirect(url_for("review_login", next=request.path))
        if not isinstance(user, Reviewer):
            abort(403)
        if user.must_change_password and request.endpoint != "review_logout":
            # Only a page can be returned to afterwards, never a form post.
            return redirect(_password_step_url(
                request.path if request.method == "GET" else None))
        return view(*args, **kwargs)
    return wrapped


def _find_reviewer(username):
    """The reviewer account for a typed username, ignoring capitals.

    Phones capitalise the first letter of a text box, so a reviewer who types
    "Olive" must still reach the account "olive". An exact match wins; failing
    that, a match that ignores capitals is used, but only when exactly one
    account fits. Passwords stay exact.
    """
    if not username:
        return None
    exact = Reviewer.query.filter_by(username=username).first()
    if exact is not None:
        return exact
    matches = (
        Reviewer.query
        .filter(func.lower(Reviewer.username) == username.lower())
        .limit(2)
        .all()
    )
    return matches[0] if len(matches) == 1 else None


def _seed_reviewers():
    """Create reviewer accounts from REVIEWER_ACCOUNTS if they don't exist.

    Format: 'CODE:username:password;CODE:username:password'
    e.g.    'OU:olive:secret;YV:yvette:secret'
    Display names come from REVIEWER_NAMES. Existing accounts are never
    modified here, so rotating a password means deleting and recreating.
    Returns the number of accounts created.
    """
    raw = os.environ.get("REVIEWER_ACCOUNTS", "").strip()
    if not raw:
        return 0
    created = 0
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        if len(parts) != 3:
            print(f"[reviewers] skipping malformed entry: {chunk!r}")
            continue
        code, username, password = (p.strip() for p in parts)
        if not (code and username and password):
            print(f"[reviewers] skipping incomplete entry: {chunk!r}")
            continue
        if Reviewer.query.filter(
            db.or_(Reviewer.code == code, Reviewer.username == username)
        ).first():
            continue
        r = Reviewer(code=code, username=username,
                     display_name=REVIEWER_NAMES.get(code, code))
        r.set_password(password)
        db.session.add(r)
        created += 1
    return created


# ---------------------------------------------------------------------------
# Extensions — module-level singletons, bound to each app via init_app().
# (Factory pattern: the app can be created more than once — e.g. in tests —
#  without re-instantiating these, which also avoids Flask-Limiter weakref
#  errors under repeated app creation.)
# ---------------------------------------------------------------------------
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)


# ---------------------------------------------------------------------------
# App Factory
# ---------------------------------------------------------------------------
def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    app.config.setdefault("REVIEW_ROUND_CLOSED", REVIEW_ROUND_CLOSED)
    app.config.setdefault("REVIEW_DAILY_GOAL", REVIEW_DAILY_GOAL)
    app.config.setdefault("REVIEW_PHASE", REVIEW_PHASE)
    app.config.setdefault("REVIEW_CORPUS", REVIEW_CORPUS)
    app.config.setdefault("REVIEW_RESULTS_EXPECTED", REVIEW_RESULTS_EXPECTED)
    if app.config["REVIEW_PHASE"] not in REVIEW_PHASES:
        # An unknown value falls back to the narrowest queue, never the widest.
        print(f"[review] unknown REVIEW_PHASE {app.config['REVIEW_PHASE']!r}; "
              f"using 'pilot'")
        app.config["REVIEW_PHASE"] = "pilot"

    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    @app.url_defaults
    def _version_static_urls(endpoint, values):
        # Every url_for('static', ...) in every template gets ?v=<content hash>
        # without the templates having to know about it. base.html included.
        if endpoint == "static" and "filename" in values and "v" not in values:
            version = static_file_version(app.static_folder, values["filename"])
            if version:
                values["v"] = version

    # Set up Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "admin_login"
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        # Session ids are 'admin:<id>' or 'reviewer:<id>'. A bare integer is
        # an admin session from before reviewer accounts existed.
        kind, _, raw = str(user_id).partition(":")
        if not raw:
            kind, raw = "admin", kind
        try:
            pk = int(raw)
        except ValueError:
            return None
        if kind == "reviewer":
            return db.session.get(Reviewer, pk)
        if kind == "admin":
            return db.session.get(Admin, pk)
        return None

    # ---------------------------------------------------------------
    # Security headers
    # ---------------------------------------------------------------
    @app.after_request
    def set_security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.errorhandler(429)
    def ratelimit_handler(e):
        # API endpoints get a JSON 429; everything else gets the friendly page
        if request.path.startswith("/api/"):
            return jsonify({"error": "Too many requests. Please slow down."}), 429
        flash("Too many login attempts. Please wait a minute and try again.", "danger")
        # A reviewer who mistypes a few times stays on their own login page,
        # not the admin one.
        if request.path.startswith("/review"):
            return render_template("review/login.html"), 429
        return render_template("admin/login.html"), 429

    # Create database tables, migrate, and auto-seed new terms
    with app.app_context():
        db.create_all()
        migrate_add_provenance_columns(app)
        migrate_add_suggestion_resolved(app)
        migrate_add_validation_status(app)
        migrate_add_shown_rw(app)
        migrate_add_variant_columns(app)
        # Before any ORM query on Term (the model already names these columns).
        migrate_add_corpus_columns(app)
        # Before any ORM query on Reviewer, _seed_reviewers() included.
        migrate_add_reviewer_password_columns(app)
        migrate_split_compound_entries(app)
        migrate_split_two_concept_entries(app)
        migrate_fix_contributor_attribution(app)
        migrate_apply_editor_corrections(app)

        from seed_data import STARTER_TERMS, ADMIN_USERNAME, ADMIN_PASSWORD

        added = 0
        for term_data in STARTER_TERMS:
            if not Term.query.filter_by(english=term_data["english"]).first():
                db.session.add(Term(**term_data))
                added += 1

        admin_created = False
        if not Admin.query.filter_by(username=ADMIN_USERNAME).first():
            admin = Admin(username=ADMIN_USERNAME)
            admin.set_password(ADMIN_PASSWORD)
            db.session.add(admin)
            admin_created = True

        reviewers_created = _seed_reviewers()

        # Commit if anything was staged — not only when new terms were added.
        # Otherwise a freshly-created admin (e.g. after rotating ADMIN_USERNAME)
        # would be silently rolled back and you'd be locked out.
        if added > 0 or admin_created or reviewers_created:
            db.session.commit()
            if added > 0:
                print(f"Auto-seed: added {added} new terms (total: {Term.query.count()})")
            if reviewers_created:
                print(f"[reviewers] created {reviewers_created} reviewer account(s)")

        # The frozen annotation corpora, each loaded once and unpublished.
        # After the starter terms, so a fresh database gets the dictionary first.
        for version in ANNOTATION_CORPORA:
            import_annotation_corpus(app, version)

    # -------------------------------------------------------------------
    # PUBLIC ROUTES
    # -------------------------------------------------------------------

    # The public site, the API and the data export show published terms only.
    # Corpus terms waiting for review are in the table but not in the
    # dictionary yet.
    def public_terms():
        return Term.query.filter(Term.published.is_(True))

    @app.route("/")
    def index():
        terms = public_terms().order_by(Term.english.asc()).all()
        recent = public_terms().order_by(Term.created_at.desc()).limit(10).all()
        terms_json = [t.to_dict() for t in terms]
        # A count only: the terms themselves stay hidden until they are verified.
        under_review_count = Term.query.filter(
            Term.published.is_(False),
            Term.corpus_version == app.config["REVIEW_CORPUS"],
        ).count()
        return render_template(
            "index.html",
            terms_json=terms_json,
            recent_terms=recent,
            total_count=len(terms),
            under_review_count=under_review_count,
            review_results_expected=app.config["REVIEW_RESULTS_EXPECTED"],
        )

    @app.route("/suggest", methods=["GET", "POST"])
    def suggest():
        if request.method == "POST":
            suggestion = Suggestion(
                english_word=request.form.get("english_word", "").strip(),
                suggested_translation=request.form.get("suggested_translation", "").strip() or None,
                context=request.form.get("context", "").strip() or None,
                submitter_email=request.form.get("email", "").strip() or None,
            )
            db.session.add(suggestion)
            db.session.commit()
            flash("Thank you! Your suggestion has been submitted for review.", "success")
            return redirect(url_for("index"))
        return render_template("suggest.html")

    @app.route("/about")
    def about():
        return render_template("about.html")

    # -------------------------------------------------------------------
    # API ROUTES (CSRF-exempt — no cookie auth)
    # -------------------------------------------------------------------

    @app.route("/api/terms")
    @csrf.exempt
    def api_terms_route():
        terms = public_terms().order_by(Term.english.asc()).all()
        return jsonify([t.to_dict() for t in terms])

    @app.route("/api/search")
    @csrf.exempt
    @limiter.limit("30 per minute")
    def api_search_route():
        query = request.args.get("q", "").strip().lower()
        if not query:
            return jsonify([])
        results = public_terms().filter(
            db.or_(
                Term.english.ilike(f"%{query}%"),
                Term.kinyarwanda.ilike(f"%{query}%"),
                Term.variants_rw.ilike(f"%{query}%"),
                Term.variants_en.ilike(f"%{query}%")
            )
        ).all()
        # Log the API search
        log = SearchLog(
            query_text=query,
            results_count=len(results),
            source="api"
        )
        db.session.add(log)
        db.session.commit()
        return jsonify([t.to_dict() for t in results])

    @app.route("/api/log-search", methods=["POST"])
    @csrf.exempt
    @limiter.limit("30 per minute")
    def api_log_search():
        """
        Called by the public search page JS (debounced).
        Logs the query and how many results it returned.
        """
        data = request.get_json(silent=True) or {}
        query = (data.get("query") or "").strip().lower()
        results_count = data.get("results_count", 0)
        # Match the frontend's 4-char floor so the noise filter holds even if
        # something calls this endpoint directly.
        if not query or len(query) < 4:
            return jsonify({"ok": True})
        log = SearchLog(
            query_text=query,
            results_count=int(results_count),
            source="web"
        )
        db.session.add(log)
        db.session.commit()
        return jsonify({"ok": True})

    # -------------------------------------------------------------------
    # ADMIN ROUTES
    # -------------------------------------------------------------------

    @app.route("/admin/login", methods=["GET", "POST"])
    @limiter.limit("5 per minute")
    def admin_login():
        if current_user.is_authenticated:
            if isinstance(_actual_user(), Reviewer):
                return redirect(url_for("review_queue"))
            return redirect(url_for("admin_dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            admin = Admin.query.filter_by(username=username).first()

            if admin and admin.check_password(password):
                login_user(admin)
                flash("Welcome back!", "success")
                next_page = request.args.get("next")
                if not is_safe_redirect_target(next_page):
                    next_page = None
                return redirect(next_page or url_for("admin_dashboard"))
            else:
                flash("Invalid username or password.", "danger")

        return render_template("admin/login.html")

    @app.route("/admin/logout")
    @login_required
    def admin_logout():
        logout_user()
        flash("You have been logged out.", "info")
        return redirect(url_for("index"))

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        total_terms = Term.query.count()
        public_count = public_terms().count()
        unpublished_count = total_terms - public_count
        corpus_version = app.config["REVIEW_CORPUS"]
        corpus_count = Term.query.filter_by(corpus_version=corpus_version).count()
        corpus_pilot_count = Term.query.filter_by(
            corpus_version=corpus_version, pilot=True).count()
        # Active = not yet resolved (regardless of status)
        active_suggestions = Suggestion.query.filter_by(resolved=False) \
            .order_by(Suggestion.created_at.desc()).all()
        # Resolved archive
        resolved_suggestions = Suggestion.query.filter_by(resolved=True) \
            .order_by(Suggestion.resolved_at.desc()).all()
        all_terms = Term.query.order_by(Term.english.asc()).all()
        # Which suggested words the dictionary already holds, for the note on
        # each card and "Select those already in the dictionary".
        matches = suggestion_matches(active_suggestions, all_terms)

        # --- Search analytics ---
        total_searches = SearchLog.query.count()

        # Top searched queries (all time, top 15)
        top_queries = db.session.query(
            SearchLog.query_text,
            func.count(SearchLog.id).label("search_count"),
            func.min(SearchLog.results_count).label("min_results")
        ).group_by(SearchLog.query_text).order_by(
            func.count(SearchLog.id).desc()
        ).limit(15).all()

        # "No results" queries — your priority list for new terms
        no_results_queries = db.session.query(
            SearchLog.query_text,
            func.count(SearchLog.id).label("search_count")
        ).filter(
            SearchLog.results_count == 0
        ).group_by(SearchLog.query_text).order_by(
            func.count(SearchLog.id).desc()
        ).limit(20).all()

        # --- Reviewer progress (the weekly check-in, without asking) ---
        reviewers = Reviewer.query.order_by(Reviewer.code.asc()).all()
        reviewer_progress_rows = [
            (rv, reviewer_progress(rv)) for rv in reviewers
        ]

        return render_template(
            "admin/dashboard.html",
            total_terms=total_terms,
            public_count=public_count,
            unpublished_count=unpublished_count,
            corpus_version=corpus_version,
            corpus_count=corpus_count,
            corpus_pilot_count=corpus_pilot_count,
            review_phase=app.config["REVIEW_PHASE"],
            pending_count=len(active_suggestions),
            suggestions=active_suggestions,
            suggestion_info=matches,
            in_dictionary_count=sum(1 for m in matches.values() if m["all_public"]),
            resolved_suggestions=resolved_suggestions,
            all_terms=all_terms,
            total_searches=total_searches,
            top_queries=top_queries,
            no_results_queries=no_results_queries,
            reviewer_progress_rows=reviewer_progress_rows,
            daily_goal=app.config["REVIEW_DAILY_GOAL"],
            round_closed=app.config["REVIEW_ROUND_CLOSED"],
        )

    @app.route("/admin/reviewer/<int:reviewer_id>/password", methods=["POST"])
    @admin_required
    def admin_reviewer_password(reviewer_id):
        """Set a new password for a reviewer account.

        REVIEWER_ACCOUNTS only creates accounts that do not exist yet, so this
        is the way to rotate a password once the account is live. The new
        password is never logged or shown back; hand it to the reviewer over
        a separate channel from the login link.
        """
        reviewer = db.get_or_404(Reviewer, reviewer_id)
        new_password = request.form.get("new_password", "")
        if len(new_password) < PASSWORD_MIN_LENGTH:
            flash(f"The new password must be at least {PASSWORD_MIN_LENGTH} characters long.",
                  "danger")
            return redirect(url_for("admin_dashboard"))
        reviewer.set_password(new_password)
        # A password the admin knows is temporary: the reviewer chooses their
        # own at the next sign-in.
        reviewer.must_change_password = True
        reviewer.password_changed_at = None
        db.session.commit()
        flash(f"Password updated for {reviewer.display_name} ({reviewer.username}). "
              f"It is temporary: they will choose their own at their next sign-in.",
              "success")
        return redirect(url_for("admin_dashboard"))

    def _clean_variants(raw):
        """Normalise the typed variants field to 'A / B / C', or None.

        Empty pieces are dropped and separators are regularised, so the stored
        string is predictable for search and for the freeze artifact.
        """
        parts = [p.strip() for p in (raw or "").split("/")]
        parts = [p for p in parts if p]
        return " / ".join(parts) or None

    def _existing_headword(english):
        """The entry already using this English headword (any capitals),
        public or in a review round: the dictionary keeps one entry per word."""
        english = (english or "").strip()
        if not english:
            return None
        return Term.query.filter(func.lower(Term.english) == english.lower()).first()

    def _in_open_round(term):
        return bool(term.corpus_version) and not term.published

    def _resolve_suggestions_for(term, suggestion_id=None):
        """Close the suggestion a new term came from, and every other active
        suggestion for the same word, noting where it went. Returns the count."""
        now = datetime.now(timezone.utc)
        note = f"Added to the dictionary as '{term.english}' on {now.strftime('%d %b %Y')}."
        targets = []
        if suggestion_id:
            origin = db.session.get(Suggestion, suggestion_id)
            if origin is not None and not origin.resolved:
                targets.append(origin)
        same_word = Suggestion.query.filter(
            Suggestion.resolved == False,  # noqa: E712  (as the dashboard reads it)
            func.lower(func.trim(Suggestion.english_word)) == term.english.strip().lower(),
        ).all()
        targets += [s for s in same_word if s not in targets]
        for s in targets:
            s.status = "approved"
            s.resolved = True
            s.resolved_at = now
            s.admin_notes = f"{s.admin_notes}\n{note}" if s.admin_notes else note
        return len(targets)

    @app.route("/admin/add", methods=["GET", "POST"])
    @admin_required
    def admin_add_term():
        # Set when the form was opened from a suggestion's "Approve & Add".
        raw_id = request.form.get("suggestion_id") or request.args.get("suggestion")
        try:
            suggestion_id = int(raw_id) if raw_id else None
        except (TypeError, ValueError):
            suggestion_id = None

        if request.method == "POST":
            existing = _existing_headword(request.form.get("english"))
            if existing is not None:
                if _in_open_round(existing):
                    flash(f'"{existing.english}" is one of the terms in the review round, '
                          f'not public yet. Nothing was added; leave it until the round '
                          f'closes.', "warning")
                    return redirect(url_for("admin_dashboard"))
                flash(f'"{existing.english}" is already in the dictionary, so nothing was '
                      f'added. Here is its entry, if you want to add another form as a '
                      f'variant.', "warning")
                return redirect(url_for("admin_edit_term", term_id=existing.id))
            term = Term(
                english=request.form.get("english", "").strip(),
                kinyarwanda=request.form.get("kinyarwanda", "").strip(),
                variants_rw=_clean_variants(request.form.get("variants_rw", "")),
                variants_en=_clean_variants(request.form.get("variants_en", "")),
                example_en=request.form.get("example_en", "").strip() or None,
                example_rw=request.form.get("example_rw", "").strip() or None,
                etymology=request.form.get("etymology", "").strip() or None,
                category=request.form.get("category", "").strip() or None,
                source=request.form.get("source", "").strip() or None,
            )
            db.session.add(term)
            resolved = _resolve_suggestions_for(term, suggestion_id)
            db.session.commit()
            message = f'"{term.english}" has been added to the dictionary.'
            if resolved == 1:
                message += " Its suggestion was marked resolved."
            elif resolved > 1:
                message += f" The {resolved} suggestions for it were marked resolved."
            flash(message, "success")
            return redirect(url_for("admin_dashboard"))
        # Warn before any typing when the word is already here.
        existing = _existing_headword(request.args.get("english"))
        return render_template(
            "admin/add_term.html",
            existing=existing,
            existing_in_round=existing is not None and _in_open_round(existing),
            suggestion_id=suggestion_id,
        )

    @app.route("/admin/edit/<int:term_id>", methods=["GET", "POST"])
    @admin_required
    def admin_edit_term(term_id):
        term = Term.query.get_or_404(term_id)
        if request.method == "POST":
            term.english = request.form.get("english", "").strip()
            term.kinyarwanda = request.form.get("kinyarwanda", "").strip()
            term.variants_rw = _clean_variants(request.form.get("variants_rw", ""))
            term.variants_en = _clean_variants(request.form.get("variants_en", ""))
            term.example_en = request.form.get("example_en", "").strip() or None
            term.example_rw = request.form.get("example_rw", "").strip() or None
            term.etymology = request.form.get("etymology", "").strip() or None
            term.category = request.form.get("category", "").strip() or None
            term.source = request.form.get("source", "").strip() or None
            db.session.commit()
            flash(f'"{term.english}" has been updated.', "success")
            return redirect(url_for("admin_dashboard"))
        return render_template("admin/add_term.html", term=term, editing=True)

    @app.route("/admin/delete/<int:term_id>", methods=["POST"])
    @admin_required
    def admin_delete_term(term_id):
        term = Term.query.get_or_404(term_id)
        english = term.english
        db.session.delete(term)
        db.session.commit()
        flash(f'"{english}" has been removed from the dictionary.', "info")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/suggestion/<int:suggestion_id>/<action>", methods=["POST"])
    @admin_required
    def admin_handle_suggestion(suggestion_id, action):
        suggestion = db.get_or_404(Suggestion, suggestion_id)
        if action == "approve":
            # Open the add-term form pre-filled, carrying the suggestion's id.
            # Nothing changes yet: saving the term resolves the suggestion,
            # cancelling the form leaves it exactly as it is.
            return redirect(url_for(
                "admin_add_term",
                english=suggestion.english_word,
                suggested=suggestion.suggested_translation or "",
                suggestion=suggestion.id,
            ))
        elif action == "reject":
            _reject_suggestion(suggestion, datetime.now(timezone.utc))
            db.session.commit()
            flash(f'"{suggestion.english_word}" rejected and moved to the archive. '
                  f'"Restore to Active" brings it back.', "info")
        return redirect(url_for("admin_dashboard") + "#suggestions")

    def _reject_suggestion(suggestion, now):
        """A rejected word is handled: mark it rejected and close it."""
        suggestion.status = "rejected"
        if not suggestion.resolved:
            suggestion.resolved = True
            suggestion.resolved_at = now
        note = f"Rejected on {now.strftime('%d %b %Y')}."
        if note not in (suggestion.admin_notes or ""):
            suggestion.admin_notes = (f"{suggestion.admin_notes}\n{note}"
                                      if suggestion.admin_notes else note)

    BULK_SUGGESTION_ACTIONS = {
        "resolve": "resolved",
        "reject": "rejected",
        "restore": "restored to the active list",
    }

    @app.route("/admin/suggestions/bulk", methods=["POST"])
    @admin_required
    def admin_bulk_suggestions():
        """Resolve, reject or restore every ticked suggestion in one step.

        Nothing is deleted, and each action can be undone from the other
        list, so there is no confirmation dialog.
        """
        action = request.form.get("action", "")
        ids = []
        for raw in request.form.getlist("ids"):
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        if action not in BULK_SUGGESTION_ACTIONS or not ids:
            flash("Nothing was changed: tick at least one suggestion first.", "info")
            return redirect(url_for("admin_dashboard") + "#suggestions")
        now = datetime.now(timezone.utc)
        changed = 0
        for s in Suggestion.query.filter(Suggestion.id.in_(ids)).all():
            if action == "resolve" and not s.resolved:
                s.resolved, s.resolved_at = True, now
                changed += 1
            elif action == "reject" and not (s.resolved and s.status == "rejected"):
                _reject_suggestion(s, now)
                changed += 1
            elif action == "restore" and s.resolved:
                s.resolved, s.resolved_at = False, None
                changed += 1
        db.session.commit()
        noun = "suggestion" if changed == 1 else "suggestions"
        message = f"{changed} {noun} {BULK_SUGGESTION_ACTIONS[action]}."
        if action != "restore" and changed:
            message += " You can bring any of them back from the Resolved Archive."
        flash(message, "success")
        return redirect(url_for("admin_dashboard") + "#suggestions")

    @app.route("/admin/suggestion/<int:suggestion_id>/resolve", methods=["POST"])
    @admin_required
    def admin_resolve_suggestion(suggestion_id):
        """Mark a suggestion as resolved — moves it to the archive."""
        suggestion = db.get_or_404(Suggestion, suggestion_id)
        suggestion.resolved = True
        suggestion.resolved_at = datetime.now(timezone.utc)
        db.session.commit()
        flash(
            f'"{suggestion.english_word}" resolved and moved to archive.',
            "success"
        )
        return redirect(url_for("admin_dashboard") + "#suggestions")

    @app.route("/admin/suggestion/<int:suggestion_id>/unresolve", methods=["POST"])
    @admin_required
    def admin_unresolve_suggestion(suggestion_id):
        """Restore a resolved suggestion back to the active panel."""
        suggestion = db.get_or_404(Suggestion, suggestion_id)
        suggestion.resolved = False
        suggestion.resolved_at = None
        db.session.commit()
        flash(
            f'"{suggestion.english_word}" restored to active suggestions.',
            "info"
        )
        return redirect(url_for("admin_dashboard") + "#suggestions")

    # -------------------------------------------------------------------
    # REVIEWER ROUTES — the scoring interface for the validation round
    # -------------------------------------------------------------------

    def _in_review_phase(term):
        """True if the current phase puts this term in the queue.

        pilot: the corpus terms marked as the pilot; round: every term of the
        corpus; all: every term in the table (tests and local work only).
        """
        phase = app.config["REVIEW_PHASE"]
        if phase == "all":
            return True
        if term.corpus_version != app.config["REVIEW_CORPUS"]:
            return False
        if phase == "round":
            return True
        return bool(term.pilot)

    def _review_queue_for(reviewer):
        """Return (eligible, remaining, ordered_next) for this reviewer.

        eligible: every term this reviewer may score. Only the terms the
                  current phase serves (see _in_review_phase), minus the
                  guideline anchors and any term the reviewer contributed
                  (author exclusion, mirrored here so they never even see it).
        remaining: eligible terms with no blind score from this reviewer yet.
        ordered_next: remaining, in a randomised order that is stable for
                  this reviewer (hash of code + id), with terms they chose
                  to skip pushed to the end.
        """
        author_name = REVIEWER_NAMES.get(reviewer.code)
        scored_ids = {
            r.term_id for r in TermReview.query
            .filter_by(reviewer=reviewer.code, is_adjudication=False).all()
        }
        eligible = [
            t for t in Term.query.all()
            if _in_review_phase(t)
            and t.english not in REVIEW_EXCLUDED_TERMS
            and not (author_name and t.contributed_by == author_name)
        ]
        eligible.sort(key=lambda t: hashlib.sha256(
            f"{reviewer.code}:{t.id}".encode()).hexdigest())
        remaining = [t for t in eligible if t.id not in scored_ids]
        skipped = set(session.get("review_skipped", []))
        ordered_next = ([t for t in remaining if t.id not in skipped]
                        + [t for t in remaining if t.id in skipped])
        return eligible, remaining, ordered_next

    def _reviewer_may_score(reviewer, term):
        author_name = REVIEWER_NAMES.get(reviewer.code)
        if not _in_review_phase(term):
            return False
        if term.english in REVIEW_EXCLUDED_TERMS:
            return False
        if author_name and term.contributed_by == author_name:
            return False
        return True

    def _previous_blind_score(reviewer, term):
        return (TermReview.query
                .filter_by(term_id=term.id, reviewer=reviewer.code,
                           is_adjudication=False)
                .order_by(TermReview.reviewed_at.desc(), TermReview.id.desc())
                .first())

    @app.route("/review/login", methods=["GET", "POST"])
    @limiter.limit("5 per minute")
    def review_login():
        if current_user.is_authenticated:
            if isinstance(_actual_user(), Reviewer):
                return redirect(url_for("review_queue"))
            return redirect(url_for("admin_dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            reviewer = _find_reviewer(username)
            if reviewer and reviewer.active and reviewer.check_password(password):
                login_user(reviewer)
                session.pop("review_skipped", None)
                flash(f"Welcome, {reviewer.display_name}.", "success")
                next_page = request.args.get("next")
                if not is_safe_redirect_target(next_page):
                    next_page = None
                if reviewer.must_change_password:
                    return redirect(_password_step_url(next_page))
                return redirect(next_page or url_for("review_queue"))
            flash("Invalid username or password.", "danger")

        return render_template("review/login.html")

    @app.route("/review/password", methods=["GET", "POST"])
    def review_password():
        """Choose a new password.

        Required at the first sign-in and after an admin reset, when the
        account still carries a password someone else chose; open at any
        other time from the scoring pages, with the current password. Not
        wrapped in reviewer_required, which would send a reviewer who has
        not chosen yet straight back here.
        """
        user = _actual_user()
        if user is None:
            return redirect(url_for("review_login", next=request.path))
        if not isinstance(user, Reviewer):
            abort(403)
        first_time = bool(user.must_change_password)
        next_page = request.args.get("next")
        if not is_safe_redirect_target(next_page):
            next_page = None

        if request.method == "POST":
            current = request.form.get("current_password", "")
            new = request.form.get("new_password", "")
            confirm = request.form.get("confirm_password", "")
            error = None
            if not first_time and not user.check_password(current):
                error = "Your current password is not right. Please type it again."
            elif len(new) < PASSWORD_MIN_LENGTH:
                error = f"Please choose at least {PASSWORD_MIN_LENGTH} characters."
            elif new != confirm:
                error = "The two new passwords are not the same. Please type them again."
            elif user.check_password(new):
                error = ("Please choose a password different from the one you were sent."
                         if first_time else
                         "Please choose a password different from your current one.")
            elif new.strip().casefold() == user.username.casefold():
                error = "Please choose a password different from your username."
            if error:
                flash(error, "danger")
            else:
                user.set_password(new)
                user.must_change_password = False
                user.password_changed_at = datetime.now(timezone.utc)
                db.session.commit()
                flash("Your new password is saved. Use it from now on.", "success")
                return redirect(next_page or url_for("review_queue"))

        return render_template(
            "review/password.html",
            reviewer=user,
            first_time=first_time,
            min_length=PASSWORD_MIN_LENGTH,
        )

    @app.route("/review/logout")
    @reviewer_required
    def review_logout():
        logout_user()
        session.pop("review_skipped", None)
        flash("You have been logged out.", "info")
        return redirect(url_for("index"))

    @app.route("/review")
    @reviewer_required
    def review_queue():
        reviewer = _actual_user()
        eligible, remaining, ordered_next = _review_queue_for(reviewer)
        if not ordered_next:
            return render_template(
                "review/done.html",
                reviewer=reviewer,
                total=len(eligible),
            )
        return redirect(url_for("review_term", term_id=ordered_next[0].id))

    @app.route("/review/term/<int:term_id>")
    @reviewer_required
    def review_term(term_id):
        reviewer = _actual_user()
        term = db.get_or_404(Term, term_id)
        if not _reviewer_may_score(reviewer, term):
            abort(403)
        eligible, remaining, _ = _review_queue_for(reviewer)
        progress = reviewer_progress(reviewer, days=1)
        latest = progress["latest"]
        previous_term = (latest.term if latest and latest.term_id != term.id else None)
        return render_template(
            "review/score.html",
            reviewer=reviewer,
            term=term,
            previous=_previous_blind_score(reviewer, term),
            previous_term=previous_term,
            done=len(eligible) - len(remaining),
            total=len(eligible),
            today_count=progress["today"],
            daily_goal=app.config["REVIEW_DAILY_GOAL"],
            history_count=progress["total"],
            round_closed=app.config["REVIEW_ROUND_CLOSED"],
        )

    @app.route("/review/term/<int:term_id>/score", methods=["POST"])
    @reviewer_required
    def review_score(term_id):
        reviewer = _actual_user()
        term = db.get_or_404(Term, term_id)
        if not _reviewer_may_score(reviewer, term):
            abort(403)

        if app.config["REVIEW_ROUND_CLOSED"]:
            flash("The round is closed, so scores can no longer be added or "
                  "changed. Your scored terms are still listed below.", "warning")
            return redirect(url_for("review_history"))

        raw_score = request.form.get("score", "").strip()
        if not raw_score:
            flash("Choose a score first, then press Save.", "warning")
            return redirect(url_for("review_term", term_id=term.id))
        try:
            score = int(raw_score)
        except ValueError:
            abort(400)
        if score not in (1, 2, 3, 4):
            abort(400)

        previous = _previous_blind_score(reviewer, term)
        if previous and request.form.get("confirm_replace") != "yes":
            flash("You have already scored this term. Tick the box to confirm "
                  "you want to replace your earlier score.", "warning")
            return redirect(url_for("review_term", term_id=term.id))

        row = TermReview(
            term_id=term.id,
            reviewer=reviewer.code,
            score=score,
            proposed_rw=request.form.get("proposed_rw", "").strip() or None,
            note=request.form.get("note", "").strip() or None,
            # What was actually on screen, from the hidden field the page
            # rendered; falls back to the current string if it is missing.
            shown_rw=(request.form.get("shown_rw", "").strip() or term.kinyarwanda),
            is_adjudication=False,
        )
        db.session.add(row)
        recompute_validation_status(term)
        db.session.commit()

        skipped = session.get("review_skipped", [])
        if term.id in skipped:
            skipped.remove(term.id)
            session["review_skipped"] = skipped

        extras = []
        if row.proposed_rw:
            extras.append("your alternative rendering")
        if row.note:
            extras.append("your comment")
        with_what = (" with " + " and ".join(extras)) if extras else ""
        # One <span> so the flex-layout flash box keeps the spaces between words.
        flash(Markup(
            '<span>Saved: <strong>{}</strong> scored <strong>{}</strong>{}. '
            '<a href="{}">Change it</a></span>'
        ).format(term.english, score, with_what,
                 url_for("review_term", term_id=term.id)), "success")
        return redirect(url_for("review_queue"))

    @app.route("/review/term/<int:term_id>/skip", methods=["POST"])
    @reviewer_required
    def review_skip(term_id):
        term = db.get_or_404(Term, term_id)
        skipped = session.get("review_skipped", [])
        if term.id not in skipped:
            skipped.append(term.id)
            session["review_skipped"] = skipped
        return redirect(url_for("review_queue"))

    @app.route("/review/history")
    @reviewer_required
    def review_history():
        """Every term this reviewer has scored, newest first, one row per term
        with the latest blind score. Rows link back to the term so a verdict
        can be changed through the usual confirmation, until the round closes."""
        reviewer = _actual_user()
        rows = (TermReview.query
                .filter_by(reviewer=reviewer.code, is_adjudication=False)
                .order_by(TermReview.reviewed_at.desc(), TermReview.id.desc())
                .all())
        seen = {}
        for r in rows:
            entry = seen.get(r.term_id)
            if entry is None:
                seen[r.term_id] = {"row": r, "times": 1}
            else:
                entry["times"] += 1
        entries = list(seen.values())
        eligible, remaining, _ = _review_queue_for(reviewer)
        return render_template(
            "review/history.html",
            reviewer=reviewer,
            entries=entries,
            done=len(eligible) - len(remaining),
            total=len(eligible),
            rescored=sum(1 for e in entries if e["times"] > 1),
            round_closed=app.config["REVIEW_ROUND_CLOSED"],
        )

    @app.route("/review/guideline")
    @reviewer_required
    def review_guideline():
        path = os.path.join(app.root_path, "REVIEWER_GUIDELINE.md")
        html = None
        text = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            try:
                import markdown  # optional dependency; falls back to plain text
                html = markdown.markdown(text)
            except ImportError:
                html = None
        return render_template("review/guideline.html", html=html, text=text)

    return app


# ---------------------------------------------------------------------------
# Run the app
# ---------------------------------------------------------------------------
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)