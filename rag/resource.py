"""
Component 3: the resource, and retrieval from it (thesis 4.3.1 to 4.3.4).

The store is the canonical export of the published dictionary, data/terms.json, written
by scripts/export_terms.py (one way, database to file, published terms only). It is loaded
into an in-memory SQLite database, so retrieval is a SQL query with exact match on English
keys (4.3.2), and the connection turns read-only once loaded: nothing is written back.

Keys come from the English headword and the English variants (matching.entry_keys). The
Kinyarwanda fields are payload: stored, returned, never indexed (4.3.1).

The retrieval unit (4.3.3) is the headword, the lead rendering and the category; the
example sentence joins it only in the 'example' arm (prompt.py). Etymology and provenance
are not even loaded. The Kinyarwanda variants are loaded for the checks only and never
reach a prompt.

K (4.3.4): retrieval is per term. Each matched span brings its candidate entries, best
first (a headword match before a variant match, then by entry id), and K is how many of
them are kept; K = None keeps all.
"""

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .matching import entry_keys, find_spans, term_keys, words

SCHEMA = """
CREATE TABLE entries (
    id          INTEGER PRIMARY KEY,
    english     TEXT NOT NULL,
    kinyarwanda TEXT NOT NULL,
    category    TEXT,
    variants_en TEXT,
    variants_rw TEXT,
    example_en  TEXT,
    example_rw  TEXT
);
CREATE TABLE keys (
    key       TEXT NOT NULL,
    canonical TEXT NOT NULL,
    entry_id  INTEGER NOT NULL REFERENCES entries (id),
    kind      TEXT NOT NULL CHECK (kind IN ('headword', 'variant')),
    words     INTEGER NOT NULL,
    PRIMARY KEY (key, entry_id, kind)
);
CREATE INDEX keys_by_key ON keys (key);
CREATE INDEX keys_by_canonical ON keys (canonical);
"""

KIND_RANK = {"headword": 0, "variant": 1}


def split_rw(text):
    """Kinyarwanda strings held in one field, split on '/'."""
    return tuple(p.strip() for p in re.split(r"\s*/\s*", text or "") if p.strip())


def split_en(text):
    """English variants, separated by ' / ' in the database."""
    return tuple(p.strip() for p in re.split(r"\s+/\s+", text or "") if p.strip())


@dataclass(frozen=True)
class Entry:
    id: int
    english: str
    kinyarwanda: str            # the field as written: the string reviewers scored
    category: str
    variants_en: tuple
    variants_rw: tuple
    example_en: str
    example_rw: str

    @property
    def leads(self):
        """
        The lead rendering as a tuple: one string, except for older entries that hold
        alternatives in the field ("A / B"). The prompt shows the field as written and
        the checks accept any of them.
        """
        return split_rw(self.kinyarwanda)

    def canonical_keys(self):
        return {c for _, c, _ in entry_keys(self.english, self.variants_en)}


@dataclass
class Retrieved:
    """One matched span with the entries kept for it (component 3's output)."""
    span: object                # matching.Span
    entries: list               # [Entry], at most K
    dropped: list               # entry ids beyond K

    def canonical_keys(self):
        """The canonical English keys of the kept entries, and the span as written."""
        out = {self.span.canonical}
        for e in self.entries:
            out |= e.canonical_keys()
        return out


class ResourceError(ValueError):
    pass


