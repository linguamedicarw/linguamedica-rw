"""
From a suggestion to a dictionary entry, without housekeeping.

"Approve & Add" opens the add form carrying the suggestion's id. Saving the
term resolves that suggestion, and any other active suggestion for the same
word; cancelling changes nothing. The add form also refuses a headword the
dictionary already has, public or waiting in a review round, so a suggestion
or a zero-result search can never create a duplicate.
"""
from urllib.parse import parse_qs, urlparse

from models import db, Suggestion, Term


def _suggest(app, word, translation=None):
    with app.app_context():
        s = Suggestion(english_word=word, suggested_translation=translation)
        db.session.add(s)
        db.session.commit()
        return s.id


def _suggestion(app, sid):
    with app.app_context():
        s = db.session.get(Suggestion, sid)
        return s.resolved, s.status, s.admin_notes, s.resolved_at


def _count(app, english):
    with app.app_context():
        return Term.query.filter(db.func.lower(Term.english) == english.lower()).count()


def _approve(admin_client, sid):
    r = admin_client.post(f"/admin/suggestion/{sid}/approve")
    assert r.status_code == 302
    return r.headers["Location"]


def _new_term(english):
    # Test data only: the Kinyarwanda here is a placeholder, not a rendering.
    return {"english": english, "kinyarwanda": "Ijambo ry'isuzuma"}


def test_approve_opens_the_form_carrying_the_suggestion(app, admin_client):
    sid = _suggest(app, "Tachycardia", "Ijambo ry'isuzuma")
    location = _approve(admin_client, sid)
    query = parse_qs(urlparse(location).query)
    assert urlparse(location).path == "/admin/add"
    assert query["suggestion"] == [str(sid)] and query["english"] == ["Tachycardia"]
    page = admin_client.get(location).get_data(as_text=True)
    assert f'name="suggestion_id" value="{sid}"' in page
    assert "existingHeadword" not in page


def test_saving_the_term_resolves_its_suggestion(app, admin_client):
    sid = _suggest(app, "Tachycardia")
    location = _approve(admin_client, sid)
    r = admin_client.post(location, data={**_new_term("Tachycardia"), "suggestion_id": sid},
                          follow_redirects=True)
    assert b"Its suggestion was marked resolved." in r.data
    resolved, status, notes, resolved_at = _suggestion(app, sid)
    assert resolved is True and status == "approved" and resolved_at is not None
    assert "Added to the dictionary as 'Tachycardia'" in notes
    assert _count(app, "Tachycardia") == 1


def test_other_suggestions_for_the_same_word_close_too(app, admin_client):
    first = _suggest(app, "Tachycardia")
    second = _suggest(app, " tachycardia ")
    other = _suggest(app, "Bradycardia")
    location = _approve(admin_client, first)
    r = admin_client.post(location, data={**_new_term("Tachycardia"), "suggestion_id": first},
                          follow_redirects=True)
    assert b"The 2 suggestions for it were marked resolved." in r.data
    assert _suggestion(app, first)[0] is True
    assert _suggestion(app, second)[0] is True
    assert _suggestion(app, other)[:2] == (False, "pending")


def test_a_word_added_by_hand_also_closes_its_suggestions(app, admin_client):
    sid = _suggest(app, "Tachycardia")
    admin_client.post("/admin/add", data=_new_term("Tachycardia"))
    assert _suggestion(app, sid)[:2] == (True, "approved")


def test_cancelling_the_form_changes_nothing(app, admin_client):
    sid = _suggest(app, "Tachycardia")
    admin_client.get(_approve(admin_client, sid))
    admin_client.get("/admin")                      # the Cancel link
    assert _suggestion(app, sid)[:2] == (False, "pending")
    assert _count(app, "Tachycardia") == 0


def test_a_word_already_in_the_dictionary_is_never_added_twice(app, admin_client):
    page = admin_client.get("/admin/add?english=pneumonia").get_data(as_text=True)
    assert "is already in the dictionary" in page and "/admin/edit/" in page
    r = admin_client.post("/admin/add", data=_new_term("pneumonia"))
    assert r.status_code == 302 and "/admin/edit/" in r.headers["Location"]
    assert _count(app, "Pneumonia") == 1


def test_a_word_in_the_review_round_is_never_added(app, admin_client):
    page = admin_client.get("/admin/add?english=Dermoscopy").get_data(as_text=True)
    assert "is one of the terms in the review round" in page
    r = admin_client.post("/admin/add", data=_new_term("Dermoscopy"))
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin")
    assert _count(app, "Dermoscopy") == 1
    with app.app_context():
        term = Term.query.filter_by(english="Dermoscopy").one()
        assert term.published is False and term.corpus_version == "v1"


def test_an_existing_word_offers_to_resolve_the_suggestion(app, admin_client):
    sid = _suggest(app, "pneumonia", "umusonga")
    page = admin_client.get(_approve(admin_client, sid)).get_data(as_text=True)
    assert "is already in the dictionary" in page
    assert f"/admin/suggestion/{sid}/resolve" in page
    admin_client.post(f"/admin/suggestion/{sid}/resolve")
    assert _suggestion(app, sid)[0] is True


def test_a_bad_suggestion_id_is_ignored(app, admin_client):
    r = admin_client.post("/admin/add?suggestion=abc",
                          data={**_new_term("Tachycardia"), "suggestion_id": "abc"},
                          follow_redirects=True)
    assert r.status_code == 200
    assert _count(app, "Tachycardia") == 1
