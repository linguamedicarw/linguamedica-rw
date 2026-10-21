"""
Tests for the grounded pipeline (rag/). No database, no Flask, no network, no model.

Kinyarwanda never appears in these tests: renderings are placeholders such as rw-1, and
the tolerant reading is tested with made-up prefixes and connectives (pa-, pi-, ka', ki').
"""
import hashlib
import json
import sqlite3
import unicodedata

import pytest

from rag import checks, prompt
from rag.backbones import Backbone, Decoding, EchoBackbone, OllamaBackbone, gemma_raw
from rag.items import TEST_SET_MARK, Expected, Item, ItemsError, read_items
from rag.matching import entry_keys, find_spans, locate
from rag.pipeline import REPO_ROOT, process, run
from rag.resource import Resource


def term(id, english, rw, category="Diagnostics", **extra):
    row = {"id": id, "english": english, "kinyarwanda": rw, "variants_en": None,
           "variants_rw": None, "example_en": None, "example_rw": None,
           "etymology": "ETYMOLOGY-TEXT", "category": category,
           "contributed_by": "CONTRIBUTOR-NAME", "source": "SOURCE-TEXT",
           "date_added": None, "created_at": None}
    row.update(extra)
    return row


def resource(tmp_path, terms, schema="1.1"):
    path = tmp_path / "terms.json"
    path.write_text(json.dumps({"schema_version": schema, "term_count": len(terms),
                                "terms": terms}), encoding="utf-8")
    return Resource(path)


def spans(res, sentence):
    return find_spans(sentence, res.lookup, res.max_words)


def scored(retrieved):
    return [(r, None, False) for r in retrieved]


class Scripted(Backbone):
    """Answers the translation prompt with `main` and the miss question with `attempt`."""
    name = "scripted"

    def __init__(self, main, attempt="rw-attempt", done_reason="stop"):
        super().__init__(Decoding())
        self.main, self.attempt, self.done_reason, self.prompts = main, attempt, done_reason, []

    def generate(self, text):
        self.prompts.append(text)
        self.last = {"done_reason": self.done_reason}
        return self.attempt if text.startswith("How is the medical term") else self.main

    def describe(self):
        return {"backbone": "scripted", "checkpoint": "test"}


def rules_file(tmp_path, prefixes=(), connectives=()):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"version": "test", "noun_class_prefixes": list(prefixes),
                                "connectives": list(connectives), "min_stem_letters": 2}),
                    encoding="utf-8")
    return path


# --- (2) term matching ---------------------------------------------------------

def test_keys_are_read_off_the_english_field():
    def keys(english, variants=()):
        return {k for k, _, _ in entry_keys(english, variants)}
    assert keys("Doctor / Physician") == {"doctor", "physician"}
    assert keys("To fight/combat a disease") == {"fight a disease", "combat a disease"}
    assert keys("Institutional Review Board (IRB)") == {"institutional review board", "irb"}
    assert keys("Alpha Org / Beta Org (AO/BO)") == {"alpha org", "beta org", "ao", "bo"}
    assert keys("Assessment (clinical)") == {"assessment"}
    assert keys("High blood glucose (Hyperglycemia)") == {"high blood glucose", "hyperglycemia"}
    assert keys("A stool sample") == {"stool sample"}
    assert keys("Hemorrhage", ["Haemorrhage"]) == {"hemorrhage", "haemorrhage"}
    kinds = {k: kind for k, _, kind in entry_keys("Hemorrhage", ["Haemorrhage"])}
    assert kinds == {"hemorrhage": "headword", "haemorrhage": "variant"}


def test_hyphen_space_and_dash_are_one_key(tmp_path):
    res = resource(tmp_path, [term(1, "X-ray", "rw-1")])
    for sentence in ("An x ray was done.", "An X-ray was done.", "An X–ray was done."):
        assert [s.key for s in spans(res, sentence)] == ["x ray"]


