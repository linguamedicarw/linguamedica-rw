"""
Reviewer agreement from a backup (scripts/agreement.py).

The script reads a folder written by scripts/export_scores.py, applies the
methodology's rules (latest blind row per reviewer and term, adjudication rows
excluded, agreement on the terms both scored, gold = both 4) and writes the
aggregates as JSON beside the backup, with the side-by-side sheet for
adjudication. The statistics are checked against fixed reference values and
the hand formulas; the round's scores cannot be read before --round-closed.
"""
import csv
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from models import db, Reviewer, Term, TermReview

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export_scores = _load("export_scores")
agreement = _load("agreement")

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone(timedelta(hours=-5)))
T0 = datetime(2026, 10, 6, 14, 0)          # naive UTC, as the site stores it


def _round(app):
    """
    Seven terms of a corpus "test" (the app boots with the real corpus v1, which
    the tests leave alone), five of them pilot, scored by Olive (OU) and Yvette (YV).

    Pilot terms A..D, both reviewers:  A 4/4, B 3/4, C 2/4 (Olive first gave a
    4, then corrected to 2: the latest row counts), D 4/4 (an adjudication row
    by CM on D is ignored). Pilot term E is scored by Olive only. Non-pilot
    terms F and G: F 4/4, G 1/3. Yvette's saves sit in two sittings two hours
    apart; Olive's are one sitting.
    """
    with app.app_context():
        olive = Reviewer(code="OU", username="olive", display_name="Olive Umuhoza",
                         must_change_password=False)
        olive.set_password("olive-pass-1234")
        yvette = Reviewer(code="YV", username="yvette", display_name="Yvette Nkurunziza",
                          must_change_password=False)
        yvette.set_password("yvette-pass-1234")
        spec = [("A", True, "Obstetrics"), ("B", True, "Obstetrics"), ("C", True, "Diagnostics"),
                ("D", True, "Diagnostics"), ("E", True, "Pharmacology"),
                ("F", False, "Pharmacology"), ("G", False, "Infectious Disease")]
        terms = {}
        for key, pilot, domain in spec:
            terms[key] = Term(english=f"Test term {key}", kinyarwanda=f"RW {key}",
                              corpus_version="test", corpus_key=f"T{key}", pilot=pilot,
                              published=False, domain=domain)
        plain = Term(english="Published term", kinyarwanda="RW published", published=True)
        db.session.add_all([olive, yvette, plain, *terms.values()])
        db.session.flush()

        def row(key, who, score, minutes, **extra):
            return TermReview(term_id=terms[key].id, reviewer=who, score=score,
                              shown_rw=terms[key].kinyarwanda,
                              reviewed_at=T0 + timedelta(minutes=minutes), **extra)

        db.session.add_all([
            row("A", "OU", 4, 0), row("B", "OU", 3, 3, note="=one step too general"),
            row("C", "OU", 4, 6), row("C", "OU", 2, 9, note="button slip corrected"),
            row("D", "OU", 4, 12), row("E", "OU", 3, 15, proposed_rw="-RW E alt"),
            row("F", "OU", 4, 18), row("G", "OU", 1, 21),
            row("A", "YV", 4, 60), row("B", "YV", 4, 62), row("C", "YV", 4, 64),
            row("D", "YV", 4, 200), row("F", "YV", 4, 202), row("G", "YV", 3, 204),
            row("D", "CM", 4, 300, is_adjudication=True),
            TermReview(term_id=plain.id, reviewer="OU", score=4, shown_rw="RW published",
                       reviewed_at=T0 + timedelta(minutes=400)),
            TermReview(term_id=terms["A"].id, reviewer="CM", score=1,
                       shown_rw="RW A", reviewed_at=T0 + timedelta(minutes=500)),
        ])
        db.session.commit()


def _backup(app, tmp_path):
    _round(app)
    folder, _ = export_scores.export(app.config["SQLALCHEMY_DATABASE_URI"], tmp_path / "backups",
                                     now=NOW)
    return folder


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# --- the rules ---------------------------------------------------------------

