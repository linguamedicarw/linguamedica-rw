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
import sqlite3
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import Config
from models import db, Term, Suggestion, Admin


# ---------------------------------------------------------------------------
# Database Migration — Add provenance columns to existing terms table
# ---------------------------------------------------------------------------
def migrate_add_provenance_columns(app):
    """Add contributed_by, source, and date_added columns if they don't exist."""
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
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


# ---------------------------------------------------------------------------
# App Factory
# ---------------------------------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize extensions
    db.init_app(app)
    csrf = CSRFProtect(app)
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=[],
        storage_uri="memory://",
    )

    # Set up Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "admin_login"
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Admin, int(user_id))

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
        flash("Too many login attempts. Please wait a minute and try again.", "danger")
        return render_template("admin/login.html"), 429

    # Create database tables, migrate, and auto-seed new terms
    with app.app_context():
        db.create_all()
        migrate_add_provenance_columns(app)

        from seed_data import STARTER_TERMS, ADMIN_USERNAME, ADMIN_PASSWORD

        added = 0
        for term_data in STARTER_TERMS:
            if not Term.query.filter_by(english=term_data["english"]).first():
                db.session.add(Term(**term_data))
                added += 1

        if not Admin.query.filter_by(username=ADMIN_USERNAME).first():
            admin = Admin(username=ADMIN_USERNAME)
            admin.set_password(ADMIN_PASSWORD)
            db.session.add(admin)

        if added > 0:
            db.session.commit()
            print(f"Auto-seed: added {added} new terms (total: {Term.query.count()})")

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
        return jsonify([t.to_dict() for t in results])

    # -------------------------------------------------------------------
    # ADMIN ROUTES
    # -------------------------------------------------------------------

    @app.route("/admin/login", methods=["GET", "POST"])
    @limiter.limit("5 per minute")
    def admin_login():
        if current_user.is_authenticated:
            return redirect(url_for("admin_dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            admin = Admin.query.filter_by(username=username).first()

            if admin and admin.check_password(password):
                login_user(admin)
                flash("Welcome back!", "success")
                next_page = request.args.get("next")
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
    @login_required
    def admin_dashboard():
        total_terms = Term.query.count()
        pending = Suggestion.query.filter_by(status="pending").count()
        suggestions = Suggestion.query.filter_by(status="pending") \
            .order_by(Suggestion.created_at.desc()).all()
        recent_terms = Term.query.order_by(Term.created_at.desc()).limit(5).all()
        return render_template(
            "admin/dashboard.html",
            total_terms=total_terms,
            pending_count=pending,
            suggestions=suggestions,
            recent_terms=recent_terms,
        )

    @app.route("/admin/add", methods=["GET", "POST"])
    @login_required
    def admin_add_term():
        if request.method == "POST":
            term = Term(
                english=request.form.get("english", "").strip(),
                kinyarwanda=request.form.get("kinyarwanda", "").strip(),
                example_en=request.form.get("example_en", "").strip() or None,
                example_rw=request.form.get("example_rw", "").strip() or None,
                etymology=request.form.get("etymology", "").strip() or None,
                category=request.form.get("category", "").strip() or None,
            )
            db.session.add(term)
            db.session.commit()
            flash(f'"{term.english}" has been added to the dictionary.', "success")
            return redirect(url_for("admin_dashboard"))
        return render_template("admin/add_term.html")

    @app.route("/admin/edit/<int:term_id>", methods=["GET", "POST"])
    @login_required
    def admin_edit_term(term_id):
        term = Term.query.get_or_404(term_id)
        if request.method == "POST":
            term.english = request.form.get("english", "").strip()
            term.kinyarwanda = request.form.get("kinyarwanda", "").strip()
            term.example_en = request.form.get("example_en", "").strip() or None
            term.example_rw = request.form.get("example_rw", "").strip() or None
            term.etymology = request.form.get("etymology", "").strip() or None
            term.category = request.form.get("category", "").strip() or None
            db.session.commit()
            flash(f'"{term.english}" has been updated.', "success")
            return redirect(url_for("admin_dashboard"))
        return render_template("admin/add_term.html", term=term, editing=True)

    @app.route("/admin/delete/<int:term_id>", methods=["POST"])
    @login_required
    def admin_delete_term(term_id):
        term = Term.query.get_or_404(term_id)
        english = term.english
        db.session.delete(term)
        db.session.commit()
        flash(f'"{english}" has been removed from the dictionary.', "info")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/suggestion/<int:suggestion_id>/<action>", methods=["POST"])
    @login_required
    def admin_handle_suggestion(suggestion_id, action):
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        if action == "approve":
            suggestion.status = "approved"
            db.session.commit()
            flash(
                f'Suggestion "{suggestion.english_word}" approved. '
                f'Now add it as a term.',
                "success"
            )
            return redirect(url_for(
                "admin_add_term",
                english=suggestion.english_word,
                suggested=suggestion.suggested_translation or ""
            ))
        elif action == "reject":
            suggestion.status = "rejected"
            db.session.commit()
            flash(f'Suggestion "{suggestion.english_word}" has been rejected.', "info")
        return redirect(url_for("admin_dashboard"))

    return app


# ---------------------------------------------------------------------------
# Run the app
# ---------------------------------------------------------------------------
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)