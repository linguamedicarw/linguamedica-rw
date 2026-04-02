"""
Database models for the Medical Dictionary.

WHY SQLAlchemy (not raw SQL):
- Write Python classes instead of SQL strings
- Same code works with SQLite AND PostgreSQL
- Prevents SQL injection automatically
- Makes queries readable and maintainable

Each class below becomes a table in the database.
Each attribute becomes a column.
"""

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# This object connects Flask to the database
# We create it here and initialize it with the app in app.py
db = SQLAlchemy()


class Term(db.Model):
    """
    A validated medical translation entry.

    Only the admin (you) can add these — this is what makes
    the dictionary trustworthy.

    Provenance fields track who contributed each translation
    and where it came from — essential for attribution under
    the CC BY 4.0 data license.
    """
    __tablename__ = "terms"

    id = db.Column(db.Integer, primary_key=True)
    english = db.Column(db.String(200), nullable=False, index=True)
    kinyarwanda = db.Column(db.String(200), nullable=False)
    example_en = db.Column(db.Text, nullable=True)       # Example sentence in English
    example_rw = db.Column(db.Text, nullable=True)        # Example sentence in Kinyarwanda
    etymology = db.Column(db.Text, nullable=True)         # Why this translation makes sense
    category = db.Column(db.String(100), nullable=True)   # e.g., "Anatomy", "Disease", "Procedure"

    # --- Provenance fields ---
    contributed_by = db.Column(db.String(200), nullable=True,
                               default="Christophe Mumaragishyika")
    source = db.Column(db.String(300), nullable=True)     # e.g., "Annie Chibwe consent form"
    date_added = db.Column(db.DateTime, nullable=True,
                           default=lambda: datetime.now(timezone.utc))

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self):
        """Convert to dictionary — useful for JSON API later."""
        return {
            "id": self.id,
            "english": self.english,
            "kinyarwanda": self.kinyarwanda,
            "example_en": self.example_en,
            "example_rw": self.example_rw,
            "etymology": self.etymology,
            "category": self.category,
            "contributed_by": self.contributed_by,
            "source": self.source,
            "date_added": self.date_added.isoformat() if self.date_added else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Term: {self.english} → {self.kinyarwanda}>"


class Suggestion(db.Model):
    """
    A word submitted by a user who couldn't find what they needed.
    These go into a review queue for the admin.
    """
    __tablename__ = "suggestions"

    id = db.Column(db.Integer, primary_key=True)
    english_word = db.Column(db.String(200), nullable=False)
    suggested_translation = db.Column(db.String(200), nullable=True)  # User might not know
    context = db.Column(db.Text, nullable=True)            # Where they encountered the word
    submitter_email = db.Column(db.String(200), nullable=True)
    status = db.Column(
        db.String(20),
        default="pending"  # pending, approved, rejected
    )
    admin_notes = db.Column(db.Text, nullable=True)        # Your notes on the suggestion
    resolved = db.Column(db.Boolean, default=False)         # Stays in active panel until True
    resolved_at = db.Column(db.DateTime, nullable=True)     # When you marked it resolved
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<Suggestion: {self.english_word} ({self.status})>"


class SearchLog(db.Model):
    """
    Logs every search query made on the site.

    This data tells you:
    - What people are actually looking for
    - Which searches returned zero results (= terms you should add next)
    - How search volume grows over time
    """
    __tablename__ = "search_logs"

    id = db.Column(db.Integer, primary_key=True)
    query_text = db.Column(db.String(300), nullable=False, index=True)
    results_count = db.Column(db.Integer, default=0)
    source = db.Column(db.String(20), default="web")   # "web" (public page) or "api"
    searched_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<SearchLog: '{self.query_text}' ({self.results_count} results)>"


class Admin(UserMixin, db.Model):
    """
    Admin user (just you, for now).

    UserMixin provides the methods Flask-Login needs:
    is_authenticated, is_active, is_anonymous, get_id
    """
    __tablename__ = "admins"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        """Hash the password — never store plain text."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify a password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<Admin: {self.username}>"