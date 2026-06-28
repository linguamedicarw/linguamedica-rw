#!/usr/bin/env python3
"""
export_terms.py - one-way snapshot of the verified term store.

WHAT THIS DOES
    Reads the live `terms` table (read-only) and writes two canonical files:
        data/terms.json   full-fidelity record, UTF-8, deterministic order
        data/terms.csv    same data, flat, for spreadsheets and quick diffs

WHY IT EXISTS (Phase 1)
    The live PostgreSQL store stays the single source of truth for the public
    dictionary. This script derives a versioned, reproducible copy that git
    tracks. The RAG build reads these files, never the live DB. Because the flow
    is one-way (DB to files, never files to DB), the two cannot drift apart or
    corrupt each other, and the baseline can never be altered by this step.

GUARANTEES
    Read-only. Issues a single SELECT. No INSERT/UPDATE/DELETE, no schema
    changes. Your production data cannot be modified by running this.

    Deterministic. Same data in gives byte-identical files out. A re-run with no
    term changes produces no git diff, so every diff is a real change.

    Safe to re-run. If the query returns zero terms (almost always a bad
    DATABASE_URL, not an empty DB), it aborts WITHOUT writing, so it can never
    clobber good canonical files with an empty export.

HOW TO RUN (locally, against production)
    1. Grab the PUBLIC Postgres URL from Railway:
       Postgres service -> Variables -> DATABASE_PUBLIC_URL
    2. From the repo root, with your venv active:
           export DATABASE_URL="<paste the public URL>"
           python scripts/export_terms.py
           unset DATABASE_URL
    The internal *.railway.internal URL only resolves inside Railway; locally
    you need the public one.

A NOTE ON VERIFICATION STATUS
    Every row in `terms` is admin-verified by construction (only the admin can
    insert terms). Pending user candidates live in the separate `suggestions`
    queue, not here. So this file is the verified store, full stop. There is no
    per-term status column today; if tiering is introduced later, that is a
    schema migration and this exporter gains a field then.
"""

import csv
import json
import os
import sys
from pathlib import Path

# Make the app's modules importable no matter where this is run from.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from flask import Flask          # noqa: E402  (import after sys.path tweak)
from sqlalchemy import select    # noqa: E402
from models import db, Term      # noqa: E402

DATA_DIR = REPO_ROOT / "data"
JSON_PATH = DATA_DIR / "terms.json"
CSV_PATH = DATA_DIR / "terms.csv"
SCHEMA_VERSION = "1.0"

# Fixed field order - keeps JSON keys and CSV columns stable across runs.
FIELDS = [
    "id",
    "english",
    "kinyarwanda",
    "example_en",
    "example_rw",
    "etymology",
    "category",
    "contributed_by",
    "source",
    "date_added",
    "created_at",
]


def database_uri():
    """Build the SQLAlchemy URI, normalized to the psycopg3 driver (matches prod)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit(
            "DATABASE_URL is not set.\n"
            "Set it to the PUBLIC Railway Postgres URL "
            "(Postgres service -> Variables -> DATABASE_PUBLIC_URL), e.g.:\n"
            '    export DATABASE_URL="postgresql://..."\n'
            "then run this script again."
        )
    # Railway hands out postgres:// or postgresql://; production uses psycopg3.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def make_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


def term_to_row(term):
    """One term to an ordered dict, with timestamps as ISO strings or None."""
    return {
        "id": term.id,
        "english": term.english,
        "kinyarwanda": term.kinyarwanda,
        "example_en": term.example_en,
        "example_rw": term.example_rw,
        "etymology": term.etymology,
        "category": term.category,
        "contributed_by": term.contributed_by,
        "source": term.source,
        "date_added": term.date_added.isoformat() if term.date_added else None,
        "created_at": term.created_at.isoformat() if term.created_at else None,
    }


def write_json(rows):
    payload = {
        "schema_version": SCHEMA_VERSION,
        "term_count": len(rows),
        "terms": rows,
    }
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        # ensure_ascii=False so Kinyarwanda renders as real characters, not \u escapes.
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")  # trailing newline for clean diffs


def write_csv(rows):
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        # lineterminator="\n" so the file matches the repo's LF convention.
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row[k] is None else row[k]) for k in FIELDS})


def main():
    app = make_app()
    with app.app_context():
        stmt = select(Term).order_by(Term.english.asc(), Term.id.asc())
        terms = db.session.execute(stmt).scalars().all()

    rows = [term_to_row(t) for t in terms]
    # Re-sort in Python with casefold so ordering is identical on every machine,
    # independent of the database's collation.
    rows.sort(key=lambda r: (r["english"].casefold(), r["id"]))

    if not rows:
        sys.exit(
            "No terms returned. This almost always means DATABASE_URL points\n"
            "somewhere unexpected. Aborting WITHOUT writing so the existing\n"
            "canonical files are left untouched."
        )

    DATA_DIR.mkdir(exist_ok=True)
    write_json(rows)
    write_csv(rows)

    print(f"Exported {len(rows)} terms.")
    print(f"  {JSON_PATH.relative_to(REPO_ROOT)}")
    print(f"  {CSV_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()