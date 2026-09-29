"""
Visitors are counted on the site itself: anonymously, once a day, people only.

A public page read by a browser adds one PageView row with the Kigali day and
hour, the page, a day-long anonymous code for the browser, and the country,
device, browser language and referring site. No cookie is set and no IP
address is stored. Bots, link previews, prefetches, error pages and signed-in
admins and reviewers are never counted. The dashboard summarises the last 30
days, and both the page views and the full search log download as CSV.
"""
import sqlite3
from datetime import date, timedelta

import pytest

import app as app_module
from app import migrate_add_search_visitor_column, visitor_code
from models import db, PageView, Reviewer, SearchLog

PHONE = ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/128.0 Mobile Safari/537.36")
LAPTOP = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/17.6 Safari/605.1.15")


def _visit(client, path="/", ua=PHONE, ip="41.186.10.20", **headers):
    base = {"User-Agent": ua, "CF-Connecting-IP": ip, "CF-IPCountry": "RW",
            "Accept-Language": "rw-RW,rw;q=0.9,en;q=0.8"}
    base.update(headers)
    return client.get(path, headers={k: v for k, v in base.items() if v is not None})


def _views(app):
    with app.app_context():
        return PageView.query.order_by(PageView.id).all()


def test_a_visit_is_counted_with_what_the_dashboard_needs(app, client):
    r = _visit(client, "/about", Referer="https://www.linkedin.com/feed/")
    assert r.status_code == 200
    # The counter adds no cookie: the only one is the site's existing session
    # cookie, which carries the form-security token on every page.
    assert all(c.startswith("session=") for c in r.headers.getlist("Set-Cookie"))
    (view,) = _views(app)
    assert view.path == "/about"
    assert view.country == "RW" and view.device == "mobile" and view.language == "rw"
    assert view.referrer == "linkedin.com"
    assert len(view.visitor) == 16 and view.visitor != "41.186.10.20"
    assert 0 <= view.hour <= 23 and isinstance(view.day, date)


def test_one_browser_is_one_visitor_for_the_whole_day(app, client):
    _visit(client, "/")
    _visit(client, "/about")
    _visit(client, "/", ua=LAPTOP, ip="102.22.1.9")
    views = _views(app)
    assert len(views) == 3
    assert len({v.visitor for v in views}) == 2
    assert {v.device for v in views} == {"mobile", "desktop"}


def test_the_code_changes_every_day_and_never_contains_the_address():
    today, tomorrow = date(2026, 10, 1), date(2026, 10, 2)
    a = visitor_code("41.186.10.20", PHONE, today, "secret")
    assert a == visitor_code("41.186.10.20", PHONE, today, "secret")
    assert a != visitor_code("41.186.10.20", PHONE, tomorrow, "secret")
    assert a != visitor_code("41.186.10.20", PHONE, today, "another secret")
    assert "41.186" not in a and len(a) == 16


@pytest.mark.parametrize("ua", [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "WhatsApp/2.24.19.86 A",
    "facebookexternalhit/1.1",
    "Mozilla/5.0 (compatible; LinkedInBot/1.0)",
    "curl/8.5.0",
    "python-requests/2.32",
    "",
])
def test_bots_and_link_previews_are_not_counted(app, client, ua):
    _visit(client, "/", ua=ua)
    assert _views(app) == []


def test_prefetches_errors_and_other_pages_are_not_counted(app, client):
    _visit(client, "/", **{"Sec-Purpose": "prefetch"})
    _visit(client, "/no-such-page")
    _visit(client, "/api/terms")
    _visit(client, "/admin/login")
    _visit(client, "/review/login")
    client.post("/suggest", data={"english_word": "Tachycardia"},
                headers={"User-Agent": PHONE})
    assert _views(app) == []


def test_signed_in_admins_and_reviewers_are_not_counted(app, admin_client):
    _visit(admin_client, "/")
    admin_client.get("/admin/logout")
    with app.app_context():
        r = Reviewer(code="OU", username="olive", display_name="Olive",
                     must_change_password=False)
        r.set_password("olive-pass-1234")
        db.session.add(r)
        db.session.commit()
    reviewer = app.test_client()
    reviewer.post("/review/login", data={"username": "olive", "password": "olive-pass-1234"})
    _visit(reviewer, "/about")
    assert _views(app) == []


def test_utm_source_names_a_shared_link_and_the_site_itself_is_not_a_referrer(app, client):
    _visit(client, "/?utm_source=linkedin-article")
    _visit(client, "/about", Referer="https://linguamedica.rw/")
    _visit(client, "/", ua=LAPTOP, **{"CF-IPCountry": "XX", "Accept-Language": None})
    views = _views(app)
    assert views[0].referrer == "linkedin-article"
    assert views[1].referrer is None
    assert views[2].country is None and views[2].language is None


