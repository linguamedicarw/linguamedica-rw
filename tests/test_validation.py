"""
Validation-status tests for LinguaMedica RW.

These exercise the annotation schema (term_reviews) and the
recompute_validation_status() rules from the validation methodology (v2):

- Only blind scores count; adjudication rows are excluded by construction.
- A reviewer's judgment of a term they contributed is excluded.
- Only each reviewer's latest blind score counts (re-review replaces).
- Status: 0 qualifying -> unreviewed; 1 -> single; 2+ -> dual_agreed when
  at least two reviewers score 4 and none scores below 3, else dual_conflict.
- The database CHECK constraint keeps scores inside 1..4.
- Deleting a term deletes its reviews.
- Startup migrations are idempotent.

Run from the project root:   pytest
"""
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from models import db, Term, TermReview
from app import (
    recompute_validation_status,
    migrate_add_provenance_columns,
    migrate_add_suggestion_resolved,
    migrate_add_validation_status,
    migrate_fix_contributor_attribution,
    REVIEWER_NAMES,
)

CM_NAME = REVIEWER_NAMES["CM"]   # the curator; author of most terms
T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


def make_term(contributed_by=CM_NAME, english="Test term", kinyarwanda="Igerageza"):
    term = Term(english=english, kinyarwanda=kinyarwanda, contributed_by=contributed_by)
    db.session.add(term)
    db.session.commit()
    return term


def add_review(term, reviewer, score, minutes=0, adjudication=False, commit=True):
    row = TermReview(
        term_id=term.id,
        reviewer=reviewer,
        score=score,
        is_adjudication=adjudication,
        reviewed_at=T0 + timedelta(minutes=minutes),
    )
    db.session.add(row)
    if commit:
        db.session.commit()
    return row


# --- Status transitions --------------------------------------------------

def test_new_term_is_unreviewed(app):
    with app.app_context():
        term = make_term()
        assert term.validation_status == "unreviewed"
        assert recompute_validation_status(term) == "unreviewed"


def test_one_independent_score_gives_single(app):
    with app.app_context():
        term = make_term(contributed_by=CM_NAME)
        add_review(term, "OU", 4)
        assert recompute_validation_status(term) == "single"


def test_two_fours_give_dual_agreed(app):
    with app.app_context():
        term = make_term(contributed_by=CM_NAME)
        add_review(term, "OU", 4)
        add_review(term, "YV", 4, minutes=1)
        assert recompute_validation_status(term) == "dual_agreed"


def test_four_and_three_at_two_reviewers_is_conflict(app):
    # At exactly two reviewers the threshold rule equals unanimity on 4.
    with app.app_context():
        term = make_term(contributed_by=CM_NAME)
        add_review(term, "OU", 4)
        add_review(term, "YV", 3, minutes=1)
        assert recompute_validation_status(term) == "dual_conflict"


def test_three_reviewers_two_fours_and_a_three_is_agreed(app):
    # Past two reviewers: at least two 4s and nothing below 3 qualifies.
    with app.app_context():
        term = make_term(contributed_by="Someone Else")
        add_review(term, "CM", 4)
        add_review(term, "OU", 4, minutes=1)
        add_review(term, "YV", 3, minutes=2)
        assert recompute_validation_status(term) == "dual_agreed"


def test_three_reviewers_with_a_two_is_conflict(app):
    with app.app_context():
        term = make_term(contributed_by="Someone Else")
        add_review(term, "CM", 4)
        add_review(term, "OU", 4, minutes=1)
        add_review(term, "YV", 2, minutes=2)
        assert recompute_validation_status(term) == "dual_conflict"


# --- Author exclusion ------------------------------------------------------

def test_author_cannot_validate_own_term(app):
    with app.app_context():
        term = make_term(contributed_by=CM_NAME)
        add_review(term, "CM", 4)
        assert recompute_validation_status(term) == "unreviewed"


def test_author_exclusion_leaves_other_reviewers_counting(app):
    with app.app_context():
        term = make_term(contributed_by=CM_NAME)
        add_review(term, "CM", 4)
        add_review(term, "OU", 4, minutes=1)
        # CM is excluded, OU alone counts -> single, not dual_agreed
        assert recompute_validation_status(term) == "single"


# --- Adjudication exclusion ----------------------------------------------

def test_adjudication_rows_never_enter_status(app):
    with app.app_context():
        term = make_term(contributed_by=CM_NAME)
        add_review(term, "OU", 4)
        add_review(term, "YV", 4, minutes=1, adjudication=True)
        # Only the blind OU score counts.
        assert recompute_validation_status(term) == "single"


# --- Re-review replaces, never stacks ------------------------------------

def test_latest_blind_score_replaces_earlier_one(app):
    with app.app_context():
        term = make_term(contributed_by=CM_NAME)
        add_review(term, "OU", 2)               # first pass
        add_review(term, "OU", 4, minutes=5)    # revised later
        add_review(term, "YV", 4, minutes=6)
        assert recompute_validation_status(term) == "dual_agreed"


# --- Database constraints --------------------------------------------------

def test_check_constraint_rejects_score_zero(app):
    with app.app_context():
        term = make_term()
        with pytest.raises(IntegrityError):
            add_review(term, "OU", 0)
        db.session.rollback()


def test_check_constraint_rejects_score_five(app):
    with app.app_context():
        term = make_term()
        with pytest.raises(IntegrityError):
            add_review(term, "OU", 5)
        db.session.rollback()


def test_deleting_a_term_deletes_its_reviews(app):
    with app.app_context():
        term = make_term()
        add_review(term, "OU", 4)
        add_review(term, "YV", 3, minutes=1)
        term_id = term.id
        db.session.delete(term)
        db.session.commit()
        assert TermReview.query.filter_by(term_id=term_id).count() == 0


# --- Migrations ------------------------------------------------------------

def test_startup_migrations_are_idempotent(app):
    with app.app_context():
        for _ in range(2):
            migrate_add_provenance_columns(app)
            migrate_add_suggestion_resolved(app)
            migrate_add_validation_status(app)
            migrate_fix_contributor_attribution(app)
        term = make_term()
        assert term.validation_status == "unreviewed"