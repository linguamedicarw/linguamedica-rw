"""
Candidate items for the evaluation test set (scripts/testset_candidates.py).

The tagging rule, the exclusion of dictionary examples, the bilingual split
and the gold rule, each on inputs small enough to check by eye. No Kinyarwanda
is written here: renderings are placeholders, and the one Kinyarwanda sentence
used is read from the frozen corpus file.
"""
import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("testset_candidates",
                                               ROOT / "scripts" / "testset_candidates.py")
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)


def _gold(*headwords, variants=None):
    variants = variants or {}
    return {i: {"term_id": i, "english": h, "english_variants": variants.get(h, ""),
                "domain": "D", "rendering": f"rw-{i}"}
            for i, h in enumerate(headwords, start=1)}


def _tags(sentence, gold):
    return [entry["english"] for entry, _ in tc.tag(sentence, tc.compile_tags(gold))]


def _write(path, fields, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _backup(root, changed=False):
    """
    Three v1 terms scored by OU and YV: Tablet 4/4, Virus 4/3, Twins 4/4.
    Renderings are placeholders (rw-1 ...). With changed=True the backup's
    rendering of Twins differs from the one shown with the scores.
    """
    folder = root / "2026-10-17_1732"
    folder.mkdir(parents=True)
    terms = [{"id": i, "english": e,
              "kinyarwanda": f"rw-{i}" + ("-edited" if changed and i == 3 else ""),
              "example_en": "", "example_rw": "", "corpus_version": "v1",
              "corpus_key": f"K{i}", "pilot": "false", "domain": "D"}
             for i, e in ((1, "Tablet"), (2, "Virus"), (3, "Twins"))]
    rows, rid = [], 0
    for who, scores in (("OU", (4, 4, 4)), ("YV", (4, 3, 4))):
        for i, score in enumerate(scores, start=1):
            rid += 1
            rows.append({"id": rid, "term_id": i, "reviewer": who, "score": score,
                         "proposed_rw": "", "shown_rw": f"rw-{i}", "note": "",
                         "is_adjudication": "false",
                         "reviewed_at": f"2026-10-07T10:{rid:02d}:00"})
    _write(folder / "terms.csv", list(terms[0]), terms)
    _write(folder / "term_reviews.csv", list(rows[0]), rows)
    _write(folder / "reviewers.csv", ["id", "code", "display_name"],
           [{"id": 1, "code": "OU", "display_name": "O"}, {"id": 2, "code": "YV", "display_name": "Y"}])
    manifest = {"files": {n: {"sha256": hashlib.sha256((folder / n).read_bytes()).hexdigest()}
                          for n in ("terms.csv", "term_reviews.csv", "reviewers.csv")}}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


# --- Tagging -----------------------------------------------------------------

def test_plural_singular_and_british_spelling():
    gold = _gold("Twins", "Postpartum hemorrhage", "Cesarean section", "Infection", "Midwife")
    assert _tags("She is a twin.", gold) == ["Twins"]
    assert _tags("Postpartum haemorrhage needs urgent care.", gold) == ["Postpartum hemorrhage"]
    assert _tags("A caesarean section was done.", gold) == ["Cesarean section"]
    assert _tags("Two infections were treated by midwives.", gold) == ["Infection", "Midwife"]


def test_verb_forms_acronyms_hyphens_and_variants():
    gold = _gold("To examine", "Sexually transmitted disease (STD)", "Point-of-care testing",
                 "Placental abruption", variants={"Placental abruption": "Abruptio placentae"})
    assert _tags("The nurse examined the child.", gold) == ["To examine"]
    assert _tags("STDs are common.", gold) == ["Sexually transmitted disease (STD)"]
    assert _tags("Point of care testing is fast.", gold) == ["Point-of-care testing"]
    assert _tags("Abruptio placentae is rare.", gold) == ["Placental abruption"]


def test_a_long_headword_written_with_a_hyphen_inside_a_word():
    gold = _gold("Cephalopelvic disproportion", "Test")
    assert _tags("The causes were cephalo-pelvic disproportion and malposition.", gold) == [
        "Cephalopelvic disproportion"]
    assert _tags("Cephalo pelvic disproportion (CPD) was assessed.", gold) == [
        "Cephalopelvic disproportion"]
    assert _tags("A te-st of nothing.", gold) == []          # short headwords never stretch


def test_whole_words_only():
    gold = _gold("Test", "Virus")
    assert _tags("The contestant was testing a protest.", gold) == []
    assert _tags("Antivirus software is not medicine.", gold) == []
    assert _tags("Two tests found the virus.", gold) == ["Test", "Virus"]


# --- Dictionary examples -----------------------------------------------------

def test_dictionary_examples_are_never_candidates():
    examples = {tc.normalise("The patient was given a tablet twice a day.")}
    assert tc.is_dictionary_example(["the patient was given a TABLET twice a day"], examples)
    assert tc.is_dictionary_example(
        ["Doctors said: the patient was given a tablet twice a day, again."], examples)
    assert not tc.is_dictionary_example(["The patient was given an injection."], examples)


# --- Bilingual documents -----------------------------------------------------

def test_bilingual_split_keeps_the_translation_whole():
    def reads_as_kinyarwanda(text):
        clauses = re.split(r"(?<=[?.!:])\s+", text.strip())
        return len(text.split()) >= 4 and all(tc._english_share(c) < 0.10 for c in clauses)
    with open(ROOT / "data" / "annotation_corpus_v1.csv", encoding="utf-8", newline="") as f:
        rw = next(r["example_rw"].strip() for r in csv.DictReader(f)
                  if reads_as_kinyarwanda(r["example_rw"]))
    english = "Did you have any infections during the pregnancy?"
    expected_rw = re.sub(r"(?<=[?.!:])\s+", " ", rw)
    assert tc.split_bilingual(f"{english} {rw}") == (english, expected_rw)


# --- The gold rule -----------------------------------------------------------

def test_gold_needs_two_4s_and_an_unchanged_rendering(tmp_path):
    _, _, _, gold, left, _ = tc.read_gold(_backup(tmp_path / "plain"))
    assert sorted(g["english"] for g in gold.values()) == ["Tablet", "Twins"]
    assert gold[1]["rendering"] == "rw-1" and left == []
    _, _, _, gold, left, _ = tc.read_gold(_backup(tmp_path / "changed", changed=True))
    assert [g["english"] for g in gold.values()] == ["Tablet"]
    assert left == [{"term_id": 3, "english": "Twins",
                     "reason": "the rendering changed after it was scored"}]


# --- Building the sheet ------------------------------------------------------

def test_build_counts_tags_and_lists_what_it_drops():
    gold = _gold("Tablet", "Twins")
    examples = {tc.normalise("Take one tablet a day.")}
    web = [
        {"term": "Tablet", "sentence": "Swallow the tablet with water after a meal.", "url": "u1"},
        {"term": "Tablet", "sentence": "Take one tablet a day.", "url": "u2"},
        {"term": "Twins", "sentence": "Mothers of twins were given a tablet of iron.", "url": "u3"},
        {"term": "Twins", "sentence": None, "note": "nothing allowed found"},
        {"term": "Tablet", "sentence": "A sentence with neither term.", "url": "u4"},
    ]
    rows, coverage, left_out = tc.build(gold, examples, web, [])
    assert [r["terms"] for r in rows] == [["Tablet", "Twins"], ["Tablet"]]
    assert {c["term"]: c["candidates"] for c in coverage} == {"Tablet": 2, "Twins": 1}
    assert [c["not_found_note"] for c in coverage if c["term"] == "Twins"] == ["nothing allowed found"]
    assert sorted(x["why"].split(" (")[0] for x in left_out) == [
        "a dictionary example sentence", "no gold term matched"]


def test_refuses_to_write_inside_the_repository():
    with pytest.raises(SystemExit):
        tc.write_outputs([], [], [], {}, ROOT / "data", "x")

def test_suggestion_covers_every_term_with_few_rows():
    gold = _gold("Tablet", "Twins", "Virus", "Test")
    web = [
        {"term": "Tablet", "sentence": "Swallow the tablet with water after a meal.", "licence": "CC BY 4.0"},
        {"term": "Twins", "sentence": "Mothers of twins were given a tablet of iron.",
         "other_terms": ["Tablet"], "licence": "US federal, public domain"},
        {"term": "Virus", "sentence": "The virus was found by a test in the clinic.",
         "other_terms": ["Test"], "licence": "US federal, public domain"},
        {"term": "Twins", "sentence": "Twins were born after a statistical test of the virus data.",
         "licence": "US federal, public domain"},
    ]
    rows, coverage, _ = tc.build(gold, set(), web, [])
    chosen = [r["sentence"] for r in rows if r["suggested"]]
    assert chosen == ["Mothers of twins were given a tablet of iron.",
                      "The virus was found by a test in the clinic."]
    # the last sentence carries Test and Virus as tags, but its collector listed
    # neither, so the suggestion does not lean on it
    assert {c["term"]: c["suggested"] != "" for c in coverage} == {
        "Tablet": True, "Test": True, "Twins": True, "Virus": True}


def test_never_overwrites_a_sheet_the_editor_may_have_worked_in(tmp_path):
    tc.write_outputs([], [], [], {}, tmp_path, "2026-10-21")
    with pytest.raises(SystemExit):
        tc.write_outputs([], [], [], {}, tmp_path, "2026-10-21")
    tc.write_outputs([], [], [], {}, tmp_path, "2026-10-21", force=True)
