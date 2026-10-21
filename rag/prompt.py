"""
Component 4: prompt construction (thesis 4.3.3, 4.3.5, 4.4.2).

The backbone is told to translate the sentence and, for each matched term, to use the
given rendering, with the entry's category as context and, in the 'example' arm, the
entry's example sentence. Nothing else from an entry reaches the prompt: not the
etymology, not the provenance, not the Kinyarwanda variants.

Everything Kinyarwanda in a prompt comes from the resource. A prompt is built from three
things only: the fixed wording below, the English sentence, and the retrieved entries.
No model output is ever an input here.

A term the resource does not hold (a miss, 4.3.5) is replaced in the sentence by a
placeholder, [T1], [T2], before the model sees it, and the placeholder is replaced by the
English term, marked, after: so the model's own rendering of a missed term cannot reach
the output. Its attempt is asked for separately (MISS_TEMPLATE) and goes to the log only.

In the 'example' arm, an entry's example is withheld when the item's sentence shares
half or more of its words with the example's English (EXAMPLE_OVERLAP_LIMIT): the
example's Kinyarwanda would then be close to a reference translation of the item.

The wording is versioned: TEMPLATE_VERSION names it, and TEMPLATE_SHA256 is the SHA-256
of this file, so any change here, wording or layout, shows in every run log.
"""

import hashlib
from pathlib import Path

from .matching import words

TEMPLATE_VERSION = "p1"
MISS_TEMPLATE_VERSION = "m1"
TEMPLATE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

INSTRUCTION = "Translate the English sentence below into Kinyarwanda."
ENTRIES_INTRO = ("Dictionary entries for medical terms in the sentence. For each term, use the "
                 "Kinyarwanda rendering given, in the grammatical form the sentence needs.")
ALTERNATIVES_NOTE = 'Where an entry gives two renderings separated by "/", use one of them.'
SEVERAL_NOTE = "Where a term has more than one entry, use the one whose category fits the sentence."
PLACEHOLDER_NOTE = ("The sentence contains placeholders such as [T1]. Each stands for a term that is "
                    "not in the dictionary. Copy every placeholder into the translation exactly as "
                    "written, where its term belongs, and do not translate it.")
OUTPUT_NOTE = "Write only the Kinyarwanda translation."
SENTENCE_HEAD = "English sentence:"
EXAMPLE_LABEL = "Example:"
EXAMPLE_EN_LABEL = "Example in English:"
EXAMPLE_OVERLAP_LIMIT = 0.5

MISS_TEMPLATE = ('How is the medical term "{term}" said in Kinyarwanda, as it is used in this '
                 "English sentence? Answer with the Kinyarwanda term only.\n\n"
                 "English sentence:\n{sentence}")

MARK = "[[EN: {term}]]"     # how a missed term stands in the output, for a human to fill

ARMS = ("base", "example")


def placeholder(n):
    return f"[T{n}]"


def mask(sentence, spans):
    """
    The sentence with each (char_start, char_end) span replaced by a placeholder, numbered
    in sentence order, and [(placeholder, text as written)]. Spans must not overlap.
    """
    out, pieces, last = [], [], 0
    for n, (start, end) in enumerate(sorted(spans), start=1):
        out.append(sentence[last:start])
        out.append(placeholder(n))
        pieces.append((placeholder(n), sentence[start:end]))
        last = end
    out.append(sentence[last:])
    return "".join(out), pieces


def unmask(output, pieces):
    """The model's output with each placeholder replaced by its English term, marked."""
    for ph, text in pieces:
        output = output.replace(ph, MARK.format(term=text))
    return output


def overlap(sentence, example):
    """Shared words over all words (Jaccard) between two English sentences."""
    a, b = set(words(sentence)), set(words(example))
    return len(a & b) / len(a | b) if a and b else 0.0


def _entry_lines(entry, arm, sentence, details, indent):
    label = f"({entry.category})" if entry.category else "(no category)"
    lines = []
    if arm == "example" and (entry.example_rw or entry.example_en):
        shared = overlap(sentence, entry.example_en) if entry.example_en else 0.0
        details["example_overlap"][entry.id] = round(shared, 3)
        if shared >= EXAMPLE_OVERLAP_LIMIT:
            details["examples_withheld"].append(entry.id)
        else:
            if entry.example_rw:
                lines.append(f"{indent}    {EXAMPLE_LABEL} {entry.example_rw}")
            if entry.example_en:
                lines.append(f"{indent}    {EXAMPLE_EN_LABEL} {entry.example_en}")
    return label, lines


def build(sentence, masked_sentence, retrieved, arm="base", pieces=()):
    """
    (prompt text, details) for one item.

    `sentence` is the original English sentence, used only to keep a near-identical
    example out of the prompt; `masked_sentence` is what the model sees.
    """
    if arm not in ARMS:
        raise ValueError(f"arm must be one of {ARMS}, not {arm!r}")
    details = {"entries_shown": [], "examples_withheld": [], "example_overlap": {}}
    blocks, lines, groups_seen = [INSTRUCTION], [], set()
    alternatives = several = False
    for r in retrieved:
        ids = tuple(e.id for e in r.entries)
        if not ids or ids in groups_seen:
            continue
        groups_seen.add(ids)
        if len(r.entries) == 1:
            e = r.entries[0]
            label, extra = _entry_lines(e, arm, sentence, details, "")
            lines.append(f'- "{e.english}" {label}: {e.kinyarwanda}')
            lines.extend(extra)
            alternatives |= len(e.leads) > 1
        else:
            several = True
            lines.append(f'- "{r.span.text}", more than one entry:')
            for e in r.entries:
                label, extra = _entry_lines(e, arm, sentence, details, "    ")
                lines.append(f'    "{e.english}" {label}: {e.kinyarwanda}')
                lines.extend(extra)
                alternatives |= len(e.leads) > 1
        details["entries_shown"].extend(ids)
    if lines:
        intro = [ENTRIES_INTRO]
        if alternatives:
            intro.append(ALTERNATIVES_NOTE)
        if several:
            intro.append(SEVERAL_NOTE)
        blocks.append(" ".join(intro) + "\n" + "\n".join(lines))
    if pieces:
        blocks.append(PLACEHOLDER_NOTE)
    blocks.append(OUTPUT_NOTE)
    blocks.append(f"{SENTENCE_HEAD}\n{masked_sentence}")
    return "\n\n".join(blocks), details


def miss_prompt(term, sentence):
    """The separate question for the model's own attempt at a missed term (log only)."""
    return MISS_TEMPLATE.format(term=term, sentence=sentence)
