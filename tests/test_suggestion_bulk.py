"""
Acting on many suggestions at once.

Every suggestion card carries a tick box; one bar resolves or rejects all the
ticked cards, and the archive restores them the same way. Nothing is deleted
and every action can be undone from the other list, so there is no confirm
dialog. Each card also says whether its word is already in the dictionary.
"""
import re

from models import db, Suggestion


def _suggest(app, word, translation=None, resolved=False, status="pending"):
    with app.app_context():
        s = Suggestion(english_word=word, suggested_translation=translation,
                       resolved=resolved, status=status)
        db.session.add(s)
        db.session.commit()
        return s.id


def _state(app, sid):
    with app.app_context():
        s = db.session.get(Suggestion, sid)
        return s.resolved, s.status


def _bulk(admin_client, action, ids):
    return admin_client.post("/admin/suggestions/bulk",
                             data={"action": action, "ids": [str(i) for i in ids]},
                             follow_redirects=True)


def test_resolve_several_at_once(app, admin_client):
    a, b, c = (_suggest(app, w) for w in ("Tachycardia", "Bradycardia", "Syncope"))
    r = _bulk(admin_client, "resolve", [a, b])
    assert b"2 suggestions resolved." in r.data
    assert _state(app, a) == (True, "pending")
    assert _state(app, b) == (True, "pending")
    assert _state(app, c) == (False, "pending")


def test_reject_several_at_once_moves_them_to_the_archive(app, admin_client):
    a, b = _suggest(app, "Tachycardia"), _suggest(app, "Bradycardia")
    r = _bulk(admin_client, "reject", [a, b])
    assert b"2 suggestions rejected." in r.data
    assert _state(app, a) == (True, "rejected") and _state(app, b) == (True, "rejected")
    with app.app_context():
        assert "Rejected on" in db.session.get(Suggestion, a).admin_notes


def test_restore_several_from_the_archive(app, admin_client):
    a = _suggest(app, "Tachycardia", resolved=True)
    b = _suggest(app, "Bradycardia", resolved=True, status="rejected")
    r = _bulk(admin_client, "restore", [a, b])
    assert b"2 suggestions restored to the active list." in r.data
    assert _state(app, a) == (False, "pending")
    assert _state(app, b) == (False, "rejected")


def test_nothing_ticked_or_an_unknown_action_changes_nothing(app, admin_client):
    a = _suggest(app, "Tachycardia")
    assert b"tick at least one suggestion first" in _bulk(admin_client, "resolve", []).data
    assert b"tick at least one suggestion first" in _bulk(admin_client, "delete", [a]).data
    r = admin_client.post("/admin/suggestions/bulk",
                          data={"action": "resolve", "ids": ["abc", "99999"]},
                          follow_redirects=True)
    assert b"0 suggestions resolved." in r.data
    assert _state(app, a) == (False, "pending")


def test_only_the_admin_can_act_in_bulk(app, client):
    a = _suggest(app, "Tachycardia")
    r = client.post("/admin/suggestions/bulk", data={"action": "resolve", "ids": [str(a)]})
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]
    assert _state(app, a) == (False, "pending")


def test_a_single_reject_also_moves_the_card_to_the_archive(app, admin_client):
    a = _suggest(app, "Tachycardia")
    r = admin_client.post(f"/admin/suggestion/{a}/reject", follow_redirects=True)
    assert b"rejected and moved to the archive" in r.data
    assert _state(app, a) == (True, "rejected")


def test_every_card_has_a_tick_box_and_no_confirm_dialog(app, admin_client):
    a = _suggest(app, "Tachycardia")
    b = _suggest(app, "Bradycardia", resolved=True)
    html = admin_client.get("/admin").get_data(as_text=True)
    assert f'value="{a}" form="bulkActive"' in html
    assert f'value="{b}" form="bulkArchive"' in html
    assert 'id="bulkActive"' in html and 'id="bulkArchive"' in html
    # No dialogs around suggestions, which can always be restored...
    suggestions_part = html[html.index('id="suggestions"'):html.index("All Terms (")]
    assert "confirm(" not in suggestions_part
    # ...while deleting a term, which cannot be undone, still asks first.
    assert "Delete this term? This cannot be undone." in html
    assert re.search(r'src="/static/js/bulk-select\.js\?v=[0-9a-f]{10}"', html)


def test_cards_say_whether_the_word_is_already_in_the_dictionary(app, admin_client):
    asthma = _suggest(app, "asthma", "asima")
    vaccin = _suggest(app, "vaccin", "urukingo")               # misspelt: no match
    pair = _suggest(app, "miscarriage/abortion", "gukuramo inda")
    round_term = _suggest(app, "Dermoscopy")                  # waiting in the round
    html = admin_client.get("/admin").get_data(as_text=True)

    def box(sid):
        return re.search(rf'value="{sid}" form="bulkActive"\s+aria-label="[^"]*"\s+'
                         rf'data-in-dictionary="(\d)"', html).group(1)

    assert box(asthma) == "1" and box(pair) == "1"
    assert box(vaccin) == "0" and box(round_term) == "0"
    assert "Already in the dictionary:" in html and "Gusemeka" in html
    assert "In the review round, not public yet:" in html
    assert "Already in the dictionary (2)" in html


def test_the_selection_script_is_served_and_never_asks_to_confirm(client):
    r = client.get("/static/js/bulk-select.js")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "confirm(" not in body and "shiftKey" in body
