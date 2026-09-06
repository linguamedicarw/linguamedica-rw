"""
Reviewer-interface tests for LinguaMedica RW.

Covers the reviewer account model, the separation between admin and
reviewer sessions, queue eligibility (anchor exclusion, author exclusion),
scoring with shown_rw recorded and validation status recomputed, the
re-score confirmation, skipping, and backward compatibility of old admin
sessions with the prefixed user ids.

Run from the project root:   pytest
"""
import pytest

from models import db, Term, TermReview, Reviewer, Admin
from app import REVIEW_EXCLUDED_TERMS, REVIEWER_NAMES


REVIEWER_CODE = "OU"
REVIEWER_NAME = REVIEWER_NAMES[REVIEWER_CODE]


@pytest.fixture
def reviewer(app):
    """A reviewer account for Olive (code OU), created directly in the DB."""
    with app.app_context():
        r = Reviewer(code=REVIEWER_CODE, display_name=REVIEWER_NAME, username="olive")
        r.set_password("olive-pass")
        db.session.add(r)
        db.session.commit()
        return r.id


@pytest.fixture
def reviewer_client(client, reviewer):
    client.post("/review/login", data={"username": "olive", "password": "olive-pass"})
    return client


def _make_term(english, kinyarwanda, contributed_by="Christophe Mumaragishyika"):
    t = Term(english=english, kinyarwanda=kinyarwanda, contributed_by=contributed_by)
    db.session.add(t)
    db.session.commit()
    return t.id


# --- Access separation -----------------------------------------------------

def test_review_queue_requires_reviewer_login(client):
    r = client.get("/review")
    assert r.status_code == 302
    assert "/review/login" in r.headers["Location"]


def test_reviewer_login_succeeds(client, reviewer):
    r = client.post("/review/login", data={"username": "olive", "password": "olive-pass"})
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/review")


def test_reviewer_login_rejects_wrong_password(client, reviewer):
    r = client.post("/review/login", data={"username": "olive", "password": "nope"})
    assert r.status_code == 200
    assert b"Invalid username or password" in r.data


def test_reviewer_cannot_reach_admin_routes(reviewer_client):
    assert reviewer_client.get("/admin").status_code == 403
    assert reviewer_client.get("/admin/add").status_code == 403


def test_admin_cannot_reach_review_routes(admin_client):
    assert admin_client.get("/review").status_code == 403


def test_legacy_bare_integer_admin_session_still_loads(client, app):
    # Sessions created before prefixed ids stored just "1". They must still work.
    with app.app_context():
        admin_id = Admin.query.first().id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True
    assert client.get("/admin").status_code == 200


# --- Queue eligibility -----------------------------------------------------

def test_anchor_terms_are_never_shown(reviewer_client, app):
    with app.app_context():
        anchor = next(iter(REVIEW_EXCLUDED_TERMS))
        term_id = _make_term(anchor, "Ikigereranyo")
    assert reviewer_client.get(f"/review/term/{term_id}").status_code == 403


def test_reviewer_never_sees_own_contributed_term(reviewer_client, app):
    with app.app_context():
        term_id = _make_term("Own term", "Ijambo ryanjye", contributed_by=REVIEWER_NAME)
    assert reviewer_client.get(f"/review/term/{term_id}").status_code == 403


def test_queue_shows_progress_and_the_term(reviewer_client, app):
    with app.app_context():
        term_id = _make_term("Queue term", "Ijambo ryo ku murongo")
    r = reviewer_client.get(f"/review/term/{term_id}")
    assert r.status_code == 200
    assert b"Queue term" in r.data
    assert b"Ijambo ryo ku murongo" in r.data
    assert b"scored 0 of" in r.data


def test_queue_never_shows_contributor_or_etymology(reviewer_client, app):
    with app.app_context():
        t = Term(english="Neutral term", kinyarwanda="Ijambo",
                 contributed_by="Someone Visible", etymology="A tell-tale etymology")
        db.session.add(t)
        db.session.commit()
        term_id = t.id
    r = reviewer_client.get(f"/review/term/{term_id}")
    assert b"Someone Visible" not in r.data
    assert b"tell-tale etymology" not in r.data


# --- Scoring ---------------------------------------------------------------

def test_scoring_records_row_with_shown_rw_and_recomputes_status(reviewer_client, app):
    with app.app_context():
        term_id = _make_term("Scored term", "Ijambo ryasuzumwe")
    r = reviewer_client.post(f"/review/term/{term_id}/score", data={
        "score": "4",
        "note": "clean",
        "shown_rw": "Ijambo ryasuzumwe",
    })
    assert r.status_code == 302
    with app.app_context():
        row = TermReview.query.filter_by(term_id=term_id).one()
        assert row.reviewer == REVIEWER_CODE
        assert row.score == 4
        assert row.shown_rw == "Ijambo ryasuzumwe"
        assert row.is_adjudication is False
        assert db.session.get(Term, term_id).validation_status == "single"


def test_out_of_range_score_is_rejected(reviewer_client, app):
    with app.app_context():
        term_id = _make_term("Range term", "Ijambo")
    assert reviewer_client.post(f"/review/term/{term_id}/score",
                                data={"score": "9"}).status_code == 400
    assert reviewer_client.post(f"/review/term/{term_id}/score",
                                data={"score": "abc"}).status_code == 400
    with app.app_context():
        assert TermReview.query.filter_by(term_id=term_id).count() == 0


def test_rescoring_needs_explicit_confirmation(reviewer_client, app):
    with app.app_context():
        term_id = _make_term("Twice term", "Ijambo kabiri")
    reviewer_client.post(f"/review/term/{term_id}/score", data={"score": "2"})
    # Second attempt without confirmation: refused, no new row.
    r = reviewer_client.post(f"/review/term/{term_id}/score", data={"score": "4"})
    assert r.status_code == 302
    with app.app_context():
        assert TermReview.query.filter_by(term_id=term_id).count() == 1
    # With confirmation: new row, and the page had warned about the earlier score.
    page = reviewer_client.get(f"/review/term/{term_id}")
    assert b"You scored this term" in page.data
    reviewer_client.post(f"/review/term/{term_id}/score",
                         data={"score": "4", "confirm_replace": "yes"})
    with app.app_context():
        rows = TermReview.query.filter_by(term_id=term_id).all()
        assert len(rows) == 2                       # earlier score stays in the record
        assert sorted(r.score for r in rows) == [2, 4]


def test_skip_moves_term_to_the_end_of_the_queue(reviewer_client, app):
    # The queue is empty of eligible seed terms only if we score them all, so
    # instead assert on ordering: after skipping the current term, /review
    # must redirect somewhere other than that term.
    r = reviewer_client.get("/review")
    assert r.status_code == 302
    first = r.headers["Location"].rstrip("/").split("/")[-1]
    reviewer_client.post(f"/review/term/{first}/skip")
    r2 = reviewer_client.get("/review")
    nxt = r2.headers["Location"].rstrip("/").split("/")[-1]
    assert nxt != first


def test_guideline_page_renders_without_the_markdown_package(reviewer_client):
    # No REVIEWER_GUIDELINE.md in the test tree and no hard dependency on
    # the markdown package: the page must still load with a fallback notice.
    r = reviewer_client.get("/review/guideline")
    assert r.status_code == 200
    assert b"Reviewer guideline" in r.data
