"""
Component 1: the input (thesis 4.2.1). An item is an English sentence with an id and,
when the item is annotated, the medical terms it carries.

Formats
    CSV, columns `item` (or `id`) and `sentence`, and optionally `terms`, `found_as`
    and `wrong_sense`; or JSON Lines, one object per line with the same keys.

    `terms`: the medical terms in the sentence, separated by ";" or "|" (a JSON list
    is fine too). A term may name its entry as "Headword#123" when two entries share
    the headword. With a `terms` column, an empty cell means the sentence carries no
    medical term. Without one, the item is not annotated: no miss can be flagged, term
    recall is not computed, and a generated output is marked `unchecked`.

    `found_as`: in the same order, one slot per term, how each term is written in the
    sentence (the test-set sheet's column); a slot may be empty. It tells the pipeline
    where to put the placeholder when a term is missed.

    `wrong_sense`: terms that string matching tagged but that the sentence uses in
    another sense ("Delivery" in the delivery of oxygen). They are not counted as
    terms, and their retrieval is reported apart from adherence.

Any other column is ignored. A Kinyarwanda reference never reaches the pipeline.

The test set stays away from every system until it is frozen (EVALUATION_TEST_SET_v1.md),
so a path that looks like it is refused: any folder or file whose name holds "test set"
or "test candidates" in any spelling (testset, test_set, TestSet, test-candidates...).
"""

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .matching import nfc

TEST_SET_MARK = re.compile(r"test[\W_]*(?:sets?|candidates)(?!(?-i:[a-z]))", re.IGNORECASE)
_SEPARATOR = re.compile(r"[;|]")


class HeldOut(SystemExit):
    """Raised for a path that looks like the evaluation test set."""


class ItemsError(ValueError):
    pass


@dataclass
class Expected:
    term: str
    found_as: str = None
    entry_id: int = None


@dataclass
class Item:
    id: str
    sentence: str               # NFC
    expected: list = None       # [Expected]; None when the item is not annotated
    notes: list = field(default_factory=list)
    wrong_sense: list = field(default_factory=list)   # [Expected]

    @property
    def annotated(self):
        return self.expected is not None


def guard(path):
    """The resolved path, unless it looks like the evaluation test set."""
    p = Path(path).expanduser().resolve()
    for part in p.parts:
        if TEST_SET_MARK.search(part):
            raise HeldOut(
                f"Refusing {p}: it looks like the evaluation test set. The test set stays "
                "away from every system until it is frozen (SHA-256 and git tag), and the "
                "test run opens only after K, the backbone and the matching rule are fixed "
                "on development items. Use development items.")
    return p


def _slots(value):
    """Positional slots of a cell: a JSON list as it is, a string split on ';' or '|'."""
    if value is None:
        return []
    parts = value if isinstance(value, list) else _SEPARATOR.split(str(value))
    return ["" if p is None else str(p).strip() for p in parts]


def _term(text):
    """(name, entry id or None) from "Headword" or "Headword#123"."""
    m = re.match(r"^(.*?)#(\d+)$", text)
    return (m.group(1).strip(), int(m.group(2))) if m else (text, None)


def _expected(terms, found_as, wrong_sense, notes):
    """([Expected] or None when not annotated, [Expected] for the wrong-sense terms)."""
    wrong = [Expected(name, None, entry_id)
             for name, entry_id in (_term(w) for w in _slots(wrong_sense) if w)]
    if terms is None:
        return None, wrong
    names, surfaces = _slots(terms), _slots(found_as)
    if any(surfaces) and len(surfaces) != len(names):
        notes.append(f"found_as has {len(surfaces)} slots for {len(names)} terms; ignored")
        surfaces = []
    skip_names = {w.term.casefold() for w in wrong}
    skip_ids = {w.entry_id for w in wrong if w.entry_id is not None}
    out = []
    for i, raw in enumerate(names):
        if not raw:
            continue
        name, entry_id = _term(raw)
        if name.casefold() in skip_names or (entry_id is not None and entry_id in skip_ids):
            continue
        surface = surfaces[i] if i < len(surfaces) and surfaces[i] else None
        out.append(Expected(name, surface, entry_id))
    return out, wrong


def _item(row, line):
    item_id = str(row.get("item") or row.get("id") or "").strip()
    sentence = nfc(str(row.get("sentence") or "")).strip()
    if not item_id or not sentence:
        raise ItemsError(f"{line}: every item needs an id (item) and a sentence")
    notes = []
    expected, wrong = _expected(row.get("terms"), row.get("found_as"),
                                row.get("wrong_sense"), notes)
    return Item(item_id, sentence, expected, notes, wrong)


def read_items(path):
    """[Item] from a CSV or JSON Lines file, after the test-set guard."""
    p = guard(path)
    suffix = p.suffix.lower()
    rows = []
    if suffix in (".csv", ".tsv"):
        with open(p, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t" if suffix == ".tsv" else ",")
            for n, row in enumerate(reader, start=2):
                if None in row or any(v is None for v in row.values()):
                    raise ItemsError(f"{p.name} line {n}: the row does not have the header's "
                                     "columns (a missing cell, or a comma in an unquoted "
                                     "sentence)")
                rows.append((row, f"{p.name} line {n}"))
    elif suffix in (".jsonl", ".ndjson"):
        with open(p, encoding="utf-8-sig") as f:
            for n, line in enumerate(f, start=1):
                if line.strip():
                    rows.append((json.loads(line), f"{p.name} line {n}"))
    else:
        raise ItemsError(f"{p.name}: items must be a .csv, .tsv or .jsonl file")
    items, seen = [], set()
    for row, line in rows:
        item = _item(row, line)
        if item.id in seen:
            raise ItemsError(f"{line}: the id {item.id} is used twice")
        seen.add(item.id)
        items.append(item)
    if not items:
        raise ItemsError(f"{p.name} holds no items")
    return items
