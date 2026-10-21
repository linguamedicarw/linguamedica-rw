"""
Component 2: term matching, on the English side only (thesis 4.3.1, 4.3.2, 4.3.6).

The rule fixed in 4.3.6: matching is case-insensitive, tolerates simple plurals, prefers
the longest span at any position, and takes the leftmost of two overlapping spans.

Keys come from the English headword and the English variants of each entry
(`entry_keys`). Keys and sentence go through the same folding before they are compared,
the lexical index for spelling variants of 4.3.2:

    - Unicode compatibility forms and accents are folded (é and e are one letter);
    - case is folded;
    - curly apostrophes become straight ones, and a possessive 's is dropped
      (the patient's fever holds the word patient);
    - a word is what stands between spaces and punctuation, so a hyphen and a space
      join words alike: "X-ray", "x ray" and "X–ray" are the same two words.

Simple plurals are tolerated on every word and in both directions, through one form
per word (`canon`): -ies and -y, -sses and -ss (also -xes, -ches, -shes), and a final
-s, except after ss, us or is. An exact form is always tried first, so a word that is
itself a key is never read as another one. A word written in capitals (IRB, AIDS) is
an abbreviation and keeps its s.

Nothing else is folded. British and American spellings in particular are not
(haemorrhage is not hemorrhage) unless an entry lists the other spelling as an
English variant. The run log records this as `spelling: orthographic`.

Kinyarwanda is never matched here: its morphology belongs to the checks (checks.py).
"""

import re
import unicodedata
from dataclasses import dataclass, field

SPELLING = "orthographic"
ENGLISH_RULE = ("case-insensitive; simple plurals on every word, both ways, exact form "
                "first; longest span at any position; leftmost on ties")

_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)*")
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'",
                              "`": "'", "´": "'"})
_PAREN = re.compile(r"\(([^()]*)\)")
_ACRONYM = re.compile(r"^[A-Z][A-Z0-9]+$")
_WORD_ALTERNATIVE = re.compile(r"([^\s/]+)/([^\s/]+)")


def nfc(text):
    return unicodedata.normalize("NFC", text or "")


def fold(word):
    """One word folded: compatibility forms, accents, case, apostrophes, a possessive 's."""
    word = unicodedata.normalize("NFKD", (word or "").translate(_APOSTROPHES))
    word = "".join(ch for ch in word if not unicodedata.combining(ch)).casefold()
    if len(word) > 2 and word.endswith("'s"):
        word = word[:-2]
    return word


