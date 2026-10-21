"""
Component 6: the checks (thesis 4.2.1, 4.3.5, 4.3.6).

For each item: which annotated terms were retrieved (term recall) and which were not (the
misses, flagged); which retrieved terms the output used (adherence); whether every
placeholder came back. The run adds the resource version (pipeline.py).

Term recall counts a flagged term as a miss. Adherence is computed over retrieved terms,
with the misses reported beside it, not inside it (4.3.5). Two kinds of miss are told
apart for the error analysis: `held_by_resource` when the resource has the term but
matching did not find it in the sentence (a gap in matching, not in the resource), and
`dropped_by_k` when the annotated entry was matched but fell beyond K.

When an annotation names its entry ("Culture#12"), adherence for that term is scored
against that entry's rendering only, whatever else K kept. A retrieval the annotation
marks as another sense (`wrong_sense`) is left out of adherence and reported apart:
using its rendering there would be a wrong translation, not adherence.

The matching rule on the Kinyarwanda side stays open until it is settled with Prof.
Marlo, so two readings are reported (4.3.6):

    strict    the rendering's words, in order, as whole words of the output. Case, Unicode
              form and apostrophes are folded, nothing else: exact match on the citation
              form.
    tolerant  the same, except that a word may differ by a noun-class prefix and a
              connective may be any connective, by the lists in rag/matching_rules.json.
              Those lists are Kinyarwanda grammar and the editor writes them; while they
              are empty, the tolerant reading is not reported.

Whether a listed variant (variants_rw) counts is part of the same decision, so each
reading is also reported with the variants accepted. A term inside a compound is caught
by neither reading; that case is left to the reviewers.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .matching import canon_words, term_keys

DEFAULT_RULES = Path(__file__).with_name("matching_rules.json")

_RW_WORD = re.compile(r"[^\W_]+'(?=[^\W_])|[^\W_]+")
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'",
                              "`": "'", "´": "'"})


def _rw_fold(text):
    return unicodedata.normalize("NFC", text or "").translate(_APOSTROPHES).casefold()


def rw_words(text):
    """The words of a Kinyarwanda text; an elided connective (cy'...) is a word of its own."""
    return _RW_WORD.findall(_rw_fold(text))


@dataclass(frozen=True)
class Rules:
    prefixes: tuple = ()             # longest first
    connectives: frozenset = frozenset()
    min_stem: int = 2
    version: str = "none"
    sha256: str = None
    path: str = None

    @property
    def tolerant(self):
        return bool(self.prefixes or self.connectives)

    def stem(self, word):
        for p in self.prefixes:
            if word.startswith(p) and len(word) - len(p) >= self.min_stem:
                return word[len(p):]
        return word

    def describe(self):
        return {"path": self.path, "version": self.version, "sha256": self.sha256,
                "tolerant_reading": self.tolerant, "prefixes": len(self.prefixes),
                "connectives": len(self.connectives), "min_stem": self.min_stem}


def load_rules(path=None):
    """The tolerant reading's lists. A missing or empty file means strict only."""
    path = Path(path).expanduser().resolve() if path else DEFAULT_RULES
    if not path.exists():
        return Rules(version="missing", path=str(path))
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    prefixes = {_rw_fold(str(p)).strip().strip("-") for p in data.get("noun_class_prefixes") or []}
    connectives = {_rw_fold(str(c)).strip() for c in data.get("connectives") or []}
    return Rules(prefixes=tuple(sorted((p for p in prefixes if p), key=lambda p: (-len(p), p))),
                 connectives=frozenset(c for c in connectives if c),
                 min_stem=int(data.get("min_stem_letters") or 2),
                 version=str(data.get("version") or "unset"),
                 sha256=hashlib.sha256(raw).hexdigest(), path=str(path))


def _same(t, o, rules):
    if t == o:
        return True
    if rules is None:
        return False
    if t in rules.connectives:
        return o in rules.connectives
    return rules.stem(t) == rules.stem(o)


def present(rendering, out_words, rules=None):
    """True when the rendering stands in the output: strict without rules, tolerant with."""
    target = rw_words(rendering)
    n = len(target)
    if not n or n > len(out_words):
        return False
    return any(all(_same(t, o, rules) for t, o in zip(target, out_words[i:i + n]))
               for i in range(len(out_words) - n + 1))


def check_terms(scored, output, rules):
    """
    One record per retrieved term shown to the model. `scored` is
    [(Retrieved, entry ids to score against or None for all kept, wrong_sense)].
    """
    out_words = rw_words(output)
    tolerant = rules if rules.tolerant else None
    records, seen = [], set()
    for r, score_ids, wrong in scored:
        ids = tuple(e.id for e in r.entries)
        if not ids or (ids, wrong) in seen:
            continue
        seen.add((ids, wrong))
        entries = [e for e in r.entries if score_ids is None or e.id in score_ids]
        leads = [x for e in entries for x in e.leads]
        variants = [x for e in entries for x in e.variants_rw]

        def used(strings, reading):
            return any(present(x, out_words, reading) for x in strings)

        records.append({
            "term": r.span.text,
            "entry_ids": list(ids),
            "scored_against": [e.id for e in entries],
            "wrong_sense": wrong,
            "lead_strict": used(leads, None),
            "lead_tolerant": used(leads, tolerant) if tolerant else None,
            "variant_strict": used(variants, None) if variants else None,
            "variant_tolerant": (used(variants, tolerant) if variants else None) if tolerant else None,
        })
    return records


def compare_expected(item, retrieved):
    """
    [(Expected, index into retrieved or None, reason)] in annotation order, [] when the
    item is not annotated. reason is None for a hit, 'dropped_by_k' when the annotated
    entry was matched but not kept, 'not_retrieved' otherwise.
    """
    if not item.annotated:
        return []
    out = []
    for e in item.expected:
        if e.entry_id is not None:
            hit = next((i for i, r in enumerate(retrieved)
                        if any(x.id == e.entry_id for x in r.entries)), None)
            if hit is None:
                dropped = next((i for i, r in enumerate(retrieved) if e.entry_id in r.dropped), None)
                out.append((e, dropped, "dropped_by_k") if dropped is not None
                           else (e, None, "not_retrieved"))
                continue
            out.append((e, hit, None))
            continue
        wanted = term_keys(e.term)
        if e.found_as:
            wanted.add(" ".join(canon_words(e.found_as)))
        hit = next((i for i, r in enumerate(retrieved) if wanted & r.canonical_keys()), None)
        out.append((e, hit, None if hit is not None else "not_retrieved"))
    return out


def is_wrong_sense(item, r):
    """True when a retrieval matches a term the annotation marks as another sense."""
    for w in item.wrong_sense:
        if w.entry_id is not None and any(x.id == w.entry_id for x in r.entries):
            return True
        if w.entry_id is None and term_keys(w.term) & r.canonical_keys():
            return True
    return False


def _rate(a, b):
    return round(a / b, 4) if b else None


def summarise(records, rules):
    """The run's numbers, from the item records."""
    annotated = [r for r in records if r["annotated"]]
    counted = [e for r in annotated for e in r["expected"] if e.get("counted") is not False]
    nested = sum(1 for r in annotated for e in r["expected"] if e.get("counted") is False)
    misses = [e for e in counted if not e["retrieved"]]
    held = sum(1 for e in misses if e.get("held_by_resource"))
    by_k = sum(1 for e in misses if e.get("reason") == "dropped_by_k")
    extras = sum(1 for r in annotated for x in r["retrieved"]
                 if x.get("annotated") is False and not x.get("wrong_sense"))
    generated = [r for r in records if r.get("output") is not None]
    terms = [t for r in generated for t in r.get("terms", []) if not t["wrong_sense"]]
    wrong = [t for r in generated for t in r.get("terms", []) if t["wrong_sense"]]

    def tally(rows, key, variant_key=None):
        used = sum(1 for t in rows if t[key] or (variant_key and t.get(variant_key)))
        return {"used": used, "of": len(rows), "rate": _rate(used, len(rows))}

    adherence = None
    if generated:
        adherence = {
            "strict": tally(terms, "lead_strict"),
            "tolerant": tally(terms, "lead_tolerant") if rules.tolerant else None,
            "strict_with_variants": tally(terms, "lead_strict", "variant_strict"),
            "tolerant_with_variants": (tally(terms, "lead_tolerant", "variant_tolerant")
                                       if rules.tolerant else None),
            "wrong_sense_retrievals": tally(wrong, "lead_strict"),
        }
    return {
        "items": len(records),
        "annotated": len(annotated),
        "generated": len(generated),
        "statuses": {s: sum(1 for r in records if r["status"] == s)
                     for s in ("ok", "needs_review", "unchecked", "skipped", "not_generated")},
        "english_side": {
            "expected_terms": len(counted),
            "retrieved": len(counted) - len(misses),
            "term_recall": _rate(len(counted) - len(misses), len(counted)),
            "misses": len(misses),
            "miss_rate": _rate(len(misses), len(counted)),
            "misses_held_by_resource": held,
            "misses_dropped_by_k": by_k,
            "misses_not_in_resource": len(misses) - held,
            "retrievals_not_annotated": extras,
            "annotations_nested_in_a_longer_term": nested,
        },
        "adherence": adherence,
        "placeholders": {k: sum(len(r.get(f"placeholders_{k}", [])) for r in generated)
                         for k in ("sent", "lost", "repeated")},
        "outputs_cut_at_max_length": sum(1 for r in generated
                                         if any(g.get("done_reason") == "length"
                                                for g in r.get("generation", []))),
    }
