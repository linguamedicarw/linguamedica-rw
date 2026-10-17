"""
Per-reviewer profile by domain and sitting half (scripts/reviewer_profile.py).

Built on a small hand-made backup folder, so every count can be checked by eye.
"""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("reviewer_profile",
                                               ROOT / "scripts" / "reviewer_profile.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)


def _write(path, fields, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _backup(tmp_path):
    """
    Eight terms, two domains (A: terms 1-4, B: terms 5-8), all scored by both.
    XX: one sitting of 8 saves a minute apart; scores 4,4,4,4 then 1,1,4,1,
        so 1s go from 0% to 75% between halves, all in domain B.
        Term 2 is re-scored: first 1, latest 4.
    YY: two sittings of 4 (two hours apart), all 4s except term 3 = 2.
    An adjudication row (CM) is ignored.
    """
    folder = tmp_path / "2026-10-17_1732"
    folder.mkdir()
    terms = [{"id": i, "english": f"t{i}", "corpus_version": "v1", "pilot": "false",
              "domain": "A" if i <= 4 else "B"} for i in range(1, 9)]
    xx = [4, 4, 4, 4, 1, 1, 4, 1]
    rows, rid = [], 0
    def add(term, who, score, minute, adj="false", note=""):
        nonlocal rid
        rid += 1
        h, m = divmod(minute, 60)
        rows.append({"id": rid, "term_id": term, "reviewer": who, "score": score,
                     "proposed_rw": "", "shown_rw": "", "note": note,
                     "is_adjudication": adj, "reviewed_at": f"2026-10-07T{10+h:02d}:{m:02d}:00"})
    add(2, "XX", 1, 0)                       # replaced later
    for i, s in enumerate(xx, start=1):
        add(i, "XX", s, i, note="n" if i <= 4 else "")
    for i in range(1, 9):
        add(i, "YY", 2 if i == 3 else 4, (i if i <= 4 else 120 + i))
    add(1, "CM", 1, 300, adj="true")
    _write(folder / "terms.csv", list(terms[0]), terms)
    _write(folder / "term_reviews.csv", list(rows[0]), rows)
    _write(folder / "reviewers.csv", ["id", "code", "display_name"],
           [{"id": 1, "code": "XX", "display_name": "X"}, {"id": 2, "code": "YY", "display_name": "Y"}])
    manifest = {"files": {n: {"sha256": hashlib.sha256((folder / n).read_bytes()).hexdigest()}
                          for n in ("terms.csv", "term_reviews.csv", "reviewers.csv")}}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


def test_domain_distributions_use_the_latest_blind_score(tmp_path):
    report, _ = rp.profile(_backup(tmp_path), term_set="all")
    xx = report["reviewers"]["XX"]
    assert xx["distribution"] == {"1": 3, "2": 0, "3": 0, "4": 5}      # term 2's early 1 replaced
    assert xx["by_domain"]["A"]["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 4}
    assert xx["by_domain"]["B"]["distribution"] == {"1": 3, "2": 0, "3": 0, "4": 1}
    assert report["parameters"]["reviewers"] == ["XX", "YY"]          # CM never counted


def test_sitting_halves_show_the_drift_and_where_it_falls(tmp_path):
    report, _ = rp.profile(_backup(tmp_path), term_set="all")
    [s] = report["reviewers"]["XX"]["sittings_of_4_or_more"]
    assert s["terms"] == 8
    assert s["first_half"]["share_1"] == 0 and s["second_half"]["share_1"] == 0.75
    assert s["second_half"]["ones_by_domain"] == {"B": 3}
    assert s["first_half"]["comment_rate"] == 1 and s["second_half"]["comment_rate"] == 0
    assert s["first_half"]["median_gap_seconds"] == 60


def test_a_two_hour_pause_starts_a_new_sitting(tmp_path):
    report, _ = rp.profile(_backup(tmp_path), term_set="all")
    assert [s["terms"] for s in report["reviewers"]["YY"]["sittings_of_4_or_more"]] == [4, 4]


def test_the_round_cannot_be_read_before_it_closes(tmp_path):
    folder = _backup(tmp_path)
    with pytest.raises(SystemExit, match="round-closed"):
        rp.main(["--backup", str(folder), "--terms", "all"])
