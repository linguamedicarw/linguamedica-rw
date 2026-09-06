"""
Medical Dictionary — Main Application

This is the heart of the app. It:
1. Creates and configures the Flask app
2. Sets up authentication (so only you can admin)
3. Defines all the routes (URLs) users can visit
4. Handles search, suggestions, and admin operations

Security features:
- CSRF protection on all forms (Flask-WTF)
- Rate limiting on login route (Flask-Limiter)
- Content-Security-Policy header
- All credentials from environment variables
"""

import os
import hashlib
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, abort, session
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import Config
from models import db, Term, TermReview, Suggestion, SearchLog, Admin, Reviewer
from sqlalchemy import func


# ---------------------------------------------------------------------------
# Helper — validate post-login redirect targets (prevents open redirects)
# ---------------------------------------------------------------------------
def is_safe_redirect_target(target):
    """Only allow redirects to local, relative paths — never off-site."""
    if not target:
        return False
    parsed = urlparse(target)
    # Must be a relative path: no scheme, no host, single leading slash
    return (
        not parsed.scheme
        and not parsed.netloc
        and target.startswith("/")
        and not target.startswith("//")
    )


# ---------------------------------------------------------------------------
# Database Migration — Add provenance columns to existing terms table
# ---------------------------------------------------------------------------
def _pg_add_columns_if_missing(table, columns):
    """Idempotently add columns on Postgres via ADD COLUMN IF NOT EXISTS.

    A safe no-op when the columns already exist. Wrapped in try/except so a
    hiccup never blocks startup — the app still boots on the existing schema.
    """
    from sqlalchemy import text
    try:
        with db.engine.begin() as conn:
            for name, ddl in columns:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}"
                ))
    except Exception as exc:
        print(f"[migrate] Postgres column check skipped for {table}: {exc}")