class Resource:
    """The exported dictionary, loaded read-only into SQLite."""

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        raw = self.path.read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResourceError(f"{self.path} is not the JSON export: {exc}") from None
        terms = payload.get("terms") if isinstance(payload, dict) else None
        if not isinstance(terms, list) or not terms:
            raise ResourceError(f"{self.path} holds no terms; expected the file written by "
                                "scripts/export_terms.py.")
        self.schema_version = payload.get("schema_version")
        self.term_count = len(terms)
        self.has_variants = all("variants_en" in t for t in terms)
        self.notes = []
        self._several, self._bracketed, self._no_keys = [], [], []
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        for t in terms:
            self._load(t)
        self.db.commit()
        self.db.execute("PRAGMA query_only = ON")
        self.max_words = self.db.execute("SELECT MAX(words) FROM keys").fetchone()[0] or 1
        self._entries = {}
        self._write_notes()

    def _load(self, t):
        try:
            entry_id = int(t["id"])
            english = (t["english"] or "").strip()
            kinyarwanda = (t["kinyarwanda"] or "").strip()
        except (KeyError, TypeError, ValueError):
            raise ResourceError(f"an entry without id, english or kinyarwanda: {t!r:.120}") from None
        if not english or not kinyarwanda:
            raise ResourceError(f"entry {entry_id} has an empty english or kinyarwanda field")
        self.db.execute(
            "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (entry_id, english, kinyarwanda, t.get("category"), t.get("variants_en"),
             t.get("variants_rw"), t.get("example_en"), t.get("example_rw")))
        keys = entry_keys(english, split_en(t.get("variants_en")))
        for key, canonical, kind in keys:
            self.db.execute("INSERT OR IGNORE INTO keys VALUES (?, ?, ?, ?, ?)",
                            (key, canonical, entry_id, kind, len(key.split())))
        if not keys:
            self._no_keys.append(english)
        if len(split_rw(kinyarwanda)) > 1:
            self._several.append(f"{english} ({len(split_rw(kinyarwanda))})")
        if "(" in kinyarwanda or "[" in kinyarwanda:
            self._bracketed.append(english)

    def _write_notes(self):
        """Things in the data that the editor may want to tidy. The code decides none."""
        if not self.has_variants:
            self.notes.append(
                f"schema {self.schema_version}: the export has no variants_en or variants_rw, "
                "so English variants are not keys and Kinyarwanda variants are not checked. "
                "Re-export with scripts/export_terms.py (schema 1.1).")
        if self._no_keys:
            self.notes.append("no English key could be read for: " + ", ".join(self._no_keys))
        if self._several:
            self.notes.append(
                f"{len(self._several)} entries hold more than one rendering in the kinyarwanda "
                f"field, separated by '/': {', '.join(self._several)}. The prompt shows the field "
                "as written and the checks accept any of them. One lead per entry, with the "
                "others in variants_rw, would make the prompt and the checks one string again.")
        if self._bracketed:
            self.notes.append(
                f"{len(self._bracketed)} entries have brackets in the rendering: "
                f"{', '.join(self._bracketed)}. The strict check looks for the bracketed words "
                "too, so an output without them counts as not used.")
        renderings = {}
        for entry_id, rw in self.db.execute("SELECT id, kinyarwanda FROM entries"):
            for lead in split_rw(rw):
                for form in (lead, re.sub(r"\([^)]*\)", " ", lead)):
                    renderings.setdefault(" ".join(words(form)), entry_id)
        clash = sorted({english for (english, key) in self.db.execute(
            "SELECT e.english, k.key FROM keys k JOIN entries e ON e.id = k.entry_id")
            if key in renderings})
        if clash:
            self.notes.append(
                "an English key is also written as a Kinyarwanda rendering in: "
                f"{', '.join(clash)}. It stays a key because it is in the English field "
                "(a name English texts use, say); move it if it should not be one.")

    # -- queries -------------------------------------------------------------

    def lookup(self, form, canonical=False):
        """[(entry_id, kind)] for every entry with this key (or canonical key), best first."""
        if not form:
            return []
        column = "canonical" if canonical else "key"
        rows = self.db.execute(f"SELECT entry_id, kind FROM keys WHERE {column} = ?",
                               (form,)).fetchall()
        best = {}
        for entry_id, kind in rows:
            if entry_id not in best or KIND_RANK[kind] < KIND_RANK[best[entry_id]]:
                best[entry_id] = kind
        return sorted(best.items(), key=lambda pair: (KIND_RANK[pair[1]], pair[0]))

    def entry(self, entry_id):
        if entry_id not in self._entries:
            row = self.db.execute(
                "SELECT id, english, kinyarwanda, category, variants_en, variants_rw, "
                "example_en, example_rw FROM entries WHERE id = ?", (entry_id,)).fetchone()
            if row is None:
                raise KeyError(entry_id)
            self._entries[entry_id] = Entry(
                row[0], row[1], row[2], row[3] or "", split_en(row[4]), split_rw(row[5]),
                row[6] or "", row[7] or "")
        return self._entries[entry_id]

    def holds(self, term, entry_id=None):
        """True when the resource has an entry for an annotated term (by id, or by key)."""
        if entry_id is not None:
            return self.db.execute("SELECT 1 FROM entries WHERE id = ?",
                                   (entry_id,)).fetchone() is not None
        return any(self.lookup(key, canonical=True) for key in term_keys(term))

    def retrieve(self, sentence, k):
        """Components 2 and 3: [Retrieved] for a sentence, K entries kept per span."""
        out = []
        for span in find_spans(sentence, self.lookup, self.max_words):
            ids = [entry_id for entry_id, _ in span.candidates]
            kept = ids if k is None else ids[:k]
            out.append(Retrieved(span, [self.entry(i) for i in kept], ids[len(kept):]))
        return out

    def version(self):
        """What every result names: the file, its SHA-256, its size."""
        return {
            "label": f"{self.path.name}@{self.sha256[:12]} ({self.term_count} terms)",
            "file": self.path.name,
            "path": str(self.path),
            "sha256": self.sha256,
            "schema_version": self.schema_version,
            "term_count": self.term_count,
            "has_variants": self.has_variants,
        }
