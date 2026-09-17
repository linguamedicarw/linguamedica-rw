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


# --- Select-then-save, feedback, history, round closing, progress ----------

def test_score_page_offers_choices_and_a_save_button(reviewer_client, app):
    with app.app_context():
        term_id = _make_term("Choice term", "Ijambo ry'amahitamo")
    r = reviewer_client.get(f"/review/term/{term_id}")
    assert r.status_code == 200
    assert r.data.count(b'<input type="radio" name="score"') == 4   # four choices, one form
    assert b"Save and go to the next term" in r.data
    assert b"Choose a score, then press Save" in r.data
    assert b"Scored so far (0)" in r.data
    assert b"today 0 of 10" in r.data


def test_saving_without_a_score_stores_nothing(reviewer_client, app):
    with app.app_context():
        term_id = _make_term("Empty term", "Ijambo ridafite amanota")
    r = reviewer_client.post(f"/review/term/{term_id}/score",
                             data={"note": "typed but no score"}, follow_redirects=True)
    assert r.status_code == 200
    assert b"Choose a score first" in r.data
    with app.app_context():
        assert TermReview.query.filter_by(term_id=term_id).count() == 0


def test_saved_message_names_the_term_and_offers_to_change_it(reviewer_client, app):
    with app.app_context():
        term_id = _make_term("Named term", "Ijambo rifite izina")
    r = reviewer_client.post(f"/review/term/{term_id}/score",
                             data={"score": "3", "note": "register", "shown_rw": "Ijambo rifite izina"},
                             follow_redirects=True)
    assert r.status_code == 200
    assert b"Saved: <strong>Named term</strong> scored <strong>3</strong> with your comment." in r.data
    assert f'href="/review/term/{term_id}">Change it</a>'.encode() in r.data


def test_history_lists_latest_score_per_term_with_change_links(reviewer_client, app):
    with app.app_context():
        a = _make_term("History A", "Ijambo A")
        b = _make_term("History B", "Ijambo B")
    reviewer_client.post(f"/review/term/{a}/score", data={"score": "2"})
    reviewer_client.post(f"/review/term/{b}/score", data={"score": "4"})
    reviewer_client.post(f"/review/term/{a}/score", data={"score": "3", "confirm_replace": "yes"})
    r = reviewer_client.get("/review/history")
    assert r.status_code == 200
    body = r.data.decode()
    assert "History A" in body and "History B" in body
    # one row per term (the pending "Saved" message also names it), latest score shown, re-score counted
    assert body.count("<td><strong>History A</strong></td>") == 1
    assert 'score-pill-3">3</span> <span class="label-hint">(changed 1' in body
    assert f'href="/review/term/{a}"' in body
    assert "2 terms scored, 1 changed after the first score" in body


def test_previous_term_link_points_at_the_last_scored_term(reviewer_client, app):
    with app.app_context():
        first = _make_term("First scored", "Ijambo rya mbere")
        second = _make_term("Second shown", "Ijambo rya kabiri")
    reviewer_client.post(f"/review/term/{first}/score", data={"score": "4"})
    r = reviewer_client.get(f"/review/term/{second}")
    assert f'href="/review/term/{first}"'.encode() in r.data
    assert b"Previous term: First scored" in r.data


def test_today_counter_moves_after_a_score(reviewer_client, app):
    with app.app_context():
        a = _make_term("Today A", "Uyu munsi A")
        b = _make_term("Today B", "Uyu munsi B")
    reviewer_client.post(f"/review/term/{a}/score", data={"score": "4"})
    r = reviewer_client.get(f"/review/term/{b}")
    assert b"today 1 of 10" in r.data
    assert b"Scored so far (1)" in r.data


def test_closed_round_refuses_scores_and_hides_change_links(app, client, reviewer):
    with app.app_context():
        term_id = _make_term("Closed term", "Ijambo rifunze")
        db.session.add(TermReview(term_id=term_id, reviewer=REVIEWER_CODE, score=4,
                                  shown_rw="Ijambo rifunze"))
        db.session.commit()
    app.config["REVIEW_ROUND_CLOSED"] = True
    client.post("/review/login", data={"username": "olive", "password": "olive-pass"})
    page = client.get(f"/review/term/{term_id}")
    assert b"The round is closed" in page.data
    assert b"Save and go to the next term" not in page.data
    r = client.post(f"/review/term/{term_id}/score",
                    data={"score": "1", "confirm_replace": "yes"}, follow_redirects=True)
    assert b"The round is closed" in r.data
    with app.app_context():
        rows = TermReview.query.filter_by(term_id=term_id).all()
        assert [x.score for x in rows] == [4]          # nothing added
    hist = client.get("/review/history")
    assert b">View<" in hist.data and b">Change<" not in hist.data


def test_admin_dashboard_shows_reviewer_progress(admin_client, app, reviewer):
    with app.app_context():
        term_id = _make_term("Progress term", "Ijambo ry'iterambere")
        db.session.add(TermReview(term_id=term_id, reviewer=REVIEWER_CODE, score=4))
        db.session.commit()
    r = admin_client.get("/admin")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Reviewer progress" in body
    assert REVIEWER_NAME in body
    assert "progress-days" in body
    assert "/admin/reviewer/" in body and "new_password" in body


def test_admin_can_reset_a_reviewer_password(admin_client, client, app, reviewer):
    r = admin_client.post(f"/admin/reviewer/{reviewer}/password",
                          data={"new_password": "a-much-longer-secret-42"}, follow_redirects=True)
    assert b"Password updated for" in r.data
    admin_client.get("/admin/logout")
    assert client.post("/review/login", data={"username": "olive", "password": "olive-pass"}).status_code == 200
    ok = client.post("/review/login", data={"username": "olive", "password": "a-much-longer-secret-42"})
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/review")


def test_admin_password_reset_rejects_short_passwords(admin_client, client, app, reviewer):
    r = admin_client.post(f"/admin/reviewer/{reviewer}/password",
                          data={"new_password": "short"}, follow_redirects=True)
    assert b"at least 12 characters" in r.data
    admin_client.get("/admin/logout")
    still = client.post("/review/login", data={"username": "olive", "password": "olive-pass"})
    assert still.status_code == 302


def test_reviewer_cannot_reset_passwords(reviewer_client, reviewer):
    assert reviewer_client.post(f"/admin/reviewer/{reviewer}/password",
                                data={"new_password": "a-much-longer-secret-42"}).status_code == 403
