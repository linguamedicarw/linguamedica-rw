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
    the dictionary trustworthy. Entries loaded from a frozen annotation
    corpus are the one other way in, and they arrive unpublished
    (see `published` below), so nothing reaches the public dictionary
    that the editor has not released.

    Provenance fields track who contributed each translation
    and where it came from — essential for attribution under
    the CC BY 4.0 data license.
    """
    __tablename__ = "terms"

    id = db.Column(db.Integer, primary_key=True)
    english = db.Column(db.String(200), nullable=False, index=True)
    kinyarwanda = db.Column(db.String(200), nullable=False)

    # Other Kinyarwanda forms a reader might look up, separated by " / ".
    # Recorded and searchable, but never the string a reviewer scores: the
    # scored rendering is always `kinyarwanda` on its own, so one adequacy
    # judgment means the same thing on every row of the corpus.
    # Text, not a short VARCHAR: an entry can carry several long variants
    # (Differential blood count has five), and Postgres enforces the length.
    variants_rw = db.Column(db.Text, nullable=True)

    # Other English names for the same concept, separated by " / ". The
    # headword in `english` is the single term a reviewer is shown; these are
    # searchable synonyms, so one compound headword never asks a reviewer to
    # hold two concepts at once.
    variants_en = db.Column(db.Text, nullable=True)

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

    # --- Publication and the annotation corpus ---
    # Only published terms reach the public site, the API and the exported
    # data files (the store the RAG build reads). A term added through the
    # admin form is published at once, as before. Terms loaded from a frozen
    # annotation corpus arrive unpublished: they are in the database so the
    # reviewers can score them, and they stay off the public dictionary until
    # the editor publishes them after the round.
    published = db.Column(db.Boolean, nullable=False, default=True,
                          server_default=db.text("true"))

    # Which frozen annotation corpus the term came from ("v1"), and its key in
    # that file (for example "S84", Sarah Izabayo's row 84). Both stay empty
    # for terms that did not come from a corpus. The key is what makes the
    # import idempotent, so it is unique whenever it is set.
    corpus_version = db.Column(db.String(20), nullable=True, index=True)
    corpus_key = db.Column(db.String(20), nullable=True, unique=True, index=True)

    # In the pilot subset of the round. The review queue serves only these
    # while REVIEW_PHASE is "pilot".
    pilot = db.Column(db.Boolean, nullable=False, default=False,
                      server_default=db.text("false"))

    # The priority domain the term was sampled from: Diagnostics, Infectious
    # Disease, Obstetrics or Pharmacology. Separate from `category`, which
    # says what kind of thing the term is (Placenta is Anatomy by category
    # and Obstetrics by domain).
    domain = db.Column(db.String(40), nullable=True)

    # The editor's note recorded with the term in the corpus file: etymology
    # he gave, why a rendering was corrected, a usage note. Internal: never
    # shown to reviewers and never part of the public record, because some
    # notes quote a collector's rendering that the rules keep unpublished.
    corpus_note = db.Column(db.Text, nullable=True)

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
            "variants_rw": self.variants_rw,
            "variants_en": self.variants_en,
            "example_en": self.example_en,
            "example_rw": self.example_rw,
            "etymology": self.etymology,
            "category": self.category,
            "contributed_by": self.contributed_by,
            "source": self.source,
            "date_added": self.date_added.isoformat() if self.date_added else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "validation_status": self.validation_status,
            "published": self.published,
            "corpus_version": self.corpus_version,
            "domain": self.domain,
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
    # The exact Kinyarwanda string that was on the reviewer's screen when
    # they scored. Recorded so the stimulus is auditable, and so a genuinely
    # blind round can be run later without reworking the schema.
    shown_rw = db.Column(db.String(200), nullable=True)
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
    # The same anonymous, day-long code as the searcher's page views (see
    # PageView.visitor), so a day's searches can be tied to a day's visits.
    # None for searches made while signed in, and for rows logged before
    # visitors were counted.
    visitor = db.Column(db.String(16), nullable=True, index=True)

    def __repr__(self):
        return f"<SearchLog: '{self.query_text}' ({self.results_count} results)>"


class PageView(db.Model):
    """
    One visit to a public page, counted without cookies or IP addresses.

    `visitor` is a 16-character code made from the browser's address and
    user agent together with the day and the app's secret key. It is the same
    for all of one browser's visits on one day, different the next day, and
    cannot be turned back into an address, so visitors are counted once a day
    and never followed from one day to the next. Bots, prefetches and signed-in
    admins and reviewers are never counted. Days and hours are Kigali time.
    """
    __tablename__ = "page_views"

    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.Date, nullable=False, index=True)
    hour = db.Column(db.SmallInteger, nullable=False)
    path = db.Column(db.String(40), nullable=False)
    visitor = db.Column(db.String(16), nullable=False, index=True)
    country = db.Column(db.String(2), nullable=True)     # from Cloudflare's CF-IPCountry
    device = db.Column(db.String(8), nullable=True)      # mobile, tablet or desktop
    language = db.Column(db.String(8), nullable=True)    # the browser's first language
    referrer = db.Column(db.String(80), nullable=True)   # site or utm_source; None = direct

    def __repr__(self):
        return f"<PageView: {self.day} {self.path}>"


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

    def get_id(self):
        # Prefixed so Flask-Login can tell an admin session from a reviewer
        # session. The user loader in app.py understands both, and still
        # accepts the old bare-integer form for sessions created before this.
        return f"admin:{self.id}"

    def __repr__(self):
        return f"<Admin: {self.username}>"


class Reviewer(UserMixin, db.Model):
    """
    An independent reviewer account for the validation round.

    Separate from Admin on purpose: a reviewer can reach the scoring pages
    and nothing else. No dashboard, no add-term, no delete. Identity comes
    from the session, so a score is attributed to whoever is logged in,
    never to a name picked from a dropdown.

    `code` is the stable reviewer id used in term_reviews.reviewer and in
    REVIEWER_NAMES (app.py): 'CM', 'OU', 'YV'. Author exclusion depends on
    that mapping, so a reviewer must have an entry there before scoring.

    A new account, or one whose password an admin has just reset, carries a
    password someone else chose. `must_change_password` stays true until the
    reviewer chooses their own at the next sign-in; from then on only they
    know it, so a score under their code can only have come from them.
    """
    __tablename__ = "reviewers"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(200), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True,
                       server_default=db.text("true"))
    must_change_password = db.Column(db.Boolean, nullable=False, default=True,
                                     server_default=db.text("true"))
    # When the reviewer last chose their own password; None while temporary.
    password_changed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_active(self):
        # Flask-Login consults this; a deactivated reviewer cannot log in.
        return bool(self.active)

    def get_id(self):
        return f"reviewer:{self.id}"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<Reviewer: {self.code} {self.display_name}>"