def test_pilot_agreement_applies_the_latest_blind_row_rule(app, tmp_path):
    folder = _backup(app, tmp_path)
    report, side, gold, a, b = agreement.analyse(folder, corpus="test", term_set="pilot", resamples=0)
    assert (a, b) == ("OU", "YV")
    assert report["terms"]["n_in_set"] == 5                      # pilot terms only
    assert report["terms"]["scored_by"] == {"OU": 5, "YV": 4}
    assert report["terms"]["scored_by_both"] == 4                # A, B, C, D
    assert report["terms"]["blind_rows_from_other_codes_ignored"] == ["CM"]
    ag = report["agreement"]
    assert ag["exact"]["count"] == 2 and ag["within_one"]["count"] == 3     # A, D exact; B within one
    assert ag["difference_counts"] == {"0": 2, "1": 1, "2": 1, "3": 0}       # C: latest 2 vs 4
    assert ag["both_4"] == 2 and ag["split_across_2_and_3"] == 1
    assert ag["table_rows_first_cols_second"]["2"]["4"] == 1
    assert report["reviewers"]["OU"]["terms_scored_more_than_once"] == 1
    assert report["reviewers"]["OU"]["saves_in_total"] == 6
    assert report["reviewers"]["OU"]["distribution"] == {"1": 0, "2": 1, "3": 2, "4": 2}
    assert report["reviewers"]["OU"]["with_note"] == 2
    assert report["reviewers"]["OU"]["with_alternative"] == 1
    assert report["by_pilot"] is None
    assert set(report["by_domain"]) == {"Obstetrics", "Diagnostics", "Pharmacology"}
    assert report["by_domain"]["Pharmacology"]["n_both_scored"] == 0
    assert gold == []                                            # only for --terms all


def test_the_whole_round_separates_pilot_from_the_rest_and_lists_gold(app, tmp_path):
    folder = _backup(app, tmp_path)
    report, side, gold, a, b = agreement.analyse(folder, corpus="test", term_set="all", resamples=0)
    assert report["terms"]["n_in_set"] == 7                      # the published term is not corpus
    assert report["terms"]["scored_by_both"] == 6
    assert report["agreement"]["both_4"] == 3                    # A, D and F
    assert report["by_pilot"]["pilot"]["n_both_scored"] == 4
    assert report["by_pilot"]["non-pilot"]["n_both_scored"] == 2
    assert report["by_pilot"]["non-pilot"]["within_one"]["count"] == 1   # G is 1 vs 3
    assert [g["english"] for g in gold] == ["Test term A", "Test term D", "Test term F"]


def test_the_sittings_profile_cuts_at_the_gap(app, tmp_path):
    folder = _backup(app, tmp_path)
    report, *_ = agreement.analyse(folder, corpus="test", term_set="all", resamples=0, gap_minutes=60)
    yv = report["reviewers"]["YV"]["sittings"]
    assert [s["terms"] for s in yv["sittings"]] == [3, 3]
    assert yv["sittings"][0]["start"]["utc"] == "2026-10-06T15:00:00+00:00"
    assert yv["sittings"][0]["minutes"] == 4
    assert yv["sittings"][0]["terms_per_hour"] == pytest.approx(45)
    assert yv["sittings"][0]["first_half"] is None               # fewer than four terms
    assert yv["terms_by_day_utc"] == {"2026-10-06": 6}
    ou = report["reviewers"]["OU"]["sittings"]
    assert [s["terms"] for s in ou["sittings"]] == [7]
    assert ou["sittings"][0]["first_half"]["terms"] == 3
    assert ou["sittings"][0]["second_half"]["terms"] == 4
    assert ou["sittings"][0]["median_gap_seconds"] == 180
    wide, *_ = agreement.analyse(folder, corpus="test", term_set="all", resamples=0, gap_minutes=180)
    assert [s["terms"] for s in wide["reviewers"]["YV"]["sittings"]["sittings"]] == [6]


# --- the outputs ---------------------------------------------------------------