def migrate_add_provenance_columns(app):
    """Add contributed_by, source, and date_added columns if they don't exist."""
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('postgresql'):
        _pg_add_columns_if_missing("terms", [
            ("contributed_by", "VARCHAR(200) DEFAULT 'Christophe Mumaragishyika'"),
            ("source", "VARCHAR(300)"),
            ("date_added", "TIMESTAMP"),
        ])
        return
    if not db_uri.startswith('sqlite'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(terms)")
    existing = {row[1] for row in cursor.fetchall()}
    if 'contributed_by' not in existing:
        cursor.execute(
            "ALTER TABLE terms ADD COLUMN contributed_by VARCHAR(200) "
            "DEFAULT 'Christophe Mumaragishyika'"
        )
    if 'source' not in existing:
        cursor.execute("ALTER TABLE terms ADD COLUMN source VARCHAR(300)")
    if 'date_added' not in existing:
        cursor.execute("ALTER TABLE terms ADD COLUMN date_added DATETIME")
    conn.commit()
    conn.close()


def migrate_add_suggestion_resolved(app):
    """Add resolved and resolved_at columns to suggestions if they don't exist."""
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('postgresql'):
        _pg_add_columns_if_missing("suggestions", [
            ("resolved", "BOOLEAN DEFAULT FALSE"),
            ("resolved_at", "TIMESTAMP"),
        ])
        return
    if not db_uri.startswith('sqlite'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(suggestions)")
    existing = {row[1] for row in cursor.fetchall()}
    if 'resolved' not in existing:
        cursor.execute(
            "ALTER TABLE suggestions ADD COLUMN resolved BOOLEAN DEFAULT 0"
        )
    if 'resolved_at' not in existing:
        cursor.execute(
            "ALTER TABLE suggestions ADD COLUMN resolved_at DATETIME"
        )
    conn.commit()
    conn.close()


# Known contributor corrections. Three early community-suggested terms were
# seeded with the default author in `contributed_by`; the true contributor was
# only recorded in each row's `source`. This restores correct attribution.
# Guarded so a later deliberate edit is never overwritten (see function below).
DEFAULT_CONTRIBUTOR = "Christophe Mumaragishyika"
CONTRIBUTOR_CORRECTIONS = {
    "Palliative care": "Aimable Uwimana (Mugenzi)",
    "Interview (research methodology)": "Benithe Himbazwa",
    "Health management": "Benithe Himbazwa",
}


def migrate_fix_contributor_attribution(app):
    """Restore correct contributor attribution on the community-suggested terms.

    Idempotent and safe on every startup. Only rows still holding the default
    author (or NULL) are corrected, so any later deliberate change to a term's
    contributor is preserved rather than forced back on the next boot.
    """
    try:
        changed = 0
        for english, author in CONTRIBUTOR_CORRECTIONS.items():
            term = Term.query.filter_by(english=english).first()
            if term and term.contributed_by in (DEFAULT_CONTRIBUTOR, None):
                term.contributed_by = author
                changed += 1
        if changed:
            db.session.commit()
            print(f"[migrate] corrected contributor attribution on {changed} term(s)")
    except Exception as exc:
        db.session.rollback()
        print(f"[migrate] contributor attribution correction skipped: {exc}")


def migrate_add_validation_status(app):
    """Add the computed validation_status column to terms if it doesn't exist.

    Existing rows are backfilled with 'unreviewed', which is exactly true:
    no review rows exist yet. Idempotent and safe to run on every startup.
    """
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('postgresql'):
        _pg_add_columns_if_missing("terms", [
            ("validation_status",
             "VARCHAR(20) NOT NULL DEFAULT 'unreviewed'"),
        ])
        return
    if not db_uri.startswith('sqlite'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(terms)")
    existing = {row[1] for row in cursor.fetchall()}
    if 'validation_status' not in existing:
        cursor.execute(
            "ALTER TABLE terms ADD COLUMN validation_status VARCHAR(20) "
            "NOT NULL DEFAULT 'unreviewed'"
        )
    conn.commit()
    conn.close()


def migrate_add_shown_rw(app):
    """Add term_reviews.shown_rw if it doesn't exist.

    Records the exact Kinyarwanda string a reviewer saw when scoring, so the
    stimulus is auditable and a genuinely blind round remains possible later.
    Idempotent and safe on every startup.
    """
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('postgresql'):
        _pg_add_columns_if_missing("term_reviews", [
            ("shown_rw", "VARCHAR(200)"),
        ])
        return
    if not db_uri.startswith('sqlite'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(term_reviews)")
    existing = {row[1] for row in cursor.fetchall()}
    if 'shown_rw' not in existing:
        cursor.execute("ALTER TABLE term_reviews ADD COLUMN shown_rw VARCHAR(200)")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Validation status — computed from term_reviews, never set by hand
# ---------------------------------------------------------------------------
# Stable reviewer ids mapped to the contributor names used in
# terms.contributed_by. This mapping is what lets the recompute exclude
# a reviewer's judgment of a term they themselves contributed. Add a new
# reviewer's entry here BEFORE they start reviewing, or author-exclusion
# cannot see them.
REVIEWER_NAMES = {
    "CM": "Christophe Mumaragishyika",
    "OU": "Olive Umuhoza",
    "YV": "Yvette Nkurunziza",
}


def recompute_validation_status(term):
    """Recompute term.validation_status from its blind review rows.

    Rules (validation methodology v2):
    - Only blind scores count. Adjudication rows are excluded.
    - A reviewer's judgment of a term they contributed is excluded.
    - Only each reviewer's latest blind score counts, so a re-review
      replaces the earlier one rather than stacking.
    - Status:
        0 qualifying reviews -> unreviewed
        1                    -> single
        2 or more            -> dual_agreed when at least two reviewers
                                score 4 and none scores below 3 (this is
                                identical to unanimity at exactly two
                                reviewers), otherwise dual_conflict

    The caller is responsible for db.session.commit().
    """
    rows = (
        TermReview.query
        .filter_by(term_id=term.id, is_adjudication=False)
        .order_by(TermReview.reviewed_at.asc(), TermReview.id.asc())
        .all()
    )
    latest = {}
    for r in rows:
        author_name = REVIEWER_NAMES.get(r.reviewer)
        if author_name and term.contributed_by and author_name == term.contributed_by:
            continue  # authors cannot validate their own terms
        latest[r.reviewer] = r.score  # later rows overwrite: latest wins

    scores = list(latest.values())
    if not scores:
        status = "unreviewed"
    elif len(scores) == 1:
        status = "single"
    else:
        fours = sum(1 for s in scores if s == 4)
        status = "dual_agreed" if (fours >= 2 and min(scores) >= 3) else "dual_conflict"

    term.validation_status = status
    return status


# Terms used as worked anchor examples in REVIEWER_GUIDELINE.md. A reviewer
# who has seen a term scored in the guideline would score it the same way
# in the queue, so these never appear in the scoring queue.
REVIEW_EXCLUDED_TERMS = {
    "Anemia",
    "Malaria",
    "Tuberculosis",
    "Bone tuberculosis",
    "Uterine prolapse",
    "Stomach ache",
}


# ---------------------------------------------------------------------------
# Access control — admin and reviewer are different kinds of session
# ---------------------------------------------------------------------------
def _actual_user():
    return current_user._get_current_object() if current_user.is_authenticated else None


def admin_required(view):
    """Only an Admin session may pass. Reviewers get 403, guests get login."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _actual_user()
        if user is None:
            return redirect(url_for("admin_login", next=request.path))
        if not isinstance(user, Admin):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def reviewer_required(view):
    """Only a Reviewer session may pass. Admins get 403, guests get login."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _actual_user()
        if user is None:
            return redirect(url_for("review_login", next=request.path))
        if not isinstance(user, Reviewer):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def _seed_reviewers():
    """Create reviewer accounts from REVIEWER_ACCOUNTS if they don't exist.

    Format: 'CODE:username:password;CODE:username:password'
    e.g.    'OU:olive:secret;YV:yvette:secret'
    Display names come from REVIEWER_NAMES. Existing accounts are never
    modified here, so rotating a password means deleting and recreating.
    Returns the number of accounts created.
    """
    raw = os.environ.get("REVIEWER_ACCOUNTS", "").strip()
    if not raw:
        return 0
    created = 0
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        if len(parts) != 3:
            print(f"[reviewers] skipping malformed entry: {chunk!r}")
            continue
        code, username, password = (p.strip() for p in parts)
        if not (code and username and password):
            print(f"[reviewers] skipping incomplete entry: {chunk!r}")
            continue
        if Reviewer.query.filter(
            db.or_(Reviewer.code == code, Reviewer.username == username)
        ).first():
            continue
        r = Reviewer(code=code, username=username,
                     display_name=REVIEWER_NAMES.get(code, code))
        r.set_password(password)
        db.session.add(r)
        created += 1
    return created


# ---------------------------------------------------------------------------
# Extensions — module-level singletons, bound to each app via init_app().
# (Factory pattern: the app can be created more than once — e.g. in tests —
#  without re-instantiating these, which also avoids Flask-Limiter weakref
#  errors under repeated app creation.)
# ---------------------------------------------------------------------------
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)


# ---------------------------------------------------------------------------
# App Factory
# ---------------------------------------------------------------------------
def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # Set up Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "admin_login"
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        # Session ids are 'admin:<id>' or 'reviewer:<id>'. A bare integer is
        # an admin session from before reviewer accounts existed.
        kind, _, raw = str(user_id).partition(":")
        if not raw:
            kind, raw = "admin", kind
        try:
            pk = int(raw)
        except ValueError:
            return None
        if kind == "reviewer":
            return db.session.get(Reviewer, pk)
        if kind == "admin":
            return db.session.get(Admin, pk)
        return None

    # ---------------------------------------------------------------
    # Security headers
    # ---------------------------------------------------------------
    @app.after_request
    def set_security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.errorhandler(429)
    def ratelimit_handler(e):
        # API endpoints get a JSON 429; everything else gets the friendly page
        if request.path.startswith("/api/"):
            return jsonify({"error": "Too many requests. Please slow down."}), 429
        flash("Too many login attempts. Please wait a minute and try again.", "danger")
        return render_template("admin/login.html"), 429

    # Create database tables, migrate, and auto-seed new terms
    with app.app_context():
        db.create_all()
        migrate_add_provenance_columns(app)
        migrate_add_suggestion_resolved(app)
        migrate_add_validation_status(app)
        migrate_add_shown_rw(app)
        migrate_fix_contributor_attribution(app)

        from seed_data import STARTER_TERMS, ADMIN_USERNAME, ADMIN_PASSWORD

        added = 0
        for term_data in STARTER_TERMS:
            if not Term.query.filter_by(english=term_data["english"]).first():
                db.session.add(Term(**term_data))
                added += 1

        admin_created = False
        if not Admin.query.filter_by(username=ADMIN_USERNAME).first():
            admin = Admin(username=ADMIN_USERNAME)
            admin.set_password(ADMIN_PASSWORD)
            db.session.add(admin)
            admin_created = True

        reviewers_created = _seed_reviewers()

        # Commit if anything was staged — not only when new terms were added.
        # Otherwise a freshly-created admin (e.g. after rotating ADMIN_USERNAME)
        # would be silently rolled back and you'd be locked out.
        if added > 0 or admin_created or reviewers_created:
            db.session.commit()
            if added > 0:
                print(f"Auto-seed: added {added} new terms (total: {Term.query.count()})")
            if reviewers_created:
                print(f"[reviewers] created {reviewers_created} reviewer account(s)")

    # -------------------------------------------------------------------
    # PUBLIC ROUTES
    # -------------------------------------------------------------------

    @app.route("/")
    def index():
        terms = Term.query.order_by(Term.english.asc()).all()
        recent = Term.query.order_by(Term.created_at.desc()).limit(10).all()
        terms_json = [t.to_dict() for t in terms]
        return render_template(
            "index.html",
            terms_json=terms_json,
            recent_terms=recent,
            total_count=len(terms)
        )

    @app.route("/suggest", methods=["GET", "POST"])
    def suggest():
        if request.method == "POST":
            suggestion = Suggestion(
                english_word=request.form.get("english_word", "").strip(),
                suggested_translation=request.form.get("suggested_translation", "").strip() or None,
                context=request.form.get("context", "").strip() or None,
                submitter_email=request.form.get("email", "").strip() or None,
            )
            db.session.add(suggestion)
            db.session.commit()
            flash("Thank you! Your suggestion has been submitted for review.", "success")
            return redirect(url_for("index"))
        return render_template("suggest.html")

    @app.route("/about")
    def about():
        return render_template("about.html")

    # -------------------------------------------------------------------
    # API ROUTES (CSRF-exempt — no cookie auth)
    # -------------------------------------------------------------------

    @app.route("/api/terms")
    @csrf.exempt
    def api_terms_route():
        terms = Term.query.order_by(Term.english.asc()).all()
        return jsonify([t.to_dict() for t in terms])

    @app.route("/api/search")
    @csrf.exempt
    @limiter.limit("30 per minute")
    def api_search_route():
        query = request.args.get("q", "").strip().lower()
        if not query:
            return jsonify([])
        results = Term.query.filter(
            db.or_(
                Term.english.ilike(f"%{query}%"),
                Term.kinyarwanda.ilike(f"%{query}%")
            )
        ).all()
        # Log the API search
        log = SearchLog(
            query_text=query,
            results_count=len(results),
            source="api"
        )
        db.session.add(log)
        db.session.commit()
        return jsonify([t.to_dict() for t in results])

    @app.route("/api/log-search", methods=["POST"])
    @csrf.exempt
    @limiter.limit("30 per minute")
    def api_log_search():
        """
        Called by the public search page JS (debounced).
        Logs the query and how many results it returned.
        """
        data = request.get_json(silent=True) or {}
        query = (data.get("query") or "").strip().lower()
        results_count = data.get("results_count", 0)
        # Match the frontend's 4-char floor so the noise filter holds even if
        # something calls this endpoint directly.
        if not query or len(query) < 4:
            return jsonify({"ok": True})
        log = SearchLog(
            query_text=query,
            results_count=int(results_count),
            source="web"
        )
        db.session.add(log)
        db.session.commit()
        return jsonify({"ok": True})

    # -------------------------------------------------------------------
    # ADMIN ROUTES
    # -------------------------------------------------------------------

    @app.route("/admin/login", methods=["GET", "POST"])
    @limiter.limit("5 per minute")
    def admin_login():
        if current_user.is_authenticated:
            if isinstance(_actual_user(), Reviewer):
                return redirect(url_for("review_queue"))
            return redirect(url_for("admin_dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            admin = Admin.query.filter_by(username=username).first()

            if admin and admin.check_password(password):
                login_user(admin)
                flash("Welcome back!", "success")
                next_page = request.args.get("next")
                if not is_safe_redirect_target(next_page):
                    next_page = None
                return redirect(next_page or url_for("admin_dashboard"))
            else:
                flash("Invalid username or password.", "danger")

        return render_template("admin/login.html")

    @app.route("/admin/logout")
    @login_required
    def admin_logout():
        logout_user()
        flash("You have been logged out.", "info")
        return redirect(url_for("index"))

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        total_terms = Term.query.count()
        # Active = not yet resolved (regardless of status)
        active_suggestions = Suggestion.query.filter_by(resolved=False) \
            .order_by(Suggestion.created_at.desc()).all()
        # Resolved archive
        resolved_suggestions = Suggestion.query.filter_by(resolved=True) \
            .order_by(Suggestion.resolved_at.desc()).all()
        all_terms = Term.query.order_by(Term.english.asc()).all()

        # --- Search analytics ---
        total_searches = SearchLog.query.count()

        # Top searched queries (all time, top 15)
        top_queries = db.session.query(
            SearchLog.query_text,
            func.count(SearchLog.id).label("search_count"),
            func.min(SearchLog.results_count).label("min_results")
        ).group_by(SearchLog.query_text).order_by(
            func.count(SearchLog.id).desc()
        ).limit(15).all()

        # "No results" queries — your priority list for new terms
        no_results_queries = db.session.query(
            SearchLog.query_text,
            func.count(SearchLog.id).label("search_count")
        ).filter(
            SearchLog.results_count == 0
        ).group_by(SearchLog.query_text).order_by(
            func.count(SearchLog.id).desc()
        ).limit(20).all()

        return render_template(
            "admin/dashboard.html",
            total_terms=total_terms,
            pending_count=len(active_suggestions),
            suggestions=active_suggestions,
            resolved_suggestions=resolved_suggestions,
            all_terms=all_terms,
            total_searches=total_searches,
            top_queries=top_queries,
            no_results_queries=no_results_queries,
        )

    @app.route("/admin/add", methods=["GET", "POST"])
    @admin_required
    def admin_add_term():
        if request.method == "POST":
            term = Term(
                english=request.form.get("english", "").strip(),
                kinyarwanda=request.form.get("kinyarwanda", "").strip(),
                example_en=request.form.get("example_en", "").strip() or None,
                example_rw=request.form.get("example_rw", "").strip() or None,
                etymology=request.form.get("etymology", "").strip() or None,
                category=request.form.get("category", "").strip() or None,
                source=request.form.get("source", "").strip() or None,
            )
            db.session.add(term)
            db.session.commit()
            flash(f'"{term.english}" has been added to the dictionary.', "success")
            return redirect(url_for("admin_dashboard"))
        return render_template("admin/add_term.html")

    @app.route("/admin/edit/<int:term_id>", methods=["GET", "POST"])
    @admin_required
    def admin_edit_term(term_id):
        term = Term.query.get_or_404(term_id)
        if request.method == "POST":
            term.english = request.form.get("english", "").strip()
            term.kinyarwanda = request.form.get("kinyarwanda", "").strip()
            term.example_en = request.form.get("example_en", "").strip() or None
            term.example_rw = request.form.get("example_rw", "").strip() or None
            term.etymology = request.form.get("etymology", "").strip() or None
            term.category = request.form.get("category", "").strip() or None
            term.source = request.form.get("source", "").strip() or None
            db.session.commit()
            flash(f'"{term.english}" has been updated.', "success")
            return redirect(url_for("admin_dashboard"))
        return render_template("admin/add_term.html", term=term, editing=True)

    @app.route("/admin/delete/<int:term_id>", methods=["POST"])
    @admin_required
    def admin_delete_term(term_id):
        term = Term.query.get_or_404(term_id)
        english = term.english
        db.session.delete(term)
        db.session.commit()
        flash(f'"{english}" has been removed from the dictionary.', "info")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/suggestion/<int:suggestion_id>/<action>", methods=["POST"])
    @admin_required
    def admin_handle_suggestion(suggestion_id, action):
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        if action == "approve":
            # Just open the add-term form pre-filled — don't change status
            # The suggestion stays in the active panel untouched
            return redirect(url_for(
                "admin_add_term",
                english=suggestion.english_word,
                suggested=suggestion.suggested_translation or ""
            ))
        elif action == "reject":
            suggestion.status = "rejected"
            db.session.commit()
            flash(f'"{suggestion.english_word}" marked as rejected.', "info")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/suggestion/<int:suggestion_id>/resolve", methods=["POST"])
    @admin_required
    def admin_resolve_suggestion(suggestion_id):
        """Mark a suggestion as resolved — moves it to the archive."""
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        suggestion.resolved = True
        suggestion.resolved_at = datetime.now(timezone.utc)
        db.session.commit()
        flash(
            f'"{suggestion.english_word}" resolved and moved to archive.',
            "success"
        )
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/suggestion/<int:suggestion_id>/unresolve", methods=["POST"])
    @admin_required
    def admin_unresolve_suggestion(suggestion_id):
        """Restore a resolved suggestion back to the active panel."""
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        suggestion.resolved = False
        suggestion.resolved_at = None
        db.session.commit()
        flash(
            f'"{suggestion.english_word}" restored to active suggestions.',
            "info"
        )
        return redirect(url_for("admin_dashboard"))

    # -------------------------------------------------------------------
    # REVIEWER ROUTES — the scoring interface for the validation round
    # -------------------------------------------------------------------

    def _review_queue_for(reviewer):
        """Return (eligible, remaining, ordered_next) for this reviewer.

        eligible: every term this reviewer may score. Excludes the guideline
                  anchors and any term the reviewer contributed (author
                  exclusion, mirrored here so they never even see it).
        remaining: eligible terms with no blind score from this reviewer yet.
        ordered_next: remaining, in a randomised order that is stable for
                  this reviewer (hash of code + id), with terms they chose
                  to skip pushed to the end.
        """
        author_name = REVIEWER_NAMES.get(reviewer.code)
        scored_ids = {
            r.term_id for r in TermReview.query
            .filter_by(reviewer=reviewer.code, is_adjudication=False).all()
        }
        eligible = [
            t for t in Term.query.all()
            if t.english not in REVIEW_EXCLUDED_TERMS
            and not (author_name and t.contributed_by == author_name)
        ]
        eligible.sort(key=lambda t: hashlib.sha256(
            f"{reviewer.code}:{t.id}".encode()).hexdigest())
        remaining = [t for t in eligible if t.id not in scored_ids]
        skipped = set(session.get("review_skipped", []))
        ordered_next = ([t for t in remaining if t.id not in skipped]
                        + [t for t in remaining if t.id in skipped])
        return eligible, remaining, ordered_next

    def _reviewer_may_score(reviewer, term):
        author_name = REVIEWER_NAMES.get(reviewer.code)
        if term.english in REVIEW_EXCLUDED_TERMS:
            return False
        if author_name and term.contributed_by == author_name:
            return False
        return True

    def _previous_blind_score(reviewer, term):
        return (TermReview.query
                .filter_by(term_id=term.id, reviewer=reviewer.code,
                           is_adjudication=False)
                .order_by(TermReview.reviewed_at.desc(), TermReview.id.desc())
                .first())

    @app.route("/review/login", methods=["GET", "POST"])
    @limiter.limit("5 per minute")
    def review_login():
        if current_user.is_authenticated:
            if isinstance(_actual_user(), Reviewer):
                return redirect(url_for("review_queue"))
            return redirect(url_for("admin_dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            reviewer = Reviewer.query.filter_by(username=username).first()
            if reviewer and reviewer.active and reviewer.check_password(password):
                login_user(reviewer)
                session.pop("review_skipped", None)
                flash(f"Welcome, {reviewer.display_name}.", "success")
                next_page = request.args.get("next")
                if not is_safe_redirect_target(next_page):
                    next_page = None
                return redirect(next_page or url_for("review_queue"))
            flash("Invalid username or password.", "danger")

        return render_template("review/login.html")

    @app.route("/review/logout")
    @reviewer_required
    def review_logout():
        logout_user()
        session.pop("review_skipped", None)
        flash("You have been logged out.", "info")
        return redirect(url_for("index"))

    @app.route("/review")
    @reviewer_required
    def review_queue():
        reviewer = _actual_user()
        eligible, remaining, ordered_next = _review_queue_for(reviewer)
        if not ordered_next:
            return render_template(
                "review/done.html",
                reviewer=reviewer,
                total=len(eligible),
            )
        return redirect(url_for("review_term", term_id=ordered_next[0].id))

    @app.route("/review/term/<int:term_id>")
    @reviewer_required
    def review_term(term_id):
        reviewer = _actual_user()
        term = db.get_or_404(Term, term_id)
        if not _reviewer_may_score(reviewer, term):
            abort(403)
        eligible, remaining, _ = _review_queue_for(reviewer)
        return render_template(
            "review/score.html",
            reviewer=reviewer,
            term=term,
            previous=_previous_blind_score(reviewer, term),
            done=len(eligible) - len(remaining),
            total=len(eligible),
        )

    @app.route("/review/term/<int:term_id>/score", methods=["POST"])
    @reviewer_required
    def review_score(term_id):
        reviewer = _actual_user()
        term = db.get_or_404(Term, term_id)
        if not _reviewer_may_score(reviewer, term):
            abort(403)

        try:
            score = int(request.form.get("score", ""))
        except ValueError:
            abort(400)
        if score not in (1, 2, 3, 4):
            abort(400)

        previous = _previous_blind_score(reviewer, term)
        if previous and request.form.get("confirm_replace") != "yes":
            flash("You have already scored this term. Tick the box to confirm "
                  "you want to replace your earlier score.", "warning")
            return redirect(url_for("review_term", term_id=term.id))

        row = TermReview(
            term_id=term.id,
            reviewer=reviewer.code,
            score=score,
            proposed_rw=request.form.get("proposed_rw", "").strip() or None,
            note=request.form.get("note", "").strip() or None,
            # What was actually on screen, from the hidden field the page
            # rendered; falls back to the current string if it is missing.
            shown_rw=(request.form.get("shown_rw", "").strip() or term.kinyarwanda),
            is_adjudication=False,
        )
        db.session.add(row)
        recompute_validation_status(term)
        db.session.commit()

        skipped = session.get("review_skipped", [])
        if term.id in skipped:
            skipped.remove(term.id)
            session["review_skipped"] = skipped

        flash("Saved.", "success")
        return redirect(url_for("review_queue"))

    @app.route("/review/term/<int:term_id>/skip", methods=["POST"])
    @reviewer_required
    def review_skip(term_id):
        term = db.get_or_404(Term, term_id)
        skipped = session.get("review_skipped", [])
        if term.id not in skipped:
            skipped.append(term.id)
            session["review_skipped"] = skipped
        return redirect(url_for("review_queue"))

    @app.route("/review/guideline")
    @reviewer_required
    def review_guideline():
        path = os.path.join(app.root_path, "REVIEWER_GUIDELINE.md")
        html = None
        text = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            try:
                import markdown  # optional dependency; falls back to plain text
                html = markdown.markdown(text)
            except ImportError:
                html = None
        return render_template("review/guideline.html", html=html, text=text)

    return app


# ---------------------------------------------------------------------------
# Run the app
# ---------------------------------------------------------------------------
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)