def test_a_counting_failure_never_reaches_the_visitor(app, client, monkeypatch):
    def broken(_req):
        raise RuntimeError("counter down")
    monkeypatch.setattr(app_module, "request_visitor_code", broken)
    r = _visit(client, "/")
    assert r.status_code == 200 and b"<html" in r.data.lower()
    assert _views(app) == []


def test_searches_carry_the_same_visitor_code_as_the_visit(app, client):
    _visit(client, "/")
    client.post("/api/log-search", json={"query": "pneumonia", "results_count": 1},
                headers={"User-Agent": PHONE, "CF-Connecting-IP": "41.186.10.20"})
    with app.app_context():
        log = SearchLog.query.filter_by(query_text="pneumonia").one()
        assert log.visitor == PageView.query.one().visitor


def test_searches_made_while_signed_in_have_no_visitor_code(app, admin_client):
    admin_client.post("/api/log-search", json={"query": "pneumonia", "results_count": 1})
    with app.app_context():
        assert SearchLog.query.filter_by(query_text="pneumonia").one().visitor is None


def test_the_dashboard_summarises_visitors_and_searches(app, client, admin_client):
    anonymous = app.test_client()
    _visit(anonymous, "/", Referer="https://www.google.com/")
    _visit(anonymous, "/about")
    _visit(anonymous, "/", ua=LAPTOP, ip="102.22.1.9", **{"CF-IPCountry": "US"})
    with app.app_context():
        old = PageView(day=date.today() - timedelta(days=45), hour=9, path="/",
                       visitor="0" * 16)
        db.session.add(old)
        db.session.add(SearchLog(query_text="malaria", results_count=1, source="web"))
        db.session.add(SearchLog(query_text="solidarity", results_count=0, source="web"))
        db.session.commit()
    html = admin_client.get("/admin").get_data(as_text=True)
    assert 'id="visitors"' in html
    assert "Visitors today" in html and "Last 30 days" in html
    assert "Rwanda" in html and "United States" in html and "google.com" in html
    assert "Kinyarwanda" in html
    assert "50% of them found nothing" in html
    assert "Counted since" in html
    # the old searches carry no visitor code, so no share is claimed yet
    assert "of visitors searched" not in html


def test_the_share_of_visitors_who_search(app, admin_client):
    anonymous = app.test_client()
    _visit(anonymous, "/")
    _visit(anonymous, "/", ua=LAPTOP, ip="102.22.1.9")
    anonymous.post("/api/log-search", json={"query": "pneumonia", "results_count": 1},
                   headers={"User-Agent": PHONE, "CF-Connecting-IP": "41.186.10.20"})
    html = admin_client.get("/admin").get_data(as_text=True)
    assert "50% of visitors searched." in html


def test_csv_downloads_are_for_the_admin_only(app, client, admin_client):
    anonymous = app.test_client()
    _visit(anonymous, "/")
    with app.app_context():
        db.session.add(SearchLog(query_text="=HYPERLINK(1)", results_count=0, source="web"))
        db.session.commit()
    assert anonymous.get("/admin/analytics/page-views.csv").status_code == 302
    views = admin_client.get("/admin/analytics/page-views.csv")
    assert views.status_code == 200 and views.mimetype == "text/csv"
    assert "attachment" in views.headers["Content-Disposition"]
    lines = views.get_data(as_text=True).splitlines()
    assert lines[0].startswith("day,hour_kigali,page,visitor_of_the_day")
    assert len(lines) == 2 and "41.186" not in lines[1]
    searches = admin_client.get("/admin/analytics/searches.csv").get_data(as_text=True)
    assert "'=HYPERLINK(1)" in searches          # opened as text, never as a formula


def test_an_older_database_gains_the_search_visitor_column(tmp_path):
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE search_logs (id INTEGER PRIMARY KEY, query_text VARCHAR(300), "
                 "results_count INTEGER, source VARCHAR(20), searched_at DATETIME)")
    conn.execute("INSERT INTO search_logs (query_text, results_count) VALUES ('malaria', 1)")
    conn.commit()
    conn.close()

    class OldApp:
        config = {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"}

    migrate_add_search_visitor_column(OldApp)
    migrate_add_search_visitor_column(OldApp)                 # idempotent
    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(search_logs)")}
    assert "visitor" in cols
    assert conn.execute("SELECT visitor FROM search_logs").fetchone() == (None,)
    conn.close()
