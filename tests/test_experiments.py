"""
Development items from TICO-19 (scripts/dev_items_tico19.py) and the comparison of two
runs (scripts/compare_runs.py), on inputs small enough to check by eye. No Kinyarwanda is
written here: renderings and references are placeholders.
"""
import csv
import importlib.util
import json
from pathlib import Path

import pytest

from rag.backbones import Backbone, Decoding
from rag.pipeline import run
from rag.resource import Resource

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dev = _load("dev_items_tico19")
cmp = _load("compare_runs")


def _terms(tmp_path, *pairs):
    rows = [{"id": i, "english": e, "kinyarwanda": rw, "variants_en": None,
             "variants_rw": None, "example_en": None, "example_rw": None, "etymology": None,
             "category": "Diagnostics", "contributed_by": None, "source": None,
             "date_added": None, "created_at": None}
            for i, (e, rw) in enumerate(pairs, start=1)]
    path = tmp_path / "terms.json"
    path.write_text(json.dumps({"schema_version": "1.1", "term_count": len(rows),
                                "terms": rows}), encoding="utf-8")
    return path


HEADER = "\t".join(dev.COLUMNS)


def _tico(tmp_path, rows, name="dev.en-rw.tsv"):
    folder = tmp_path / "tico"
    folder.mkdir(exist_ok=True)
    path = folder / name
    lines = [HEADER] + ["\t".join(["en", "rw", en, rw, sid, "https://example.org/x",
                                   "CC BY 4.0", "T1"]) for sid, en, rw in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- development items -------------------------------------------------------------

def test_tico_is_read_without_quoting(tmp_path):
    path = _tico(tmp_path, [("S1", 'He said "fever" twice.', "REF-1"),
                            ("S2", "A second line.", "REF-2")])
    rows = dev.read_tico(path)
    assert [r["stringID"] for r in rows] == ["S1", "S2"]     # the quote did not merge lines
    assert rows[0]["english"] == 'He said "fever" twice.'


def test_tico_rows_are_checked(tmp_path):
    bad = tmp_path / "dev.en-rw.tsv"
    bad.write_text(HEADER + "\nen\trw\tonly four\tfields\n", encoding="utf-8")
    with pytest.raises(dev.TicoError, match="fields"):
        dev.read_tico(bad)
    twice = _tico(tmp_path, [("S1", "a", "b"), ("S1", "c", "d")])
    with pytest.raises(dev.TicoError, match="used twice"):
        dev.read_tico(twice)


def test_only_the_dev_split_is_accepted(tmp_path):
    test_split = _tico(tmp_path, [("S1", "Fever.", "REF")], name="test.en-rw.tsv")
    with pytest.raises(SystemExit, match="dev split only"):
        dev.main(["--tico", str(test_split), "--out", str(tmp_path / "out")])


def test_dev_items_hold_a_term_and_keep_the_references_apart(tmp_path):
    rows = [(f"S{n}", f"Sentence {n} about fever." if n % 2 else f"Sentence {n}, nothing.",
             f"REF-{n}") for n in range(1, 21)]
    path = _tico(tmp_path, rows)
    res = _terms(tmp_path, ("Fever", "rw-1"))
    out = tmp_path / "out"
    assert dev.main(["--tico", str(path), "--n", "6", "--seed", "7", "--resource", str(res),
                     "--out", str(out)]) == 0
    sha = Resource(res).sha256[:12]
    items = out / f"tico19-dev_6_seed7_{sha}.csv"
    refs = out / f"tico19-dev_6_seed7_{sha}_references.tsv"
    manifest = json.loads((out / f"tico19-dev_6_seed7_{sha}_manifest.json").read_text())
    with open(items, encoding="utf-8", newline="") as f:
        chosen = list(csv.DictReader(f))
    assert list(chosen[0]) == ["item", "sentence"] and len(chosen) == 6
    assert all("fever" in r["sentence"] for r in chosen)                  # a term in each
    ids = [r["item"] for r in chosen]
    assert ids == sorted(ids, key=lambda s: int(s[1:]))                    # file order
    assert "REF" not in items.read_text(encoding="utf-8")
    with open(refs, encoding="utf-8", newline="") as f:
        ref_rows = list(csv.reader(f, delimiter="\t"))
    assert ref_rows[0] == ["item", "reference"] and [r[0] for r in ref_rows[1:]] == ids
    assert manifest["eligible"] == 10 and manifest["chosen"] == 6 and manifest["seed"] == 7
    assert manifest["terms_in_chosen"]["by_term"] == {"Fever": 6}
    # the same inputs give the same draw, and an existing file is not overwritten
    with pytest.raises(SystemExit, match="exists already"):
        dev.main(["--tico", str(path), "--n", "6", "--seed", "7", "--resource", str(res),
                  "--out", str(out)])
    again = tmp_path / "again"
    dev.main(["--tico", str(path), "--n", "6", "--seed", "7", "--resource", str(res),
              "--out", str(again)])
    assert (again / items.name).read_bytes() == items.read_bytes()


# --- comparing two runs -------------------------------------------------------------

class Says(Backbone):
    """Answers every prompt with the same text."""

    def __init__(self, text, checkpoint="test", precision="P"):
        super().__init__(Decoding())
        self.text, self.checkpoint, self.precision = text, checkpoint, precision
        self.name = "says"

    def generate(self, prompt):
        self.last = {"done_reason": "stop"}
        return self.text

    def describe(self):
        return dict(super().describe(), checkpoint=self.checkpoint, precision=self.precision)


def _items(tmp_path, name="dev.csv"):
    path = tmp_path / name
    path.write_text("item,sentence\nD1,Fever today.\nD2,Fever and cough.\nD3,Nothing here.\n",
                    encoding="utf-8")
    return path


def _run(tmp_path, items, res, backbone, name, k=1):
    run_dir, _ = run(items, res, tmp_path / "runs", k=k, backbone=backbone, name=name,
                     allow_dirty=True, say=lambda *_: None)
    return run_dir


def test_two_runs_compare_on_adherence(tmp_path):
    res, items = _terms(tmp_path, ("Fever", "rw-1")), _items(tmp_path)
    a = _run(tmp_path, items, res, Says("rw-1 x", "m@q8", "Q8_0"), "a")
    b = _run(tmp_path, items, res, Says("y z", "m@bf16", "bfloat16"), "b")
    same = _run(tmp_path, items, res, Says("rw-1 x", "m@bf16", "bfloat16"), "same")
    _, _, result = cmp.compare(a, b, resamples=200)
    s = result["adherence"]["strict"]
    assert s["terms"] == 2 and s["a"]["used"] == 2 and s["b"]["used"] == 0
    assert s["difference_b_minus_a"] == -1.0 and s["ci95"] == [-1.0, -1.0]
    assert (s["used_in_a_only"], s["used_in_b_only"]) == (2, 0)
    assert result["adherence"]["tolerant"] is None
    assert result["identical_outputs"] == {"items": 0, "of": 3, "share": 0.0}
    assert result["a"]["precision"] == "Q8_0" and result["b"]["precision"] == "bfloat16"
    _, _, result = cmp.compare(a, same, resamples=200)
    assert result["adherence"]["strict"]["difference_b_minus_a"] == 0.0
    assert result["identical_outputs"]["share"] == 1.0
    assert "rw-1" not in json.dumps(result)                    # aggregates only, no output text


def test_runs_that_differ_beyond_the_model_are_not_compared(tmp_path):
    res, items = _terms(tmp_path, ("Fever", "rw-1")), _items(tmp_path)
    a = _run(tmp_path, items, res, Says("rw-1"), "a")
    k3 = _run(tmp_path, items, res, Says("rw-1"), "k3", k=3)
    with pytest.raises(cmp.Mismatch, match="settings"):
        cmp.compare(a, k3)
    other = _run(tmp_path, _items(tmp_path, "other.csv"), res, Says("rw-1"), "other")
    other_items = other / "items.jsonl"                      # same text, other file name:
    assert other_items.exists()                              # the hash is what counts
    cmp.compare(a, other, resamples=10)
    saved = json.loads((a / "run.json").read_text())
    saved["status"] = "running"
    (a / "run.json").write_text(json.dumps(saved))
    with pytest.raises(SystemExit, match="not finished"):
        cmp.compare(a, other)


def test_chrf_against_references(tmp_path):
    pytest.importorskip("sacrebleu")
    res, items = _terms(tmp_path, ("Fever", "rw-1")), _items(tmp_path)
    a = _run(tmp_path, items, res, Says("rw-1 alpha beta"), "a")
    b = _run(tmp_path, items, res, Says("gamma delta"), "b")
    refs = tmp_path / "refs.tsv"
    refs.write_text("item\treference\nD1\trw-1 alpha beta\nD2\trw-1 alpha beta\n"
                    "D3\trw-1 alpha beta\n", encoding="utf-8")
    _, _, result = cmp.compare(a, b, refs, resamples=200)
    c = result["chrf_plus_plus"]
    assert c["items"] == 3 and c["a"] == 100.0 and c["b"] < c["a"]
    assert c["difference_b_minus_a"] < 0 and c["ci95"][1] <= 0
    assert "nc:6|nw:2" in c["signature"]
    with pytest.raises(SystemExit, match="item<TAB>reference"):
        bad = tmp_path / "bad.tsv"
        bad.write_text("id\tref\n", encoding="utf-8")
        cmp.compare(a, b, bad)


def test_the_comparison_is_written_outside_the_repository(tmp_path):
    res, items = _terms(tmp_path, ("Fever", "rw-1")), _items(tmp_path)
    a = _run(tmp_path, items, res, Says("rw-1"), "a")
    b = _run(tmp_path, items, res, Says("x"), "b")
    assert cmp.main([str(a), str(b), "--resamples", "50"]) == 0
    written = json.loads((tmp_path / "runs" / "compare_a__b.json").read_text())
    assert written["items"]["compared"] == 3
    with pytest.raises(SystemExit, match="inside the repository"):
        cmp.main([str(a), str(b), "--out", str(ROOT / "runs")])


# --- NLLB calibration ----------------------------------------------------------------

nllb = _load("nllb_calibration")


class Echoes:
    """Stands in for NLLB: 'translates' a sentence into a placeholder built from it."""

    def __init__(self, stop_after=None):
        self.calls, self.stop_after = 0, stop_after

    def translate(self, sentences):
        self.calls += 1
        if self.stop_after is not None and self.calls > self.stop_after:
            raise RuntimeError("preempted")
        return [f"HYP {s.split()[0]}" for s in sentences]

    def describe(self):
        return {"runtime": "test"}


def _tico_dir(tmp_path):
    root = tmp_path / "tico19-testset"
    for split, n in (("dev", 5), ("test", 7)):
        (root / split).mkdir(parents=True)
        lines = [HEADER] + ["\t".join(["en", "rw", f"W{split}{i} sentence {i}.", f"HYP W{split}{i}",
                                       f"{split}:{i}", "u", "CC BY 4.0", "T"])
                            for i in range(1, n + 1)]
        (root / split / f"{split}.en-rw.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    model = tmp_path / "ct2"
    model.mkdir()
    return root, model


def _translate(tmp_path, root, model, engine, compute="int8", name="calib"):
    return nllb.translate(root, model, compute, name, out=tmp_path / "runs", batch=2,
                          engine=engine, say=lambda *_: None)


def test_calibration_translates_both_splits_and_resumes(tmp_path):
    root, model = _tico_dir(tmp_path)
    whole, m = _translate(tmp_path, root, model, Echoes(), name="whole")
    assert m["status"] == "finished" and m["settings"]["beam"] == 4
    assert [len(nllb._complete(whole / f"hyp.{s}.jsonl")) for s in ("dev", "test")] == [5, 7]
    with pytest.raises(RuntimeError, match="preempted"):
        _translate(tmp_path, root, model, Echoes(stop_after=4), name="cut")
    cut = tmp_path / "runs" / "cut"
    assert len(nllb._complete(cut / "hyp.dev.jsonl")) == 5
    assert len(nllb._complete(cut / "hyp.test.jsonl")) == 2
    with open(cut / "hyp.test.jsonl", "a", encoding="utf-8") as f:
        f.write('{"id": "test:3", "hyp": "HY')                     # a line cut mid-write
    _translate(tmp_path, root, model, Echoes(), name="cut")
    for s in ("dev", "test"):
        assert (cut / f"hyp.{s}.jsonl").read_text() == (whole / f"hyp.{s}.jsonl").read_text()
    saved = json.loads((cut / "run.json").read_text())
    assert saved["status"] == "finished" and len(saved["resumed"]) == 1
    with pytest.raises(SystemExit, match="is finished"):
        _translate(tmp_path, root, model, Echoes(), name="cut")


def test_calibration_resumes_only_with_the_same_settings(tmp_path):
    root, model = _tico_dir(tmp_path)
    with pytest.raises(RuntimeError):
        _translate(tmp_path, root, model, Echoes(stop_after=1), name="cut")
    with pytest.raises(SystemExit, match="differ"):
        _translate(tmp_path, root, model, Echoes(), compute="float16", name="cut")
    with pytest.raises(SystemExit, match="compute-type"):
        _translate(tmp_path, root, model, Echoes(), compute="int4", name="other")


def test_calibration_scores(tmp_path):
    pytest.importorskip("sacrebleu")
    root, model = _tico_dir(tmp_path)
    run_dir, _ = _translate(tmp_path, root, model, Echoes())
    result = nllb.score(run_dir)
    assert result["segments"] == {"dev": 5, "test": 7, "all": 12}
    assert result["scores"]["chrF++"]["all"] == 100.0           # placeholders match exactly
    assert result["scores"]["TER"]["all"] == 0.0
    for spm in ("flores200", "flores101"):                      # needs sentencepiece and
        s = result["scores"][f"spBLEU ({spm})"]                  # the network, else skipped
        assert "skipped" in s or s["all"] == 100.0
    assert (run_dir / "scores.json").exists()
    (root / "dev" / "dev.en-rw.tsv").write_text(
        (root / "dev" / "dev.en-rw.tsv").read_text() + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="SHA-256 differs"):
        nllb.score(run_dir)


def test_calibration_drops_a_line_cut_inside_a_character(tmp_path):
    root, model = _tico_dir(tmp_path)

    class Accented(Echoes):
        def translate(self, sentences):
            return [h + " ’" for h in super().translate(sentences)]

    whole, _ = _translate(tmp_path, root, model, Accented(), name="whole")
    with pytest.raises(RuntimeError):
        _translate(tmp_path, root, model, Accented(stop_after=4), name="cut")
    cut = tmp_path / "runs" / "cut"
    data = (cut / "hyp.test.jsonl").read_bytes()
    (cut / "hyp.test.jsonl").write_bytes(data[:data.rindex("’".encode()) + 1])
    _translate(tmp_path, root, model, Accented(), name="cut")
    assert (cut / "hyp.test.jsonl").read_bytes() == (whole / "hyp.test.jsonl").read_bytes()
    assert not list(cut.glob("*.tmp"))


# --- found by the second review (11 November 2026) -----------------------------------

def test_runs_from_different_pipeline_code_are_not_compared(tmp_path):
    res, items = _terms(tmp_path, ("Fever", "rw-1")), _items(tmp_path)
    a = _run(tmp_path, items, res, Says("rw-1"), "a")
    b = _run(tmp_path, items, res, Says("rw-1"), "b")
    saved = json.loads((b / "run.json").read_text())
    saved["code"]["sha256"] = "0" * 64
    (b / "run.json").write_text(json.dumps(saved))
    with pytest.raises(cmp.Mismatch, match="pipeline code"):
        cmp.compare(a, b)


def test_the_code_hash_ignores_hidden_files(monkeypatch, tmp_path):
    import shutil
    from rag import pipeline
    copy = tmp_path / "repo" / "rag"                 # a copy: the real package is not touched
    shutil.copytree(Path(pipeline.__file__).parent, copy,
                    ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(pipeline, "__file__", str(copy / "pipeline.py"))
    monkeypatch.setattr(pipeline, "REPO_ROOT", tmp_path / "repo")
    before = pipeline.code_sha256()
    (copy / ".DS_Store").write_bytes(b"finder")
    assert pipeline.code_sha256() == before
    (copy / "prompt.py").write_text((copy / "prompt.py").read_text() + "# changed\n")
    assert pipeline.code_sha256() != before


def test_an_output_with_a_line_separator_character_loads(tmp_path):
    res, items = _terms(tmp_path, ("Fever", "rw-1")), _items(tmp_path)
    a = _run(tmp_path, items, res, Says("rw-1 x\u0085y"), "a")
    b = _run(tmp_path, items, res, Says("rw-1 x"), "b")
    _, _, result = cmp.compare(a, b, resamples=20)
    assert result["items"]["compared"] == 3


def test_the_report_survives_items_without_terms(tmp_path):
    res = _terms(tmp_path, ("Fever", "rw-1"))
    items = tmp_path / "plain.csv"
    items.write_text("item,sentence\nP1,Nothing here.\n", encoding="utf-8")
    a = _run(tmp_path, items, res, Says("x"), "a")
    b = _run(tmp_path, items, res, Says("y"), "b")
    _, _, result = cmp.compare(a, b, resamples=20)
    assert any("no retrieved term" in line for line in cmp.report(result))


def test_convert_never_empties_a_folder_holding_other_files(tmp_path):
    target = tmp_path / "ct2"
    target.mkdir()
    (target / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(SystemExit, match="holds other files"):
        nllb.convert("facebook/nllb-200-3.3B", target)
    assert (target / "notes.txt").read_text(encoding="utf-8") == "keep me"