def canon(word, abbreviation=False):
    """One form for the singular and the simple plural of a folded word."""
    if abbreviation or len(word) <= 3:
        return word
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("sses", "xes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _abbreviation(text):
    letters = [ch for ch in text if ch.isalpha()]
    return len(letters) >= 2 and all(ch.isupper() for ch in letters)


@dataclass(frozen=True)
class Token:
    text: str    # as written in the sentence
    norm: str    # folded
    canon: str   # folded, one form for singular and plural
    start: int   # character offsets in the NFC text
    end: int


def tokenize(text):
    """The words of a text, with their offsets in its NFC form."""
    text = nfc(text)
    probe = text.translate(_APOSTROPHES)   # one character for one, so offsets hold
    out = []
    for m in _WORD.finditer(probe):
        raw = text[m.start():m.end()]
        norm = fold(m.group())
        out.append(Token(raw, norm, canon(norm, _abbreviation(raw)), m.start(), m.end()))
    return out


def words(text):
    return [t.norm for t in tokenize(text)]


def canon_words(text):
    return [t.canon for t in tokenize(text)]


# --------------------------------------------------------------------------
# Keys, read off the English fields of an entry
# --------------------------------------------------------------------------

def names(field_text):
    """The alternative names in one English field, split on a spaced slash."""
    return [p.strip() for p in re.split(r"\s+/\s+", field_text or "") if p.strip()]


def _key(tokens):
    return (" ".join(t.norm for t in tokens), " ".join(t.canon for t in tokens))


def _phrase_keys(name):
    keys = []
    for inner in _PAREN.findall(name):
        inner = inner.strip()
        parts = [p.strip() for p in inner.split("/") if p.strip()]
        if parts and all(_ACRONYM.match(p) for p in parts):
            keys.extend(_key(tokenize(p)) for p in parts)    # (IRB), (PIH/IMB)
        elif inner[:1].isupper():
            keys.extend(_phrase_keys(inner))                  # (Hyperglycemia)
        # a lower-case qualifier, "(clinical)", "(of document)", is dropped
    phrases = [_PAREN.sub(" ", name)]
    while any(_WORD_ALTERNATIVE.search(p) for p in phrases):
        expanded = []
        for p in phrases:
            m = _WORD_ALTERNATIVE.search(p)
            if not m:
                expanded.append(p)
                continue
            for alternative in (m.group(1), m.group(2)):
                expanded.append(p[:m.start()] + alternative + p[m.end():])
        phrases = expanded
    for p in phrases:
        toks = tokenize(p)
        if len(toks) > 1 and toks[0].norm == "to":
            toks = toks[1:]
        if len(toks) > 1 and toks[0].norm in ("a", "an", "the"):
            toks = toks[1:]
        if toks:
            keys.append(_key(toks))
    return keys


def entry_keys(english, variants_en=()):
    """
    [(key, canonical key, kind)] for one entry, kind 'headword' or 'variant', in order.

    How keys are read off an English field:
      - " / " separates alternative names (the June entries pack them in the
        headword: "Doctor / Physician"); each name is a key;
      - a slash inside a phrase separates alternative words: "To fight/combat a
        disease" gives "fight a disease" and "combat a disease";
      - in brackets, an abbreviation in capitals is a key of its own ("IRB"), a
        capitalised name is a key of its own ("Hyperglycemia"), and a lower-case
        qualifier is dropped ("Assessment (clinical)" is the key "assessment");
      - a leading "to" (verbs) and a leading article (a, an, the) are dropped.
    """
    out, seen = [], set()
    for kind, texts in (("headword", [english]), ("variant", list(variants_en or ()))):
        for text in texts:
            for name in names(text):
                for key, canonical in _phrase_keys(name):
                    if key and (key, kind) not in seen:
                        seen.add((key, kind))
                        out.append((key, canonical, kind))
    return out


def term_keys(term):
    """The canonical keys an annotated term stands for, to compare annotations."""
    return {canonical for _, canonical, _ in entry_keys(term)}


# --------------------------------------------------------------------------
# Spans
# --------------------------------------------------------------------------

@dataclass
class Span:
    start: int          # first token
    end: int            # one past the last token
    char_start: int
    char_end: int
    text: str           # as written in the sentence
    key: str            # the form that matched
    plural: bool        # matched only through the singular/plural form
    candidates: list = field(default_factory=list)   # [(entry_id, kind)], best first

    @property
    def length(self):
        return self.end - self.start

    @property
    def canonical(self):
        return " ".join(canon_words(self.text))


def find_spans(sentence, lookup, max_words):
    """
    The matched spans of a sentence, in sentence order.

    `lookup(form, canonical)` returns [(entry_id, kind)], best first, for the entries
    with that exact key (canonical False) or that canonical key (canonical True).
    The exact form is tried first. Selection: longest span first, the leftmost on a
    tie, and no span overlaps another.
    """
    sentence = nfc(sentence)
    toks = tokenize(sentence)
    found = []
    for i in range(len(toks)):
        for n in range(min(max_words, len(toks) - i), 0, -1):
            window = toks[i:i + n]
            exact = " ".join(t.norm for t in window)
            hits, plural, key = lookup(exact, False), False, exact
            if not hits:
                key = " ".join(t.canon for t in window)
                hits, plural = lookup(key, True), True
            if hits:
                a, b = window[0], window[-1]
                found.append(Span(i, i + n, a.start, b.end, sentence[a.start:b.end],
                                  key, plural, hits))
    chosen = []
    for span in sorted(found, key=lambda s: (-s.length, s.start)):
        if all(span.end <= c.start or span.start >= c.end for c in chosen):
            chosen.append(span)
    return sorted(chosen, key=lambda s: s.start)


def locate_all(sentence, phrases):
    """
    Every whole-word occurrence of any of the phrases in the sentence, compared by the
    same folding and plurals: [(char_start, char_end)] in sentence order, the longest
    kept where two overlap.
    """
    toks = tokenize(sentence)
    found = set()
    for phrase in phrases:
        target = canon_words(phrase)
        n = len(target)
        if not n:
            continue
        for i in range(len(toks) - n + 1):
            if [t.canon for t in toks[i:i + n]] == target:
                found.add((toks[i].start, toks[i + n - 1].end))
    chosen = []
    for a, b in sorted(found, key=lambda s: (-(s[1] - s[0]), s[0])):
        if all(b <= c or a >= d for c, d in chosen):
            chosen.append((a, b))
    return sorted(chosen)


def locate(sentence, phrases):
    """The first occurrence from locate_all, or None."""
    spots = locate_all(sentence, phrases)
    return spots[0] if spots else None
