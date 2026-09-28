"""
The editor's corrections reach the live site with a commit.

EDITOR_CORRECTIONS names, for each field it changes, the value it replaces.
At startup a field is updated only while it still holds that old value, so
the live database is corrected by the deploy, a fresh database starts
corrected from seed_data.py, and nothing edited by hand is overwritten.
"""
from app import (EDITOR_CORRECTIONS, migrate_apply_editor_corrections,
                 migrate_split_compound_entries)
from models import db, Term
from seed_data import STARTER_TERMS

SEED = {t["english"]: t for t in STARTER_TERMS}
NEW_VALUES = {(english, field): new
              for english, changes in EDITOR_CORRECTIONS
              for field, (_old, new) in changes.items()}


def _set_old_values(app):
    """Put the corrected entries back in the state they have on the live site."""
    with app.app_context():
        for english, changes in EDITOR_CORRECTIONS:
            term = Term.query.filter_by(english=english).first()
            for field, (old, _new) in changes.items():
                setattr(term, field, old)
        db.session.commit()


def _values(app):
    with app.app_context():
        return {
            (english, field): getattr(Term.query.filter_by(english=english).first(), field)
            for english, changes in EDITOR_CORRECTIONS for field in changes
        }


def test_the_seed_and_the_corrections_agree():
    """A fresh database and the corrected live one end in the same place."""
    for english, changes in EDITOR_CORRECTIONS:
        assert english in SEED, english
        for field, (old, new) in changes.items():
            assert SEED[english].get(field) == new, (english, field)
            assert old != new, (english, field)


def test_no_correction_touches_a_term_of_the_round(app):
    with app.app_context():
        for english, _changes in EDITOR_CORRECTIONS:
            term = Term.query.filter_by(english=english).first()
            assert term.corpus_version is None and term.published is True, english


def test_the_deploy_corrects_entries_still_in_their_old_state(app, capsys):
    _set_old_values(app)
    with app.app_context():
        migrate_apply_editor_corrections(app)
    out = capsys.readouterr().out
    assert "editor corrections applied" in out
    assert _values(app) == NEW_VALUES
    with app.app_context():
        hypertension = Term.query.filter_by(english="Hypertension").first()
        assert hypertension.kinyarwanda == "Umuvuduko ukabije w'amaraso"
        assert hypertension.example_rw == "Umurwayi yasuzumwe afite umuvuduko ukabije w'amaraso."
        assert Term.query.filter_by(english="Asthma").first().variants_rw == "Isemeka / Asima"
        assert (Term.query.filter_by(english="Diabetes").first().variants_rw
                == "Indwara y'igisukari / Igisukari / Gisukari")


def test_a_second_boot_changes_nothing_and_says_nothing(app, capsys):
    _set_old_values(app)
    with app.app_context():
        migrate_apply_editor_corrections(app)
        capsys.readouterr()
        before = _values(app)
        migrate_apply_editor_corrections(app)
    assert capsys.readouterr().out == ""
    assert _values(app) == before


def test_a_fresh_database_starts_corrected(app, capsys):
    capsys.readouterr()
    before = _values(app)
    with app.app_context():
        migrate_apply_editor_corrections(app)
    assert capsys.readouterr().out == ""
    assert _values(app) == before == NEW_VALUES


def test_a_field_edited_by_hand_is_left_as_it_is(app, capsys):
    _set_old_values(app)
    with app.app_context():
        asthma = Term.query.filter_by(english="Asthma").first()
        asthma.source = "Annie Chibwe consent form; edited in the admin panel"
        db.session.commit()
        migrate_apply_editor_corrections(app)
    out = capsys.readouterr().out
    assert "left out for Asthma: source" in out
    with app.app_context():
        asthma = Term.query.filter_by(english="Asthma").first()
        assert asthma.source == "Annie Chibwe consent form; edited in the admin panel"
        assert asthma.variants_rw == "Isemeka / Asima"      # the untouched field still moves


def test_the_older_split_migration_stays_quiet_about_later_variants(app, capsys):
    """Diabetes and Asthma were split on 19 Sep; their new variants are a later
    decision, not an edit that the split migration should warn about."""
    capsys.readouterr()
    with app.app_context():
        migrate_split_compound_entries(app)
    out = capsys.readouterr().out
    assert "'Diabetes'" not in out and "'Asthma'" not in out
    with app.app_context():
        assert (Term.query.filter_by(english="Diabetes").first().variants_rw
                == "Indwara y'igisukari / Igisukari / Gisukari")
