"""
The read-only backup of the review round (scripts/export_scores.py).

It copies every term, every score ever saved, the suggestions and the reviewer
accounts (never their password hashes) into a dated folder outside the
repository, with a readable sheet of each reviewer's latest blind scores and a
manifest of checksums. It refuses to write inside the repository and never
writes an empty backup.
"""
import csv
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from models import db, Reviewer, Term, TermReview

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("export_scores", ROOT / "scripts" / "export_scores.py")
export_scores = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export_scores)

NOW = datetime(2026, 10, 1, 16, 12, tzinfo=timezone(timedelta(hours=-5)))


def _round(app):
    """Olive with two pilot terms: one re-scored, one with a comment and an alternative."""
    with app.app_context():
        olive = Reviewer(code="OU", username="olive", display_name="Olive Umuhoza",
                         must_change_password=False)
        olive.set_password("olive-pass-1234")
        a = Term(english="Test pilot term A", kinyarwanda="RW rendering A", corpus_version="v1",
                 pilot=True, published=False, domain="Obstetrics")
        b = Term(english="Test pilot term B", kinyarwanda="RW rendering B", corpus_version="v1",
                 pilot=True, published=False, domain="Pharmacology")
        db.session.add_all([olive, a, b])
        db.session.flush()
        t0 = datetime(2026, 9, 29, 18, 0)
        db.session.add_all([
            TermReview(term_id=a.id, reviewer="OU", score=3, shown_rw=a.kinyarwanda,
                       reviewed_at=t0),
            TermReview(term_id=a.id, reviewer="OU", score=4, shown_rw=a.kinyarwanda,
                       reviewed_at=t0 + timedelta(hours=1)),
            TermReview(term_id=b.id, reviewer="OU", score=2, shown_rw=b.kinyarwanda,
                       proposed_rw="=Alternative", note="-register is too formal",
                       reviewed_at=t0 + timedelta(hours=2)),
            TermReview(term_id=b.id, reviewer="CM", score=4, shown_rw=b.kinyarwanda,
                       is_adjudication=True, reviewed_at=t0 + timedelta(hours=3)),
        ])
        db.session.commit()
        return olive.password_hash


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_the_backup_holds_everything_and_the_sheet_shows_the_latest_scores(app, tmp_path):
    secret = _round(app)
    folder, manifest = export_scores.export(app.config["SQLALCHEMY_DATABASE_URI"],
                                            tmp_path, now=NOW)
    assert folder == tmp_path / "2026-10-01_1612"
    names = {"terms.csv", "term_reviews.csv", "suggestions.csv", "reviewers.csv",
             "latest_scores.csv", "manifest.json"}
    assert {p.name for p in folder.iterdir()} == names

    assert len(_read(folder / "term_reviews.csv")) == 4             # every row, replaced ones too
    terms = {t["english"]: t for t in _read(folder / "terms.csv")}
    assert terms["Test pilot term B"]["published"] == "false"                 # corpus terms included

    sheet = {(r["reviewer"], r["english"]): r for r in _read(folder / "latest_scores.csv")}
    assert set(sheet) == {("OU", "Test pilot term A"), ("OU", "Test pilot term B")}   # adjudication left out
    fluid, sedative = sheet[("OU", "Test pilot term A")], sheet[("OU", "Test pilot term B")]
    assert fluid["score"] == "4" and fluid["times_scored"] == "2"
    assert fluid["reviewer_name"] == "Olive Umuhoza" and fluid["shown_rw"] == "RW rendering A"
    assert sedative["proposed_rw"] == "'=Alternative"                      # shown as text, never run
    assert sedative["note"] == "'-register is too formal"
    assert sedative["rendering_changed_since"] == ""

    assert manifest["terms_scored_by_reviewer"] == {"OU": 2}


def test_running_a_backup_never_shows_how_anyone_scored(app, tmp_path, monkeypatch, capsys):
    """The terminal and the manifest carry counts only; the scores stay in the sheet."""
    _round(app)
    monkeypatch.setenv("DATABASE_URL", app.config["SQLALCHEMY_DATABASE_URI"])
    export_scores.main(["--out", str(tmp_path)])
    printed = capsys.readouterr().out
    assert "OU: 2" in printed
    assert "4:" not in printed and "2:" not in printed           # no score spread
    assert "register is too formal" not in printed and "Alternative" not in printed
    folder = next(tmp_path.iterdir())
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) == {"exported_at_utc", "exported_at_local", "database",
                             "files", "terms_scored_by_reviewer"}
    assert manifest["terms_scored_by_reviewer"] == {"OU": 2}


def test_no_password_hash_and_no_database_url_ever_leave(app, tmp_path):
    secret = _round(app)
    folder, _ = export_scores.export(app.config["SQLALCHEMY_DATABASE_URI"], tmp_path, now=NOW)
    assert "password_hash" not in _read(folder / "reviewers.csv")[0]
    for path in folder.iterdir():
        body = path.read_text(encoding="utf-8")
        assert secret not in body
        assert "sqlite:///" not in body


def test_the_manifest_checksums_match_the_files(app, tmp_path):
    _round(app)
    folder, _ = export_scores.export(app.config["SQLALCHEMY_DATABASE_URI"], tmp_path, now=NOW)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for name, info in manifest["files"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == info["sha256"]
    assert manifest["database"] == "sqlite"


def test_a_rendering_changed_after_scoring_is_flagged(app, tmp_path):
    _round(app)
    with app.app_context():
        term = Term.query.filter_by(english="Test pilot term B").one()
        term.kinyarwanda = "RW rendering B, edited"
        db.session.commit()
    folder, _ = export_scores.export(app.config["SQLALCHEMY_DATABASE_URI"], tmp_path, now=NOW)
    sheet = {r["english"]: r for r in _read(folder / "latest_scores.csv")}
    assert sheet["Test pilot term B"]["rendering_changed_since"] == "yes"
    assert sheet["Test pilot term A"]["rendering_changed_since"] == ""


def test_a_second_run_in_the_same_minute_gets_its_own_folder(app, tmp_path):
    _round(app)
    first, _ = export_scores.export(app.config["SQLALCHEMY_DATABASE_URI"], tmp_path, now=NOW)
    second, _ = export_scores.export(app.config["SQLALCHEMY_DATABASE_URI"], tmp_path, now=NOW)
    assert first != second and first.exists() and second.exists()


def test_it_refuses_to_write_inside_the_repository(app):
    _round(app)
    with pytest.raises(SystemExit):
        export_scores.export(app.config["SQLALCHEMY_DATABASE_URI"], ROOT / "backups", now=NOW)
    assert not (ROOT / "backups").exists()


def test_an_empty_database_writes_nothing(tmp_path):
    empty = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{empty}")
    db.metadata.create_all(engine)
    engine.dispose()
    with pytest.raises(SystemExit):
        export_scores.export(f"sqlite:///{empty}", tmp_path / "out", now=NOW)
    assert not (tmp_path / "out").exists()


def test_without_database_url_it_stops_with_instructions(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as stop:
        export_scores.database_uri()
    assert "DATABASE_PUBLIC_URL" in str(stop.value)