def test_simple_plurals_both_ways_and_exact_form_first(tmp_path):
    res = resource(tmp_path, [term(1, "Blood culture", "rw-1"), term(2, "Therapy", "rw-2"),
                              term(3, "Test", "rw-3"), term(4, "Testes", "rw-4"),
                              term(5, "Herbal remedies", "rw-5"), term(6, "Barriers to care", "rw-6")])
    got = spans(res, "Two blood cultures and two therapies.")
    assert [(s.text, s.plural, s.candidates[0][0]) for s in got] == [
        ("blood cultures", True, 1), ("therapies", True, 2)]
    assert [c[0] for c in spans(res, "The testes were examined.")[0].candidates] == [4]
    assert [c[0] for c in spans(res, "A test was done.")[0].candidates] == [3]
    assert [s.text for s in spans(res, "She took a herbal remedy.")] == ["herbal remedy"]
    assert [s.text for s in spans(res, "Cost is a barrier to care.")] == ["barrier to care"]


def test_a_possessive_is_the_word_itself(tmp_path):
    res = resource(tmp_path, [term(1, "Patient", "rw-1")])
    assert [s.text for s in spans(res, "The patient's fever rose.")] == ["patient's"]
    assert [s.text for s in spans(res, "The patients' rooms.")] == ["patients"]


def test_an_abbreviation_in_capitals_keeps_its_s(tmp_path):
    res = resource(tmp_path, [term(1, "Aid", "rw-1"), term(2, "AIDS", "rw-2"), term(3, "IRB", "rw-3")])
    assert [s.candidates[0][0] for s in spans(res, "People living with AIDS.")] == [2]
    assert [s.candidates[0][0] for s in spans(res, "First aid saves lives.")] == [1]
    assert [s.candidates[0][0] for s in spans(res, "Two IRBs met.")] == [3]


def test_longest_span_wins_and_leftmost_on_ties(tmp_path):
    res = resource(tmp_path, [term(1, "Blood culture", "rw-1"), term(2, "Culture", "rw-2"),
                              term(3, "Culture medium", "rw-3")])
    assert [s.text for s in spans(res, "A blood culture medium was used.")] == ["blood culture"]
    res2 = resource(tmp_path, [term(1, "Blood culture", "rw-1"),
                               term(4, "Blood culture medium", "rw-4")])
    assert [s.text for s in spans(res2, "A blood culture medium was used.")] == ["blood culture medium"]


def test_k_keeps_candidates_headword_first_then_id(tmp_path):
    res = resource(tmp_path, [term(5, "Culture", "rw-5"), term(3, "Culture", "rw-3", category="Other"),
                              term(1, "Medium", "rw-1", variants_en="culture")])
    one = res.retrieve("The culture grew.", 1)
    assert [e.id for e in one[0].entries] == [3] and one[0].dropped == [5, 1]
    every = res.retrieve("The culture grew.", None)
    assert [e.id for e in every[0].entries] == [3, 5, 1] and every[0].dropped == []


def test_kinyarwanda_is_never_a_key(tmp_path):
    res = resource(tmp_path, [term(1, "Fever", "zzqx", variants_rw="qqzx")])
    assert res.retrieve("zzqx qqzx", None) == []


def test_resource_is_read_only_and_named_by_its_hash(tmp_path):
    res = resource(tmp_path, [term(1, "Fever", "rw-1")])
    with pytest.raises(sqlite3.OperationalError):
        res.db.execute("INSERT INTO keys VALUES ('x', 'x', 1, 'headword', 1)")
    v = res.version()
    assert v["sha256"] == hashlib.sha256((tmp_path / "terms.json").read_bytes()).hexdigest()
    assert v["label"] == f"terms.json@{v['sha256'][:12]} (1 terms)"


def test_holds_knows_a_plural(tmp_path):
    res = resource(tmp_path, [term(1, "Blood culture", "rw-1")])
    assert res.holds("Blood cultures") and not res.holds("Splenomegaly")


def test_data_notes_for_the_editor(tmp_path):
    row = term(1, "Fever", "rw-a / rw-b")
    del row["variants_en"], row["variants_rw"]
    res = resource(tmp_path, [row, term(2, "Cough", "rw-c (rw-d)"),
                              term(3, "Clinic name", "Clinic name")], schema="1.0")
    notes = " ".join(res.notes)
    assert not res.has_variants and "schema 1.0" in notes
    assert "Fever (2)" in notes and res.entry(1).leads == ("rw-a", "rw-b")
    assert "brackets in the rendering: Cough" in notes
    assert "also written as a Kinyarwanda rendering in: Clinic name" in notes
    recs = checks.check_terms(scored(res.retrieve("Fever.", 1)), "x rw-b y", checks.Rules())
    assert recs[0]["lead_strict"] is True


# --- (1) input -------------------------------------------------------------------

