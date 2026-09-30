"""
Skipping a term in the review queue.

Skip moves a term to the back of the line and records nothing. Skipped terms
come back in the order they were skipped, and skipping one again sends it to
the back, so Skip keeps moving even when every term left has been skipped.
When a term is the only one left, the page says so instead of reloading it
silently.
"""
import pytest

from models import db, Reviewer, Term, TermReview
from app import REVIEWER_NAMES


@pytest.fixture
def olive(app, client):
    with app.app_context():
        r = Reviewer(code="OU", display_name=REVIEWER_NAMES["OU"], username="olive",
                     must_change_password=False)
        r.set_password("olive-pass")
        db.session.add(r)
        db.session.commit()
    client.post("/review/login", data={"username": "olive", "password": "olive-pass"})
    return client


def _only_these_left(app, *words):
    """Pilot terms for `words`, with every other term already scored by OU,
    so her queue holds exactly these."""
    with app.app_context():
        ids = []
        for word in words:
            t = Term(english=word, kinyarwanda=f"{word} rw",
                     contributed_by="Christophe Mumaragishyika",
                     corpus_version="v1", pilot=True, published=False)
            db.session.add(t)
            db.session.flush()
            ids.append(t.id)
        for t in Term.query.filter(~Term.id.in_(ids)).all():
            db.session.add(TermReview(term_id=t.id, reviewer="OU", score=4,
                                      shown_rw=t.kinyarwanda, is_adjudication=False))
        db.session.commit()
        return dict(zip(ids, words))


def _shown(client):
    """The term the queue serves next."""
    location = client.get("/review").headers["Location"]
    return int(location.rstrip("/").split("/")[-1])


def _skip(client, term_id, **kwargs):
    return client.post(f"/review/term/{term_id}/skip", **kwargs)


def test_skip_keeps_moving_when_every_term_left_was_skipped(app, olive):
    names = _only_these_left(app, "Tachycardia", "Bradycardia", "Syncope")
    seen = []
    for _ in range(7):
        term_id = _shown(olive)
        seen.append(names[term_id])
        _skip(olive, term_id)
    # Every press moves on, and the three terms keep rotating in one order.
    assert all(a != b for a, b in zip(seen, seen[1:]))
    assert sorted(seen[:3]) == sorted(names.values())
    assert seen[3:6] == seen[:3] and seen[6] == seen[0]


def test_skipped_terms_come_back_in_the_order_they_were_skipped(app, olive):
    _only_these_left(app, "Tachycardia", "Bradycardia", "Syncope")
    first = _shown(olive)
    _skip(olive, first)
    second = _shown(olive)
    _skip(olive, second)
    third = _shown(olive)
    _skip(olive, third)
    assert len({first, second, third}) == 3
    assert _shown(olive) == first
    _skip(olive, first)                    # skipped again: to the back
    assert _shown(olive) == second


def test_scoring_a_skipped_term_takes_it_out_of_the_rotation(app, olive):
    _only_these_left(app, "Tachycardia", "Bradycardia")
    a = _shown(olive)
    _skip(olive, a)
    b = _shown(olive)
    _skip(olive, b)
    assert _shown(olive) == a
    olive.post(f"/review/term/{a}/score", data={"score": "3"})
    assert _shown(olive) == b


def test_the_only_term_left_says_so_instead_of_reloading_silently(app, olive):
    names = _only_these_left(app, "Tachycardia")
    (only,) = names
    r = _skip(olive, only, follow_redirects=True)
    assert b"This is the only term left in your queue" in r.data
    assert _shown(olive) == only


def test_with_other_terms_waiting_skip_says_nothing_special(app, olive):
    _only_these_left(app, "Tachycardia", "Bradycardia")
    a = _shown(olive)
    r = _skip(olive, a, follow_redirects=True)
    assert b"only term left" not in r.data
    assert _shown(olive) != a
