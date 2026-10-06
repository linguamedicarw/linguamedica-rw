#!/usr/bin/env python3
"""
export_scores.py - read-only backup of the review round, with a sheet to read.

WHAT THIS DOES
    Copies the round's data from the live database into a dated folder on this
    computer, outside the repository:

        latest_scores.csv   THE SHEET TO READ: one row per reviewer and term,
                            with the latest blind score, the Kinyarwanda that
                            was on screen, the alternative and the comment
        terms.csv           every term, published and corpus, every column
        term_reviews.csv    every score ever saved, replaced ones included
        suggestions.csv     the suggestion queue
        reviewers.csv       the reviewer accounts, WITHOUT password hashes
        manifest.json       when it ran, row counts, a SHA-256 per file so two
                            backups can be compared later, and how many terms
                            each reviewer has scored (never the scores)

WHY IT EXISTS
    The scores live in one place, the Railway database. A dated copy on your
    computer protects the round against loss, and two copies side by side show
    whether anything changed between them. The dashboard counts scores but does
    not show them; latest_scores.csv does, without touching the live site.

GUARANTEES
    Read-only. On Postgres the transaction is opened READ ONLY, so the database
    itself refuses any write. Only SELECTs are issued.

    Never inside the repository. The default folder is
    ~/LinguaMedica-backups/<date_time>/, and an --out inside the repo is
    refused, so research data cannot be committed to the public repo by mistake.

    Never an empty backup. Zero terms almost always means a wrong DATABASE_URL;
    it stops before creating anything.

    No secrets. Password hashes are not exported, and the database URL is never
    printed or written.

HOW TO RUN (locally, against production; same steps as export_terms.py)
    From the repo root, with your venv active:
        export DATABASE_URL="<paste the PUBLIC Postgres URL from Railway>"
        python scripts/export_scores.py
        unset DATABASE_URL
    Optional: --out /some/folder to put the dated folder somewhere else.

READING latest_scores.csv
    Running a backup shows only how many terms each reviewer has scored, as the
    dashboard does, so a weekly backup never shows you how anyone is scoring.
    When it is time to read the scores (after the pilot, after the round), open
    the sheet in Numbers or Excel and filter on the reviewer column. Cells that
    begin with = + - or @ get a leading apostrophe so a spreadsheet shows them
    as text instead of running them; the other files keep the raw values.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, select, text          # noqa: E402
from models import Reviewer, Suggestion, Term, TermReview    # noqa: E402

DEFAULT_ROOT = Path.home() / "LinguaMedica-backups"
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

LATEST_FIELDS = [
    "reviewer", "reviewer_name", "english", "shown_rw", "score",
    "proposed_rw", "note", "reviewed_at", "times_scored",
    "rendering_changed_since", "pilot", "domain", "corpus_version", "term_id",
]


def database_uri():
    """The SQLAlchemy URI from DATABASE_URL, normalised to psycopg3 (as production)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit(
            "DATABASE_URL is not set.\n"
            "Set it to the PUBLIC Railway Postgres URL "
            "(Postgres service -> Variables -> DATABASE_PUBLIC_URL), e.g.:\n"
            '    export DATABASE_URL="postgresql://..."\n'
            "then run this script again."
        )
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _raw(value):
    """A cell for the backup files: the value itself, dates as ISO text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _safe(value):
    """A cell for the sheet people open: never read as a formula."""
    cell = str(_raw(value))
    return "'" + cell if cell.startswith(FORMULA_START) else cell


def read_round(uri):
    """Every table the round needs, as lists of dicts. Read-only."""
    engine = create_engine(uri)
    reviewer_cols = [c for c in Reviewer.__table__.c if c.name != "password_hash"]
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                # First statement of the transaction: the server now refuses writes.
                conn.execute(text("SET TRANSACTION READ ONLY"))
            data = {
                "terms": Term.__table__,
                "term_reviews": TermReview.__table__,
                "suggestions": Suggestion.__table__,
            }
            tables = {}
            for name, table in data.items():
                rows = conn.execute(select(table).order_by(table.c.id))
                tables[name] = ([c.name for c in table.c],
                                [dict(r._mapping) for r in rows])
            rows = conn.execute(select(*reviewer_cols).order_by(Reviewer.__table__.c.id))
            tables["reviewers"] = ([c.name for c in reviewer_cols],
                                   [dict(r._mapping) for r in rows])
            conn.rollback()
    finally:
        engine.dispose()
    return tables, engine.dialect.name


def latest_scores(tables):
    """One row per reviewer and term: the latest blind score and its context."""
    _, terms = tables["terms"]
    _, reviews = tables["term_reviews"]
    _, reviewers = tables["reviewers"]
    term_by_id = {t["id"]: t for t in terms}
    names = {r["code"]: r["display_name"] for r in reviewers}

    history = defaultdict(list)
    for r in reviews:
        if not r["is_adjudication"]:
            history[(r["reviewer"], r["term_id"])].append(r)

    rows = []
    for (code, term_id), scored in history.items():
        scored.sort(key=lambda r: (r["reviewed_at"] or datetime.min, r["id"]))
        last = scored[-1]
        term = term_by_id.get(term_id, {})
        changed = (bool(last["shown_rw"]) and bool(term.get("kinyarwanda"))
                   and last["shown_rw"].strip() != term["kinyarwanda"].strip())
        rows.append({
            "reviewer": code,
            "reviewer_name": names.get(code, ""),
            "english": term.get("english", ""),
            "shown_rw": last["shown_rw"],
            "score": last["score"],
            "proposed_rw": last["proposed_rw"],
            "note": last["note"],
            "reviewed_at": last["reviewed_at"],
            "times_scored": len(scored),
            "rendering_changed_since": "yes" if changed else "",
            "pilot": term.get("pilot"),
            "domain": term.get("domain"),
            "corpus_version": term.get("corpus_version"),
            "term_id": term_id,
        })
    rows.sort(key=lambda r: (r["reviewer"], not r["pilot"], r["domain"] or "",
                             (r["english"] or "").casefold()))
    return rows


def _write_csv(path, fields, rows, cell):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(fields)
        for row in rows:
            writer.writerow([cell(row.get(k)) for k in fields])
    return len(rows)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target_folder(out_root, now):
    out_root = Path(out_root).expanduser().resolve()
    if out_root == REPO_ROOT or REPO_ROOT in out_root.parents:
        sys.exit("Refusing to write inside the repository: research data must never "
                 "be committed. Choose a folder outside it, or leave out --out.")
    stamp = now.strftime("%Y-%m-%d_%H%M")
    folder = out_root / stamp
    if folder.exists():
        folder = out_root / now.strftime("%Y-%m-%d_%H%M%S")
    return folder


def export(uri, out_root=DEFAULT_ROOT, now=None):
    """Write the backup and the sheet; return (folder, manifest)."""
    now = now or datetime.now().astimezone()
    folder = _target_folder(out_root, now)
    tables, dialect = read_round(uri)
    if not tables["terms"][1]:
        sys.exit("No terms returned. This almost always means DATABASE_URL points\n"
                 "somewhere unexpected. Stopping WITHOUT writing anything.")

    folder.mkdir(parents=True)
    files = {}
    for name in ("terms", "term_reviews", "suggestions", "reviewers"):
        fields, rows = tables[name]
        path = folder / f"{name}.csv"
        files[path.name] = {"rows": _write_csv(path, fields, rows, _raw)}
    latest = latest_scores(tables)
    path = folder / "latest_scores.csv"
    files[path.name] = {"rows": _write_csv(path, LATEST_FIELDS, latest, _safe)}
    for name in files:
        files[name]["sha256"] = _sha256(folder / name)

    # How many terms each reviewer has scored, as the dashboard shows it. Never
    # the scores themselves: running a backup must not show anyone how the
    # reviewers are scoring. That stays in latest_scores.csv until it is opened.
    terms_scored = dict(sorted(Counter(r["reviewer"] for r in latest).items()))
    manifest = {
        "exported_at_utc": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "exported_at_local": now.isoformat(timespec="seconds"),
        "database": dialect,
        "files": files,
        "terms_scored_by_reviewer": terms_scored,
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return folder, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only backup of the review round.")
    parser.add_argument("--out", default=str(DEFAULT_ROOT),
                        help="parent folder for the dated backup (outside the repo)")
    args = parser.parse_args(argv)

    folder, manifest = export(database_uri(), args.out)
    print(f"Backup written to {folder}")
    for name, info in manifest["files"].items():
        print(f"  {name:<20} {info['rows']:>5} rows")
    print("Terms scored so far:")
    if not manifest["terms_scored_by_reviewer"]:
        print("  none yet")
    for code, n in manifest["terms_scored_by_reviewer"].items():
        print(f"  {code}: {n}")
    print("The scores themselves are in latest_scores.csv, unopened until you choose to read them.")


if __name__ == "__main__":
    main()