def test_items_from_csv_and_jsonl(tmp_path):
    path = tmp_path / "dev.csv"
    path.write_text(
        "item,sentence,terms,found_as,wrong_sense,reference\n"
        "D1,Blood cultures were taken.,Blood culture; Culture#12,blood cultures; cultures,,REF\n"
        "D2,The delivery of oxygen.,Delivery | Oxygen,,Delivery#7,REF\n"
        "D3,No term here.,,,,\n"
        "D4,Two patients and a nurse.,Fever;Patient;Nurse,;patients;,,\n", encoding="utf-8")
    items = read_items(path)
    assert [(e.term, e.found_as, e.entry_id) for e in items[0].expected] == [
        ("Blood culture", "blood cultures", None), ("Culture", "cultures", 12)]
    assert [e.term for e in items[1].expected] == ["Oxygen"]
    assert [(w.term, w.entry_id) for w in items[1].wrong_sense] == [("Delivery", 7)]
    assert items[2].annotated and items[2].expected == []
    assert [(e.term, e.found_as) for e in items[3].expected] == [
        ("Fever", None), ("Patient", "patients"), ("Nurse", None)]
    jl = tmp_path / "dev.jsonl"
    jl.write_text("﻿" + json.dumps({"id": "J1", "sentence": "Fever.", "terms": ["Fever"]}) + "\n"
                  + json.dumps({"id": "J2", "sentence": "Cough."}) + "\n", encoding="utf-8")
    j = read_items(jl)
    assert j[0].expected[0].term == "Fever" and not j[1].annotated


def test_a_row_short_of_the_header_is_an_error(tmp_path):
    path = tmp_path / "dev.csv"
    path.write_text("item,sentence,terms\nB1,Fever.,Fever\nB2,Splenomegaly was noted.\n",
                    encoding="utf-8")
    with pytest.raises(ItemsError, match="line 3"):
        read_items(path)


# (The function names below avoid the marker themselves: pytest names tmp_path after them.)
@pytest.mark.parametrize("name", [
    "LinguaMedica-testset/dev.csv", "test_candidates_2026-10-21.csv", "EVALUATION_TEST_SET_v1.csv",
    "my test set/items.csv", "devTestSet.csv", "EvalTestSet_v1.csv", "TestCandidates.csv",
    "test-candidates.csv", "test.set.csv", "testsets/a.csv"])