def test_the_json_holds_aggregates_only_and_the_sheet_holds_the_terms(app, tmp_path, monkeypatch):
    folder = _backup(app, tmp_path)
    monkeypatch.setattr(agreement, "DEFAULT_ROOT", tmp_path / "backups")
    agreement.main(["--corpus", "test", "--terms", "all", "--round-closed", "--bootstrap", "50"])
    names = {p.name for p in folder.iterdir()}
    assert "side_by_side_all.csv" in names and "gold_terms.csv" in names
    json_name = next(n for n in names if n.startswith("agreement_all_") and n.endswith(".json"))
    text = (folder / json_name).read_text(encoding="utf-8")
    for secret in ("Test term", "RW A", "one step too general", "button slip", "RW E alt"):
        assert secret not in text
    report = json.loads(text)
    assert report["inputs"]["verified_against_manifest"] is True
    assert set(report["inputs"]["sha256"]) == {"terms.csv", "term_reviews.csv", "reviewers.csv"}
    assert report["parameters"]["reviewers"] == ["OU", "YV"]
    assert report["bootstrap"]["resamples"] == 50
    assert set(report["script"]["repository"]) == {"commit", "clean"}

    sheet = {r["english"]: r for r in _read(folder / "side_by_side_all.csv")}
    assert len(sheet) == 7
    assert sheet["Test term C"]["score_OU"] == "2" and sheet["Test term C"]["times_scored_OU"] == "2"
    assert sheet["Test term C"]["difference"] == "-2"
    assert sheet["Test term E"]["score_YV"] == "" and sheet["Test term E"]["shown_same"] == ""
    assert sheet["Test term E"]["proposed_rw_OU"] == "'-RW E alt"      # never read as a formula
    assert sheet["Test term B"]["note_OU"] == "'=one step too general"
    assert sheet["Test term A"]["gold"] == "yes" and sheet["Test term B"]["gold"] == ""
    assert [g["english"] for g in _read(folder / "gold_terms.csv")] == ["Test term A", "Test term D", "Test term F"]


def test_the_terminal_summary_carries_no_term_and_no_comment(app, tmp_path, capsys):
    folder = _backup(app, tmp_path)
    agreement.main(["--backup", str(folder), "--corpus", "test", "--bootstrap", "0"])
    printed = capsys.readouterr().out
    assert "Exact agreement: 2/4" in printed and "within one: 3/4" in printed
    assert "OU: scores 1/2/3/4 = 0/1/2/2" in printed
    for secret in ("Test term", "RW A", "one step too general", "RW E alt"):
        assert secret not in printed


# --- the guards ----------------------------------------------------------------

def test_the_round_cannot_be_read_before_it_closes(app, tmp_path):
    folder = _backup(app, tmp_path)
    with pytest.raises(SystemExit, match="round-closed"):
        agreement.main(["--backup", str(folder), "--terms", "all"])
    with pytest.raises(SystemExit, match="round-closed"):
        agreement.main(["--backup", str(folder), "--terms", "non-pilot"])
    assert not any(p.name.startswith("agreement_") for p in folder.iterdir())


def test_an_edited_backup_is_refused(app, tmp_path):
    folder = _backup(app, tmp_path)
    path = folder / "term_reviews.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("\n4,", "\n3,", 1), encoding="utf-8")
    with pytest.raises(SystemExit, match="does not match the checksum"):
        agreement.analyse(folder, corpus="test", resamples=0)


def test_outputs_never_land_inside_the_repository(app, tmp_path):
    folder = _backup(app, tmp_path)
    report, side, gold, a, b = agreement.analyse(folder, corpus="test", resamples=0)
    with pytest.raises(SystemExit, match="inside the repository"):
        agreement.write_outputs(report, side, gold, a, b, ROOT / "data", "pilot")


def test_two_reviewer_codes_are_required(app, tmp_path):
    folder = _backup(app, tmp_path)
    with pytest.raises(SystemExit, match="two reviewers"):
        agreement.analyse(folder, corpus="test", reviewers=["OU"], resamples=0)


# --- the statistics --------------------------------------------------------------

