"""The public suggestion form drops spam quietly and lets real suggestions through."""
from models import Suggestion

THANKS = "Thank you! Your suggestion has been submitted for review."


def _count(app):
    with app.app_context():
        return Suggestion.query.count()


def test_a_real_suggestion_still_goes_through(app, client):
    r = client.post("/suggest", data={"english_word": "Seizure", "context": "Interpretation"},
                    follow_redirects=True)
    assert THANKS in r.get_data(as_text=True)
    assert _count(app) == 1


def test_the_trap_field_drops_a_bot_quietly(app, client):
    r = client.post("/suggest", data={"english_word": "Seizure", "website": "anything"},
                    follow_redirects=True)
    assert THANKS in r.get_data(as_text=True)          # the bot sees the usual thank-you
    assert _count(app) == 0


def test_a_link_in_any_field_drops_the_submission(app, client):
    spam = (
        {"english_word": "* * * SCAM SERVICE 24/7: https://example.cc/ * * *"},
        {"english_word": "Seizure", "context": '<a href="http://example.ru/">payment</a>'},
        {"english_word": "Seizure", "suggested_translation": "see www.example.com"},
    )
    for data in spam:
        r = client.post("/suggest", data=data, follow_redirects=True)
        assert THANKS in r.get_data(as_text=True)
    assert _count(app) == 0


def test_an_empty_or_overlong_term_is_not_stored(app, client):
    client.post("/suggest", data={"english_word": "   "})
    client.post("/suggest", data={"english_word": "x" * 201})
    assert _count(app) == 0


def test_the_form_carries_the_hidden_trap_field(client):
    page = client.get("/suggest").get_data(as_text=True)
    assert 'name="website"' in page
    assert 'tabindex="-1"' in page and 'aria-hidden="true"' in page


def test_one_visitor_is_slowed_down_after_five_suggestions_a_minute(monkeypatch, tmp_path):
    # Rate limits are off in the shared fixture, so this test builds its own app
    # with them on, and starts and ends with a clean count.
    from app import create_app, limiter
    monkeypatch.delenv("REVIEWER_ACCOUNTS", raising=False)
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'limit.db'}",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": True,
        "REVIEW_PHASE": "pilot",
        "REVIEW_CORPUS": "v1",
        "REVIEW_RESULTS_EXPECTED": "November",
        "REVIEW_ROUND_CLOSED": False,
    })
    limiter.reset()
    try:
        client = app.test_client()
        me = {"CF-Connecting-IP": "203.0.113.7"}
        for i in range(5):
            r = client.post("/suggest", data={"english_word": f"Term {i}"}, headers=me)
            assert r.status_code in (302, 303)
        r = client.post("/suggest", data={"english_word": "Term 5"}, headers=me)
        assert r.status_code == 429
        assert "several suggestions in a short time" in r.get_data(as_text=True)
        other = client.post("/suggest", data={"english_word": "Term 6"},
                            headers={"CF-Connecting-IP": "203.0.113.8"})
        assert other.status_code in (302, 303)            # another visitor is not affected
        assert client.get("/suggest", headers=me).status_code == 200   # reading is never limited
    finally:
        limiter.reset()