def test_held_out_paths_are_refused(tmp_path, name):
    assert not TEST_SET_MARK.search(str(tmp_path))
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("item,sentence\nX,Fever.\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="looks like the evaluation test set"):
        read_items(path)


@pytest.mark.parametrize("name", ["test_setup.csv", "latest settings/dev.csv", "dev_items.csv"])
def test_other_paths_are_not_held_out(tmp_path, name):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("item,sentence\nX,Fever.\n", encoding="utf-8")
    assert read_items(path)[0].id == "X"


# --- (4) prompt ------------------------------------------------------------------

def test_the_prompt_holds_the_unit_and_nothing_else(tmp_path):
    res = resource(tmp_path, [term(1, "Malaria", "rw-1", variants_rw="rw-variant",
                                   example_en="Malaria is common in the rainy season.",
                                   example_rw="rw-example")])
    sentence = "Malaria kills."
    base, _ = prompt.build(sentence, sentence, res.retrieve(sentence, 1), "base")
    assert '"Malaria" (Diagnostics): rw-1' in base
    for absent in ("ETYMOLOGY-TEXT", "CONTRIBUTOR-NAME", "SOURCE-TEXT", "rw-variant", "rw-example"):
        assert absent not in base
    assert base.endswith("English sentence:\nMalaria kills.")
    example, _ = prompt.build(sentence, sentence, res.retrieve(sentence, 1), "example")
    assert "Example: rw-example" in example
    assert "Example in English: Malaria is common in the rainy season." in example
    assert "rw-variant" not in example


def test_a_near_identical_example_is_withheld(tmp_path):
    res = resource(tmp_path, [term(1, "Consent form", "rw-1",
                                   example_en="Please read the consent form carefully before signing.",
                                   example_rw="rw-example")])
    sentence = "Please read the consent form before you sign it."
    text, details = prompt.build(sentence, sentence, res.retrieve(sentence, 1), "example")
    assert "rw-example" not in text and details["examples_withheld"] == [1]
    assert details["example_overlap"][1] >= prompt.EXAMPLE_OVERLAP_LIMIT
    other = "The consent form was signed by the patient."
    text, details = prompt.build(other, other, res.retrieve(other, 1), "example")
    assert "rw-example" in text and details["examples_withheld"] == []


def test_the_template_hash_is_the_file():
    path = REPO_ROOT / "rag" / "prompt.py"
    assert prompt.TEMPLATE_SHA256 == hashlib.sha256(path.read_bytes()).hexdigest()


# --- the miss policy -------------------------------------------------------------

def test_a_miss_is_kept_from_the_model_and_marked_in_the_output(tmp_path):
    res = resource(tmp_path, [term(1, "Blood culture", "rw-1")])
    item = Item("D1", "Blood cultures were taken and hepatosplenomegaly was noted.",
                [Expected("Blood culture"), Expected("Hepatosplenomegaly")])
    model = Scripted("rw-1 [T1] rw-x")
    record, candidates = process(item, res, 1, "base", model, checks.Rules())
    main = model.prompts[0]
    assert "hepatosplenomegaly" not in main.lower() and "[T1]" in main
    assert record["output"] == "rw-1 [[EN: hepatosplenomegaly]] rw-x"
    assert record["status"] == "ok" and record["terms"][0]["lead_strict"] is True
    assert [e["retrieved"] for e in record["expected"]] == [True, False]
    assert record["expected"][1]["held_by_resource"] is False
    assert len(candidates) == 1
    assert {k: candidates[0][k] for k in ("term_as_written", "placeholder", "attempt",
                                          "model_written", "never_shown")} == {
        "term_as_written": "hepatosplenomegaly", "placeholder": "[T1]",
        "attempt": "rw-attempt", "model_written": True, "never_shown": True}
    assert "rw-attempt" not in record["output"]


def test_a_possessive_occurrence_of_a_miss_is_masked_too(tmp_path):
    res = resource(tmp_path, [term(1, "Fever", "rw-1")])
    item = Item("D7", "Fever and splenomegaly were noted; the splenomegaly's size was measured.",
                [Expected("Fever"), Expected("Splenomegaly")])
    model = Scripted("rw-1 [T1] rw-x [T2] rw-y")
    record, _ = process(item, res, 1, "base", model, checks.Rules())
    assert "splenomegaly" not in model.prompts[0].lower()
    assert record["masked_sentence"] == "Fever and [T1] were noted; the [T2] size was measured."


def test_a_miss_still_visible_after_masking_stops_the_item(tmp_path):
    res = resource(tmp_path, [term(1, "Fever", "rw-1")])
    item = Item("D8", "Fever and splenomegaly; splenomegalic changes.",
                [Expected("Fever"), Expected("Splenomegaly")])
    model = Scripted("rw-1 [T1]")
    record, _ = process(item, res, 1, "base", model, checks.Rules())
    assert record["status"] == "skipped" and model.prompts == []
    other = Item("D8b", "Fever and malaria; antimalarial drugs.", [Expected("Fever"), Expected("Malaria")])
    record, _ = process(other, res, 1, "base", Scripted("rw-1 [T1]"), checks.Rules())
    assert record["status"] == "ok"


def test_every_occurrence_of_a_miss_is_masked_and_asked_once(tmp_path):
    res = resource(tmp_path, [term(1, "Fever", "rw-1")])
    item = Item("D5", "Splenomegaly and fever; splenomegaly again.",
                [Expected("Fever"), Expected("Splenomegaly")])
    record, candidates = process(item, res, 1, "base", Scripted("[T1] rw-1 [T2]"), checks.Rules())
    assert record["masked_sentence"] == "[T1] and fever; [T2] again."
    assert record["output"] == "[[EN: Splenomegaly]] rw-1 [[EN: splenomegaly]]"
    assert len(candidates) == 1 and record["status"] == "ok"


def test_a_miss_the_resource_holds_is_a_matching_gap(tmp_path):
    res = resource(tmp_path, [term(1, "Hemorrhage", "rw-1")])
    item = Item("D2", "Postpartum haemorrhage is dangerous.",
                [Expected("Hemorrhage", found_as="haemorrhage")])
    record, _ = process(item, res, 1, "base", None, checks.Rules())
    miss = record["expected"][0]
    assert miss["retrieved"] is False and miss["held_by_resource"] is True and miss["located"]
    assert record["masked_sentence"] == "Postpartum [T1] is dangerous."
    assert record["status"] == "not_generated"


def test_a_miss_that_cannot_be_located_is_never_sent(tmp_path):
    res = resource(tmp_path, [term(1, "Fever", "rw-1")])
    item = Item("D3", "Fever and chills.", [Expected("Fever"), Expected("Splenomegaly")])
    model = Scripted("rw-1")
    record, candidates = process(item, res, 1, "base", model, checks.Rules())
    assert record["status"] == "skipped" and model.prompts == [] and candidates == []


def test_a_lost_placeholder_or_a_cut_output_needs_review(tmp_path):
    res = resource(tmp_path, [term(1, "Fever", "rw-1")])
    item = Item("D4", "Fever and splenomegaly.", [Expected("Fever"), Expected("Splenomegaly")])
    record, _ = process(item, res, 1, "base", Scripted("rw-1 rw-x"), checks.Rules())
    assert record["status"] == "needs_review" and record["placeholders_lost"] == ["[T1]"]
    record, _ = process(Item("D9", "Fever.", [Expected("Fever")]), res, 1, "base",
                        Scripted("rw-1", done_reason="length"), checks.Rules())
    assert record["status"] == "needs_review" and record["generation"][0]["done_reason"] == "length"


def test_an_unannotated_item_is_unchecked(tmp_path):
    res = resource(tmp_path, [term(1, "Fever", "rw-1")])
    record, _ = process(Item("U1", "Fever and splenomegaly."), res, 1, "base",
                        Scripted("rw-1 rw-x"), checks.Rules())
    assert record["status"] == "unchecked"


# --- nesting and K -----------------------------------------------------------------

def test_an_annotation_inside_a_longer_retrieved_term_is_not_counted(tmp_path):
    res = resource(tmp_path, [term(1, "Blood culture", "rw-1")])
    item = Item("D6", "A blood culture was taken.", [Expected("Blood culture"), Expected("Culture")])
    record, _ = process(item, res, 1, "base", None, checks.Rules())
    assert record["expected"][1]["counted"] is False
    assert record["expected"][1]["nested_in"] == ["blood culture"]
    assert record["masked_sentence"] == item.sentence and "[T1]" not in record["prompt"]
    english = checks.summarise([record], checks.Rules())["english_side"]
    assert (english["expected_terms"], english["misses"]) == (1, 0)
    assert english["annotations_nested_in_a_longer_term"] == 1


def test_a_retrieved_term_inside_a_longer_miss_is_not_counted(tmp_path):
    res = resource(tmp_path, [term(1, "Health center", "rw-1")])
    item = Item("D10", "The health center staff were trained.",
                [Expected("Health center staff"), Expected("Health center")])
    record, _ = process(item, res, 1, "base", None, checks.Rules())
    assert record["masked_sentence"] == "The [T1] were trained."
    assert record["expected"][1]["counted"] is False
    english = checks.summarise([record], checks.Rules())["english_side"]
    assert (english["expected_terms"], english["retrieved"], english["misses"]) == (1, 0, 1)


def test_an_entry_dropped_by_k_is_a_miss_at_that_k(tmp_path):
    res = resource(tmp_path, [term(3, "Culture", "rw-3", category="Other"),
                              term(12, "Culture", "rw-12")])
    item = Item("D11", "The culture grew.", [Expected("Culture", entry_id=12)])
    at_one, _ = process(item, res, 1, "base", None, checks.Rules())
    assert at_one["expected"][0]["reason"] == "dropped_by_k"
    assert at_one["masked_sentence"] == item.sentence
    english = checks.summarise([at_one], checks.Rules())["english_side"]
    assert (english["expected_terms"], english["misses"], english["misses_dropped_by_k"]) == (1, 1, 1)
    at_all, _ = process(item, res, None, "base", None, checks.Rules())
    assert checks.summarise([at_all], checks.Rules())["english_side"]["term_recall"] == 1.0


def test_adherence_is_scored_against_the_annotated_entry(tmp_path):
    res = resource(tmp_path, [term(3, "Culture", "rw-3", category="Other"),
                              term(12, "Culture", "rw-12")])
    item = Item("D12", "The culture grew.", [Expected("Culture", entry_id=12)])
    record, _ = process(item, res, None, "base", Scripted("x rw-3 y"), checks.Rules())
    t = record["terms"][0]
    assert t["scored_against"] == [12] and t["lead_strict"] is False


def test_a_wrong_sense_retrieval_is_left_out_of_adherence(tmp_path):
    res = resource(tmp_path, [term(7, "Delivery", "rw-7"), term(8, "Oxygen", "rw-8")])
    item = Item("D13", "The delivery of oxygen.", [Expected("Oxygen")],
                wrong_sense=[Expected("Delivery", entry_id=7)])
    record, _ = process(item, res, 1, "base", Scripted("rw-7 rw-8"), checks.Rules())
    adherence = checks.summarise([record], checks.Rules())["adherence"]
    assert adherence["strict"] == {"used": 1, "of": 1, "rate": 1.0}
    assert adherence["wrong_sense_retrievals"]["used"] == 1


# --- (6) checks ------------------------------------------------------------------

def test_strict_and_tolerant_readings(tmp_path):
    res = resource(tmp_path, [term(1, "Fever", "pafoo ka'bar")])
    retrieved = scored(res.retrieve("Fever.", 1))
    none = checks.check_terms(retrieved, "pifoo ki'bar", checks.load_rules(rules_file(tmp_path)))
    assert none[0]["lead_strict"] is False and none[0]["lead_tolerant"] is None
    rules = checks.load_rules(rules_file(tmp_path, ["pa-", "pi"], ["ka'", "ki'"]))
    assert rules.tolerant and rules.version == "test" and len(rules.sha256) == 64
    got = checks.check_terms(retrieved, "Pifoo ki’bar.", rules)
    assert got[0]["lead_strict"] is False and got[0]["lead_tolerant"] is True
    assert checks.check_terms(retrieved, "pafoo ka'bar", rules)[0]["lead_strict"] is True
    assert checks.check_terms(retrieved, "pifoo ki'baz", rules)[0]["lead_tolerant"] is False


def test_variants_are_reported_apart_from_the_lead(tmp_path):
    res = resource(tmp_path, [term(1, "Fever", "rw-1", variants_rw="rw-2 / rw-3")])
    recs = checks.check_terms(scored(res.retrieve("Fever.", 1)), "x rw-3 y", checks.Rules())
    assert recs[0]["lead_strict"] is False and recs[0]["variant_strict"] is True
    record = {"annotated": False, "expected": None, "retrieved": [], "output": "x",
              "terms": recs, "status": "ok", "generation": []}
    summary = checks.summarise([record], checks.Rules())
    assert summary["adherence"]["strict"]["used"] == 0
    assert summary["adherence"]["strict_with_variants"]["used"] == 1
    assert summary["adherence"]["tolerant"] is None


def test_locate_finds_whole_words_only():
    assert locate("Prefever and fever.", ["fever"]) == (13, 18)
    assert locate("Two fevers.", ["fever"]) == (4, 10)
    assert locate("No match.", ["fever"]) is None


def test_a_sentence_not_in_nfc_is_masked_at_the_right_place(tmp_path):
    res = resource(tmp_path, [term(1, "Fever", "rw-1")])
    sentence = unicodedata.normalize("NFD", "Café fever and splenomegaly.")
    item = Item("D14", sentence, [Expected("Fever"), Expected("Splenomegaly")])
    record, _ = process(item, res, 1, "base", None, checks.Rules())
    assert record["masked_sentence"] == "Café fever and [T1]."


# --- (5) backbones ---------------------------------------------------------------

class _Response:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ollama(tags):
    seen = []

    def opener(request, timeout=None):
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        seen.append((request.full_url, body))
        if request.full_url.endswith("/api/generate"):
            return _Response({"response": " rw-1 \n", "done_reason": "stop",
                              "prompt_eval_count": 40, "eval_count": 3})
        if request.full_url.endswith("/api/tags"):
            return _Response({"models": tags})
        return _Response({"version": "0.0-test"})
    return opener, seen


def test_ollama_asks_for_greedy_decoding_and_names_the_checkpoint():
    opener, seen = _ollama([{"name": "gemma3:4b", "model": "gemma3:4b", "digest": "abc123"}])
    b = OllamaBackbone("gemma3:4b", Decoding(128, 7, context_tokens=4096),
                       host="127.0.0.1:11434", opener=opener)
    assert b.generate("p") == "rw-1"
    url, body = seen[0]
    assert url == "http://127.0.0.1:11434/api/generate" and body["stream"] is False
    assert body["options"] == {"temperature": 0, "top_k": 1, "seed": 7, "num_predict": 128,
                               "num_ctx": 4096}
    assert b.last == {"done_reason": "stop", "prompt_tokens": 40, "output_tokens": 3}
    d = b.describe()
    assert d["checkpoint"] == "gemma3:4b@abc123" and d["decoding"]["strategy"] == "greedy"


def test_ollama_names_latest_and_stops_without_the_model():
    opener, _ = _ollama([{"name": "gemma3:latest", "model": "gemma3:latest", "digest": "d1"}])
    assert OllamaBackbone("gemma3", opener=opener).describe()["checkpoint"] == "gemma3:latest@d1"
    with pytest.raises(SystemExit, match="ollama pull gemma3:4b"):
        OllamaBackbone("gemma3:4b", opener=opener).describe()


def test_ollama_not_running_says_so():
    def opener(request, timeout=None):
        raise OSError("connection refused")
    with pytest.raises(SystemExit, match="Is it running"):
        OllamaBackbone("gemma3:4b", opener=opener).generate("p")


def test_gemma_raw_turn():
    assert gemma_raw("x") == "<start_of_turn>user\nx<end_of_turn>\n<start_of_turn>model\n"


# --- a whole run -----------------------------------------------------------------

def _files(tmp_path):
    res_path = tmp_path / "terms.json"
    res_path.write_text(json.dumps({"schema_version": "1.1", "term_count": 1,
                                    "terms": [term(1, "Fever", "rw-1")]}), encoding="utf-8")
    items = tmp_path / "dev.csv"
    items.write_text("item,sentence,terms,reference\n"
                     "D1,Fever and splenomegaly.,Fever; Splenomegaly,REF-TEXT\n"
                     "D2,Fever again.,Fever,REF-TEXT\n", encoding="utf-8")
    return res_path, items


def test_a_run_logs_everything_outside_the_repository(tmp_path):
    res_path, items = _files(tmp_path)
    run_dir, manifest = run(items, res_path, tmp_path / "runs", k=1, arm="base",
                            rules_path=rules_file(tmp_path), backbone=Scripted("rw-1 [T1]"),
                            allow_dirty=True, say=lambda *_: None)
    assert {p.name for p in run_dir.iterdir()} == {"run.json", "items.jsonl", "outputs.tsv",
                                                   "miss_candidates.jsonl"}
    saved = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert saved["status"] == "finished" and saved["reproducible"] is False
    assert any("not the repository's own file" in r for r in saved["not_reproducible_because"])
    assert saved["resource"]["sha256"] == manifest["resource"]["sha256"]
    assert saved["prompt"]["template_sha256"] == prompt.TEMPLATE_SHA256
    assert saved["backbone"]["checkpoint"] == "test" and len(saved["code"]["sha256"]) == 64
    assert saved["settings"]["k"] == 1 and saved["settings"]["spelling"] == "orthographic"
    english = saved["summary"]["english_side"]
    assert (english["expected_terms"], english["retrieved"], english["misses"]) == (3, 2, 1)
    assert saved["summary"]["adherence"]["strict"]["used"] == 2
    lines = (run_dir / "miss_candidates.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["model_written"] is True
    for name in ("items.jsonl", "outputs.tsv", "run.json"):
        assert "REF-TEXT" not in (run_dir / name).read_text(encoding="utf-8")


def test_a_run_that_could_not_be_regenerated_does_not_start(tmp_path):
    res_path, items = _files(tmp_path)
    with pytest.raises(SystemExit, match="could not be regenerated"):
        run(items, res_path, tmp_path / "runs", backbone=EchoBackbone(), say=lambda *_: None)
    assert not (tmp_path / "runs").exists()


def test_a_run_never_writes_inside_the_repository(tmp_path):
    res_path, items = _files(tmp_path)
    with pytest.raises(SystemExit, match="inside the repository"):
        run(items, res_path, REPO_ROOT / "runs", backbone=EchoBackbone(), allow_dirty=True,
            say=lambda *_: None)


def test_the_real_export_loads():
    path = REPO_ROOT / "data" / "terms.json"
    if not path.exists():
        pytest.skip("no data/terms.json")
    res = Resource(path)
    assert res.term_count == len(json.loads(path.read_text(encoding="utf-8"))["terms"])
    assert not any("no English key" in n for n in res.notes)
    assert res.max_words >= 1