def test_perfect_agreement_scores_one_everywhere():
    pairs = [(1, 1), (2, 2), (3, 3), (4, 4), (4, 4), (3, 3)]
    for w in ("nominal", "linear", "quadratic"):
        assert agreement.cohen_kappa(pairs, w) == pytest.approx(1.0)
    for m in ("nominal", "ordinal", "interval"):
        assert agreement.krippendorff_alpha(pairs, m) == pytest.approx(1.0)
    assert agreement.krippendorff_alpha([(4, 4), (4, 4)], "ordinal") is None    # one value only
    assert agreement.cohen_kappa([(4, 4), (4, 4)], "nominal") is None


def test_kappa_matches_the_textbook_two_by_two_table():
    # Rows: rater A said 1 / 2; columns: rater B said 1 / 2.  [[20, 5], [10, 15]]
    pairs = [(1, 1)] * 20 + [(1, 2)] * 5 + [(2, 1)] * 10 + [(2, 2)] * 15
    assert agreement.cohen_kappa(pairs, "nominal") == pytest.approx(0.4)      # p_o 0.7, p_e 0.5
    # With two categories in use, every weighting is the same kappa.
    assert agreement.cohen_kappa(pairs, "linear") == pytest.approx(0.4)
    assert agreement.cohen_kappa(pairs, "quadratic") == pytest.approx(0.4)


def test_nominal_alpha_follows_the_two_rater_formula():
    # For two raters and no missing values: alpha = 1 - (n-1)/n * (1-p_o)/(1-p_e),
    # p_e from the pooled margins (Scott's pi), n = the number of values = 2N.
    pairs = [(1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (3, 4), (4, 4), (4, 4), (4, 3), (2, 4),
             (3, 3), (4, 4)]
    n_units, n_values = len(pairs), 2 * len(pairs)
    p_o = sum(1 for a, b in pairs if a == b) / n_units
    pooled = [v for pair in pairs for v in pair]
    p_e = sum((pooled.count(level) / n_values) ** 2 for level in (1, 2, 3, 4))
    expected = 1 - (n_values - 1) / n_values * (1 - p_o) / (1 - p_e)
    assert agreement.krippendorff_alpha(pairs, "nominal") == pytest.approx(expected)
    # Two categories in use: the ordinal and interval distances are one constant,
    # so all three alphas coincide.
    two = [(1, 1), (1, 2), (2, 2), (2, 1), (1, 1), (2, 2), (2, 2), (1, 2)]
    nominal = agreement.krippendorff_alpha(two, "nominal")
    assert agreement.krippendorff_alpha(two, "ordinal") == pytest.approx(nominal)
    assert agreement.krippendorff_alpha(two, "interval") == pytest.approx(nominal)


def test_the_statistics_match_the_reference_implementations():
    # Reference values from the krippendorff package (alpha) and
    # scikit-learn's cohen_kappa_score (kappa) on the same twelve pairs.
    pairs = [(1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (3, 4), (4, 4), (4, 4), (4, 3), (2, 4),
             (3, 3), (4, 4)]
    assert agreement.krippendorff_alpha(pairs, "nominal") == pytest.approx(0.441748, abs=1e-6)
    assert agreement.krippendorff_alpha(pairs, "ordinal") == pytest.approx(0.656825, abs=1e-6)
    assert agreement.krippendorff_alpha(pairs, "interval") == pytest.approx(0.703226, abs=1e-6)
    assert agreement.cohen_kappa(pairs, "nominal") == pytest.approx(0.423077, abs=1e-6)
    assert agreement.cohen_kappa(pairs, "linear") == pytest.approx(0.566265, abs=1e-6)
    assert agreement.cohen_kappa(pairs, "quadratic") == pytest.approx(0.698113, abs=1e-6)


def test_the_bootstrap_is_reproducible_from_its_seed():
    scored = [(i, a, b) for i, (a, b) in enumerate(
        [(1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (3, 4), (4, 4), (4, 4), (4, 3), (2, 4),
         (3, 3), (4, 4)])]
    first = agreement.bootstrap_block(scored, 200, 20261010)
    second = agreement.bootstrap_block(scored, 200, 20261010)
    assert first == second
    exact = first["intervals"]["exact"]
    assert 0 <= exact["low"] <= 7 / 12 <= exact["high"] <= 1
    assert agreement.bootstrap_block(scored, 0, 1) is None
