"""
Medical Dictionary — Main Application

This is the heart of the app. It:
1. Creates and configures the Flask app
2. Sets up authentication (so only you can admin)
3. Defines all the routes (URLs) users can visit
4. Handles search, suggestions, and admin operations
"""

import os
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from config import Config
from models import db, Term, Suggestion, Admin


# ---------------------------------------------------------------------------
# App Factory
# ---------------------------------------------------------------------------
def create_app():
    """
    WHY a factory function?
    - Makes testing easier (create fresh app instances)
    - Keeps configuration flexible
    - This is a Flask best practice
    """
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize extensions with the app
    db.init_app(app)

    # Set up Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "admin_login"  # Redirect here if unauthorized
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        """Flask-Login calls this to reload a user from their session."""
        return db.session.get(Admin, int(user_id))

    # Create database tables if they don't exist
    with app.app_context():
        db.create_all()

    # -------------------------------------------------------------------
    # PUBLIC ROUTES — What everyone can access
    # -------------------------------------------------------------------

    @app.route("/")
    def index():
        """
        Homepage with search bar and recently added terms.
        We load ALL terms as JSON into the page for instant client-side search.
        For < 2000 terms this is fast and works offline after page load.
        """
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
        """
        Suggestion form — users submit words they couldn't find.
        GET: show the form
        POST: save the suggestion to the database
        """
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
    # API ROUTE — For future mobile app or integrations
    # -------------------------------------------------------------------

    @app.route("/api/terms")
    def api_terms():
        """JSON API endpoint — returns all terms. Ready for mobile apps."""
        terms = Term.query.order_by(Term.english.asc()).all()
        return jsonify([t.to_dict() for t in terms])

    @app.route("/api/search")
    def api_search():
        """Search API — query parameter: ?q=word"""
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
    # ADMIN ROUTES — Only you can access these
    # -------------------------------------------------------------------

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        """Admin login page."""
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
        """
        Admin dashboard — shows:
        - Total terms in dictionary
        - Pending suggestions to review
        - Quick actions
        """
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
        """Add a new term to the dictionary."""
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
        """Edit an existing term."""
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
        """Delete a term from the dictionary."""
        term = Term.query.get_or_404(term_id)
        english = term.english
        db.session.delete(term)
        db.session.commit()
        flash(f'"{english}" has been removed from the dictionary.', "info")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/suggestion/<int:suggestion_id>/<action>", methods=["POST"])
    @login_required
    def admin_handle_suggestion(suggestion_id, action):
        """Approve or reject a suggestion."""
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        if action == "approve":
            suggestion.status = "approved"
            db.session.commit()
            flash(
                f'Suggestion "{suggestion.english_word}" approved. '
                f'Now add it as a term.',
                "success"
            )
            # Redirect to add form pre-filled with the suggestion
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
    # debug=True auto-reloads on code changes — only for development
    app.run(debug=True, port=5000)
