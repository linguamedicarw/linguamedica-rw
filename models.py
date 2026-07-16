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

    # --- Validation status (computed, never set by hand) ---
    # Recomputed from term_reviews rows by recompute_validation_status()
    # in app.py, per the validation methodology (v2).
    # Values: unreviewed, single, dual_agreed, dual_conflict.
    validation_status = db.Column(db.String(20), nullable=False,
                                  default="unreviewed",
                                  server_default="unreviewed")

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
            "validation_status": self.validation_status,
        }

    def __repr__(self):
        return f"<Term: {self.english} → {self.kinyarwanda}>"


class TermReview(db.Model):
    """
    A single reviewer's judgment on a single term.

    This is the evidence layer for the validation methodology:
    each row is one blind adequacy score (1 to 4) by one reviewer,
    or a flagged adjudication record settling a disagreement.

    Rules carried over from the validation methodology (v2):
    - Blind scores (is_adjudication=False) are the only rows that
      feed agreement statistics and validation_status.
    - Adjudication rows (is_adjudication=True) record how a
      disagreement was settled. They fix the published term but
      are excluded from reliability statistics by construction.
    - score is hard-limited to 1..4 by a database CHECK constraint,
      so an out-of-range value can never poison the statistics.
    """
    __tablename__ = "term_reviews"

    id = db.Column(db.Integer, primary_key=True)
    term_id = db.Column(
        db.Integer,
        db.ForeignKey("terms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer = db.Column(db.String(10), nullable=False, index=True)   # 'CM', 'OU', ...
    score = db.Column(db.Integer, nullable=False)                     # 1..4 adequacy
    proposed_rw = db.Column(db.String(200), nullable=True)            # reviewer's alternative
    note = db.Column(db.Text, nullable=True)
    is_adjudication = db.Column(db.Boolean, nullable=False, default=False,
                                server_default=db.text("false"))
    reviewed_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        db.CheckConstraint("score >= 1 AND score <= 4",
                           name="ck_term_reviews_score_range"),
    )

    term = db.relationship(
        "Term",
        backref=db.backref("reviews", lazy="dynamic",
                           cascade="all, delete-orphan"),
    )

    def __repr__(self):
        kind = "adjudication" if self.is_adjudication else "blind"
        return f"<TermReview: term={self.term_id} {self.reviewer}={self.score} ({kind})>"


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