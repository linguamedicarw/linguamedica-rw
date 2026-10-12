#!/usr/bin/env python3
"""
agreement.py - reviewer agreement for the annotation round, from a backup.

WHAT THIS DOES
    Reads one dated backup folder written by scripts/export_scores.py and
    computes, for two reviewers, how far they agree on the terms both scored:

        agreement_<set>_<date>.json   THE NUMBERS FOR THE THESIS: counts,
                                      exact and within-one agreement, Cohen's
                                      kappa (nominal, linear, quadratic),
                                      Krippendorff's alpha (nominal, ordinal,
                                      interval) with bootstrap intervals, the
                                      score distributions, the 4 x 4 table,
                                      the figures by domain and by pilot/round,
                                      comment rates, re-score counts and each
                                      reviewer's sittings (the fatigue check).
                                      Aggregates only: no term, no comment, no
                                      rendering appears in it.
        side_by_side_<set>.csv        one row per term with both reviewers'
                                      latest scores, alternatives and comments,
                                      for adjudication. Stays with the editor.
        gold_terms.csv                the terms both reviewers gave a 4 (only
                                      for --terms all): the Aim 3 gold list.

    Every number is derived from term_reviews.csv, terms.csv and reviewers.csv
    in the backup, never from the live site and never from a spreadsheet, so
    anyone with the backup folder and this script gets the same numbers.

THE RULES IT APPLIES (the validation methodology, v2)
    A reviewer's score for a term is the latest blind row for that reviewer
    and term, by reviewed_at then id; adjudication rows never count. Replaced
    rows are kept in the backup and counted here as re-scores, not as scores.
    Agreement is computed on the terms both reviewers scored. A term is gold
    when both latest blind scores are 4. Scores are read after the round
    closes: --terms all and --terms non-pilot refuse to run without
    --round-closed, so a weekly backup can be analysed for the pilot (closed
    on 5 October 2026) without anyone seeing the round before its close.

GUARANTEES
    Read-only on the backup. The three input files are checksummed against the
    backup's manifest.json before anything is computed, and the checksums, the
    backup's name, the repository commit and every parameter are written into
    the JSON, so a number in the thesis can be traced to the file it came from.
    Never inside the repository: outputs go beside the backup (or --out), and
    a folder inside the repo is refused, as in export_scores.py.
    Timestamps are UTC as stored by the site. --tz CODE=Area/City shows a
    reviewer's sittings in a local zone as well; nothing else uses it.

HOW TO RUN (from the repo root, with the venv active)
    python scripts/agreement.py                       newest backup, pilot terms
    python scripts/agreement.py --terms all --round-closed
    python scripts/agreement.py --backup ~/LinguaMedica-backups/2026-10-16_0900 \\
        --terms all --round-closed --tz OU=Africa/Kigali
    The terminal shows the aggregates; the files land beside the backup.
"""

import argparse
import csv
import hashlib
import json
import math
import platform
import random
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:                     # Python < 3.9: --tz is simply unavailable
    ZoneInfo = None

SCRIPT_VERSION = "1.0"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = Path.home() / "LinguaMedica-backups"
LEVELS = (1, 2, 3, 4)
INPUT_FILES = ("terms.csv", "term_reviews.csv", "reviewers.csv")
TERM_SETS = ("pilot", "all", "non-pilot")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

SIDE_BY_SIDE_FIELDS = [
    "term_id", "corpus_key", "english", "domain", "pilot",
    "shown_rw_{a}", "shown_rw_{b}", "shown_same",
    "score_{a}", "score_{b}", "difference", "gold",
    "proposed_rw_{a}", "proposed_rw_{b}", "note_{a}", "note_{b}",
    "reviewed_at_{a}", "reviewed_at_{b}", "times_scored_{a}", "times_scored_{b}",
]


# --------------------------------------------------------------------------
# Reading the backup
# --------------------------------------------------------------------------

def newest_backup(root=None):
    root = Path(root or DEFAULT_ROOT).expanduser()
    folders = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if not folders:
        sys.exit(f"No backup folder under {root}. Run scripts/export_scores.py first, "
                 "or name one with --backup.")
    return folders[-1]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bool(cell):
    return str(cell).strip().lower() in ("true", "1", "t", "yes")


def _when(cell):
    """reviewed_at as the site stored it: naive UTC, ISO text in the backup."""
    cell = (cell or "").strip()
    if not cell:
        return None
    value = datetime.fromisoformat(cell)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_backup(folder):
    """The three tables and the manifest; the files must match the manifest."""
    folder = Path(folder).expanduser().resolve()
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        sys.exit(f"{folder} has no manifest.json: it is not a backup written by "
                 "scripts/export_scores.py.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = {}
    for name in INPUT_FILES:
        path = folder / name
        if not path.is_file():
            sys.exit(f"{folder} has no {name}.")
        digest = _sha256(path)
        recorded = manifest.get("files", {}).get(name, {}).get("sha256")
        if digest != recorded:
            sys.exit(f"{name} does not match the checksum in manifest.json: the backup "
                     "has been edited since it was written. Analyse an untouched "
                     "backup (run scripts/export_scores.py again if needed).")
        checks[name] = digest
    tables = {name: _read_csv(folder / name) for name in INPUT_FILES}
    return folder, manifest, checks, tables


# --------------------------------------------------------------------------
# The rules: term set, latest blind score, the pairs
# --------------------------------------------------------------------------

def select_terms(terms, corpus, term_set):
    chosen = [t for t in terms if (t.get("corpus_version") or "").strip() == corpus]
    if term_set == "pilot":
        chosen = [t for t in chosen if _bool(t.get("pilot"))]
    elif term_set == "non-pilot":
        chosen = [t for t in chosen if not _bool(t.get("pilot"))]
    return {int(t["id"]): t for t in chosen}


def latest_blind(reviews, term_ids, reviewers):
    """
    {reviewer: {term_id: row}} with the latest blind row per reviewer and term
    (reviewed_at, then id), plus {reviewer: {term_id: times_scored}}.
    """
    history = defaultdict(lambda: defaultdict(list))
    for r in reviews:
        if _bool(r.get("is_adjudication")):
            continue
        term_id = int(r["term_id"])
        code = (r.get("reviewer") or "").strip()
        if term_id in term_ids and code in reviewers:
            history[code][term_id].append(r)
    latest, times = {}, {}
    for code in reviewers:
        latest[code], times[code] = {}, {}
        for term_id, rows in history[code].items():
            rows.sort(key=lambda r: (_when(r.get("reviewed_at")) or datetime.min, int(r["id"])))
            latest[code][term_id] = rows[-1]
            times[code][term_id] = len(rows)
    return latest, times


def score_pairs(latest, a, b):
    """[(term_id, score_a, score_b)] for the terms both reviewers scored, by term id."""
    shared = sorted(set(latest[a]) & set(latest[b]))
    return [(t, int(latest[a][t]["score"]), int(latest[b][t]["score"])) for t in shared]


# --------------------------------------------------------------------------
# Statistics (pure Python; the formulas are the standard ones)
# --------------------------------------------------------------------------

def confusion(pairs):
    table = {x: {y: 0 for y in LEVELS} for x in LEVELS}
    for x, y in pairs:
        table[x][y] += 1
    return table


def cohen_kappa(pairs, weighting="nominal"):
    """
    Cohen's kappa for two raters on an ordinal 1..4 scale. weighting is
    "nominal" (disagreement weight 1 off the diagonal), "linear" (|a-b|/3) or
    "quadratic" ((a-b)^2/9). None when expected disagreement is zero.
    """
    n = len(pairs)
    if n == 0:
        return None
    table = confusion(pairs)
    rows = {x: sum(table[x].values()) for x in LEVELS}
    cols = {y: sum(table[x][y] for x in LEVELS) for y in LEVELS}
    span = len(LEVELS) - 1

    def w(x, y):
        if weighting == "nominal":
            return 0.0 if x == y else 1.0
        if weighting == "linear":
            return abs(x - y) / span
        if weighting == "quadratic":
            return (x - y) ** 2 / span ** 2
        raise ValueError(weighting)

    observed = sum(w(x, y) * table[x][y] for x in LEVELS for y in LEVELS) / n
    expected = sum(w(x, y) * rows[x] * cols[y] for x in LEVELS for y in LEVELS) / (n * n)
    if expected == 0:
        return None
    return 1.0 - observed / expected


def krippendorff_alpha(pairs, metric="ordinal"):
    """
    Krippendorff's alpha for two raters with no missing values, from the
    coincidence matrix (Krippendorff, 2011). metric is "nominal", "ordinal"
    or "interval". None when expected disagreement is zero (one value only).
    """
    if not pairs:
        return None
    coincidence = {x: {y: 0.0 for y in LEVELS} for x in LEVELS}
    for x, y in pairs:                      # each unit holds two values: both orderings
        coincidence[x][y] += 1.0
        coincidence[y][x] += 1.0
    marginal = {x: sum(coincidence[x].values()) for x in LEVELS}
    n_values = sum(marginal.values())

    def delta2(x, y):
        if x == y:
            return 0.0
        if metric == "nominal":
            return 1.0
        if metric == "interval":
            return float((x - y) ** 2)
        if metric == "ordinal":
            lo, hi = min(x, y), max(x, y)
            between = sum(marginal[g] for g in LEVELS if lo <= g <= hi)
            return (between - (marginal[x] + marginal[y]) / 2.0) ** 2
        raise ValueError(metric)

    observed = sum(coincidence[x][y] * delta2(x, y) for x in LEVELS for y in LEVELS)
    expected = sum(marginal[x] * marginal[y] * delta2(x, y)
                   for x in LEVELS for y in LEVELS) / (n_values - 1)
    if expected == 0:
        return None
    return 1.0 - observed / expected


def agreement_block(scored):
    """The agreement figures for [(term_id, a, b)]; aggregates only."""
    pairs = [(a, b) for _, a, b in scored]
    n = len(pairs)
    if n == 0:
        return {"n_both_scored": 0}
    diffs = Counter(abs(a - b) for a, b in pairs)
    exact = diffs.get(0, 0)
    within_one = exact + diffs.get(1, 0)
    return {
        "n_both_scored": n,
        "exact": {"count": exact, "proportion": exact / n},
        "within_one": {"count": within_one, "proportion": within_one / n},
        "difference_counts": {str(d): diffs.get(d, 0) for d in range(len(LEVELS))},
        "first_reviewer_higher": sum(1 for a, b in pairs if a > b),
        "second_reviewer_higher": sum(1 for a, b in pairs if a < b),
        "both_4": sum(1 for a, b in pairs if a == 4 and b == 4),
        "both_at_least_3": sum(1 for a, b in pairs if a >= 3 and b >= 3),
        "both_at_most_2": sum(1 for a, b in pairs if a <= 2 and b <= 2),
        "split_across_2_and_3": sum(1 for a, b in pairs if (a <= 2) != (b <= 2)),
        "cohen_kappa": {w: cohen_kappa(pairs, w) for w in ("nominal", "linear", "quadratic")},
        "krippendorff_alpha": {m: krippendorff_alpha(pairs, m)
                               for m in ("nominal", "ordinal", "interval")},
        "table_rows_first_cols_second": {str(x): {str(y): v for y, v in row.items()}
                                         for x, row in confusion(pairs).items()},
    }


def bootstrap_block(scored, resamples, seed):
    """Percentile intervals over terms, resampled with replacement, fixed seed."""
    pairs = [(a, b) for _, a, b in scored]
    n = len(pairs)
    if n < 2 or resamples <= 0:
        return None
    rng = random.Random(seed)
    stats = {"exact": [], "within_one": [], "alpha_ordinal": [], "kappa_quadratic": []}
    for _ in range(resamples):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        stats["exact"].append(sum(1 for a, b in sample if a == b) / n)
        stats["within_one"].append(sum(1 for a, b in sample if abs(a - b) <= 1) / n)
        stats["alpha_ordinal"].append(krippendorff_alpha(sample, "ordinal"))
        stats["kappa_quadratic"].append(cohen_kappa(sample, "quadratic"))

    def interval(values):
        values = sorted(v for v in values if v is not None)
        if len(values) < 20:
            return None
        lo = values[int(math.floor(0.025 * (len(values) - 1)))]
        hi = values[int(math.ceil(0.975 * (len(values) - 1)))]
        return {"low": lo, "high": hi, "resamples_defined": len(values)}

    return {"resamples": resamples, "seed": seed, "level": "95% percentile",
            "intervals": {k: interval(v) for k, v in stats.items()}}


# --------------------------------------------------------------------------
# Per reviewer: distributions, comments, re-scores, sittings
# --------------------------------------------------------------------------

def _has_text(cell):
    return bool((cell or "").strip())


def reviewer_block(rows, times):
    """One reviewer's latest rows on the term set: distribution, comments, re-scores."""
    n = len(rows)
    if n == 0:
        return {"n_scored": 0}
    scores = [int(r["score"]) for r in rows]
    dist = Counter(scores)
    by_level = {}
    for level in LEVELS:
        at = [r for r in rows if int(r["score"]) == level]
        by_level[str(level)] = {
            "count": len(at),
            "with_note": sum(1 for r in at if _has_text(r.get("note"))),
            "with_alternative": sum(1 for r in at if _has_text(r.get("proposed_rw"))),
        }
    rescored = sum(1 for t in times.values() if t > 1)
    return {
        "n_scored": n,
        "distribution": {str(level): dist.get(level, 0) for level in LEVELS},
        "mean_score": statistics.fmean(scores),
        "share_4": dist.get(4, 0) / n,
        "share_at_most_2": sum(1 for s in scores if s <= 2) / n,
        "with_note": sum(1 for r in rows if _has_text(r.get("note"))),
        "with_alternative": sum(1 for r in rows if _has_text(r.get("proposed_rw"))),
        "by_level": by_level,
        "terms_scored_more_than_once": rescored,
        "saves_in_total": sum(times.values()),
    }


def _median_gap_seconds(whens):
    gaps = [(b - a).total_seconds() for a, b in zip(whens, whens[1:])]
    return statistics.median(gaps) if gaps else None


def _half(rows):
    if not rows:
        return None
    scores = [int(r["score"]) for r in rows]
    whens = [_when(r["reviewed_at"]) for r in rows]
    return {
        "terms": len(rows),
        "mean_score": statistics.fmean(scores),
        "share_4": sum(1 for s in scores if s == 4) / len(scores),
        "comment_rate": sum(1 for r in rows if _has_text(r.get("note"))
                            or _has_text(r.get("proposed_rw"))) / len(rows),
        "median_gap_seconds": _median_gap_seconds(whens),
    }


def sittings(rows, gap_minutes, zone=None):
    """
    A reviewer's sittings: the latest rows in time order, cut wherever two
    consecutive saves are more than gap_minutes apart. Each sitting carries its
    pace and the first half against the second half, which is the fatigue check.
    """
    timed = [r for r in rows if _when(r.get("reviewed_at")) is not None]
    timed.sort(key=lambda r: (_when(r["reviewed_at"]), int(r["id"])))
    groups, current = [], []
    for r in timed:
        if current and (_when(r["reviewed_at"]) - _when(current[-1]["reviewed_at"])
                        ).total_seconds() > gap_minutes * 60:
            groups.append(current)
            current = []
        current.append(r)
    if current:
        groups.append(current)

    def stamp(value):
        out = {"utc": value.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")}
        if zone is not None:
            out["local"] = value.replace(tzinfo=timezone.utc).astimezone(zone
                                                                         ).isoformat(timespec="seconds")
        return out

    result = []
    for group in groups:
        whens = [_when(r["reviewed_at"]) for r in group]
        minutes = (whens[-1] - whens[0]).total_seconds() / 60.0
        n = len(group)
        half = n // 2
        result.append({
            "start": stamp(whens[0]),
            "end": stamp(whens[-1]),
            "minutes": minutes,
            "terms": n,
            "terms_per_hour": (n / (minutes / 60.0)) if minutes > 0 else None,
            "median_gap_seconds": _median_gap_seconds(whens),
            "whole": _half(group),
            "first_half": _half(group[:half]) if n >= 4 else None,
            "second_half": _half(group[half:]) if n >= 4 else None,
        })
    by_day = Counter(_when(r["reviewed_at"]).date().isoformat() for r in timed)
    return {
        "gap_minutes": gap_minutes,
        "timezone_shown": getattr(zone, "key", None),
        "terms_with_timestamp": len(timed),
        "terms_by_day_utc": dict(sorted(by_day.items())),
        "sittings": result,
    }


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------

def _safe(value):
    """A cell for a sheet people open: text is never read as a formula (as in
    export_scores.py); a number, such as a negative difference, stays a number."""
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    cell = str(value)
    return "'" + cell if cell.startswith(FORMULA_START) else cell


def side_by_side_rows(term_map, latest, times, a, b):
    rows = []
    for term_id in sorted(term_map):
        term = term_map[term_id]
        ra, rb = latest[a].get(term_id), latest[b].get(term_id)
        sa = int(ra["score"]) if ra else None
        sb = int(rb["score"]) if rb else None
        shown_a = (ra or {}).get("shown_rw", "")
        shown_b = (rb or {}).get("shown_rw", "")
        rows.append({
            "term_id": term_id,
            "corpus_key": term.get("corpus_key", ""),
            "english": term.get("english", ""),
            "domain": term.get("domain", ""),
            "pilot": "yes" if _bool(term.get("pilot")) else "",
            f"shown_rw_{a}": shown_a,
            f"shown_rw_{b}": shown_b,
            "shown_same": ("yes" if (shown_a or "").strip() == (shown_b or "").strip()
                           else "no") if ra and rb else "",
            f"score_{a}": sa if sa is not None else "",
            f"score_{b}": sb if sb is not None else "",
            "difference": (sa - sb) if (sa is not None and sb is not None) else "",
            "gold": "yes" if sa == 4 and sb == 4 else "",
            f"proposed_rw_{a}": (ra or {}).get("proposed_rw", ""),
            f"proposed_rw_{b}": (rb or {}).get("proposed_rw", ""),
            f"note_{a}": (ra or {}).get("note", ""),
            f"note_{b}": (rb or {}).get("note", ""),
            f"reviewed_at_{a}": (ra or {}).get("reviewed_at", ""),
            f"reviewed_at_{b}": (rb or {}).get("reviewed_at", ""),
            f"times_scored_{a}": times[a].get(term_id, ""),
            f"times_scored_{b}": times[b].get(term_id, ""),
        })
    return rows


def _write_csv(path, fields, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(fields)
        for row in rows:
            writer.writerow([_safe(row.get(k)) for k in fields])
    return len(rows)


def _outside_repo(folder):
    folder = Path(folder).expanduser().resolve()
    if folder == REPO_ROOT or REPO_ROOT in folder.parents:
        sys.exit("Refusing to write inside the repository: scores and the side-by-side "
                 "sheet are research data and never go into the public repo. Use --out "
                 "with a folder outside it, or leave it out to write beside the backup.")
    return folder


def repo_state():
    """The commit this ran from, and whether the working tree was clean."""
    def git(*args):
        try:
            done = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True,
                                  text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None
    head = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return {"commit": head, "clean": (status == "") if status is not None else None}


def _parse_tz(items):
    zones = {}
    for item in items or []:
        if "=" not in item:
            sys.exit(f"--tz takes CODE=Area/City, not {item!r}.")
        code, name = item.split("=", 1)
        if ZoneInfo is None:
            sys.exit("--tz needs Python 3.9 or newer.")
        try:
            zones[code.strip()] = ZoneInfo(name.strip())
        except Exception:
            sys.exit(f"Unknown time zone {name!r}; use an IANA name such as Africa/Kigali.")
    return zones


# --------------------------------------------------------------------------
# The analysis
# --------------------------------------------------------------------------

def analyse(folder, corpus="v1", term_set="pilot", reviewers=None, gap_minutes=60,
            resamples=2000, seed=20261010, zones=None, now=None):
    """
    Everything the JSON holds, plus the side-by-side rows and the gold rows.
    Returns (report, side_rows, gold_rows, a, b).
    """
    folder, manifest, checks, tables = read_backup(folder)
    accounts = [(r.get("code") or "").strip() for r in tables["reviewers.csv"]]
    names = {(r.get("code") or "").strip(): r.get("display_name", "")
             for r in tables["reviewers.csv"]}
    codes = [c.strip() for c in reviewers] if reviewers else [c for c in accounts if c]
    if len(codes) != 2:
        sys.exit("Agreement is between two reviewers; name them with --reviewers CODE,CODE "
                 f"(the backup has accounts for: {', '.join(c for c in accounts if c) or 'none'}).")
    a, b = codes

    term_map = select_terms(tables["terms.csv"], corpus, term_set)
    if not term_map:
        sys.exit(f"No terms in corpus {corpus!r} for --terms {term_set}.")
    latest, times = latest_blind(tables["term_reviews.csv"], set(term_map), codes)
    scored = score_pairs(latest, a, b)
    other_codes = sorted({(r.get("reviewer") or "").strip() for r in tables["term_reviews.csv"]
                          if not _bool(r.get("is_adjudication"))} - set(codes))

    by_domain = {}
    for domain in sorted({(t.get("domain") or "") for t in term_map.values()}):
        ids = {i for i, t in term_map.items() if (t.get("domain") or "") == domain}
        block = agreement_block([s for s in scored if s[0] in ids])
        block["n_terms"] = len(ids)
        by_domain[domain or "(no domain)"] = block
    by_pilot = None
    if term_set == "all":
        pilot_ids = {i for i, t in term_map.items() if _bool(t.get("pilot"))}
        by_pilot = {}
        for label, ids in (("pilot", pilot_ids), ("non-pilot", set(term_map) - pilot_ids)):
            block = agreement_block([s for s in scored if s[0] in ids])
            block["n_terms"] = len(ids)
            by_pilot[label] = block

    zones = zones or {}
    per_reviewer = {}
    for code in codes:
        rows = list(latest[code].values())
        per_reviewer[code] = {
            "display_name": names.get(code, ""),
            **reviewer_block(rows, times[code]),
            "sittings": sittings(rows, gap_minutes, zones.get(code)),
        }

    now = now or datetime.now(timezone.utc)
    report = {
        "script": {"name": "scripts/agreement.py", "version": SCRIPT_VERSION,
                   "python": platform.python_version(), "repository": repo_state(),
                   "run_at_utc": now.astimezone(timezone.utc).isoformat(timespec="seconds")},
        "inputs": {"backup": folder.name, "backup_path": str(folder),
                   "exported_at_utc": manifest.get("exported_at_utc"),
                   "sha256": checks, "verified_against_manifest": True},
        "parameters": {"corpus": corpus, "terms": term_set, "reviewers": codes,
                       "gap_minutes": gap_minutes, "bootstrap_resamples": resamples,
                       "seed": seed},
        "rules": {"score": "latest blind row per reviewer and term (reviewed_at, then id); "
                           "adjudication rows excluded",
                  "agreement_base": "terms both reviewers scored",
                  "gold": "both latest blind scores are 4"},
        "terms": {"n_in_set": len(term_map),
                  "scored_by": {code: len(latest[code]) for code in codes},
                  "scored_by_both": len(scored),
                  "scored_by_neither": sum(1 for i in term_map
                                           if i not in latest[a] and i not in latest[b]),
                  "blind_rows_from_other_codes_ignored": other_codes},
        "agreement": agreement_block(scored),
        "bootstrap": bootstrap_block(scored, resamples, seed),
        "by_domain": by_domain,
        "by_pilot": by_pilot,
        "reviewers": per_reviewer,
    }
    side_rows = side_by_side_rows(term_map, latest, times, a, b)
    gold_rows = [r for r in side_rows if r["gold"] == "yes"] if term_set == "all" else []
    return report, side_rows, gold_rows, a, b


def _rounded(value, digits=6):
    """The report with its floats rounded for reading; counts are untouched."""
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, dict):
        return {k: _rounded(v, digits) for k, v in value.items()}
    if isinstance(value, list):
        return [_rounded(v, digits) for v in value]
    return value


def write_outputs(report, side_rows, gold_rows, a, b, out_dir, term_set, now=None):
    out_dir = _outside_repo(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # The file is dated like the backup folder: the local day it was run.
    now = now or datetime.now().astimezone()
    written = {}
    json_path = out_dir / f"agreement_{term_set}_{now.strftime('%Y-%m-%d')}.json"
    json_path.write_text(json.dumps(_rounded(report), ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    written[json_path.name] = 1
    fields = [f.format(a=a, b=b) for f in SIDE_BY_SIDE_FIELDS]
    side_path = out_dir / f"side_by_side_{term_set}.csv"
    written[side_path.name] = _write_csv(side_path, fields, side_rows)
    if term_set == "all":
        gold_path = out_dir / "gold_terms.csv"
        written[gold_path.name] = _write_csv(
            gold_path, ["term_id", "corpus_key", "english", "domain", "pilot"], gold_rows)
    return out_dir, written


def _fmt(value, digits=2):
    return "undefined" if value is None else f"{value:.{digits}f}"


def summary_lines(report):
    """The terminal summary: aggregates only."""
    t, ag = report["terms"], report["agreement"]
    a, b = report["parameters"]["reviewers"]
    lines = [
        f"Backup {report['inputs']['backup']} (exported {report['inputs']['exported_at_utc']}), "
        f"corpus {report['parameters']['corpus']}, terms: {report['parameters']['terms']}",
        f"Terms in set: {t['n_in_set']}; scored by {a}: {t['scored_by'][a]}, "
        f"by {b}: {t['scored_by'][b]}, by both: {t['scored_by_both']}",
    ]
    if t["blind_rows_from_other_codes_ignored"]:
        lines.append("Blind rows from other reviewer codes ignored: "
                     + ", ".join(t["blind_rows_from_other_codes_ignored"]))
    if ag.get("n_both_scored", 0) == 0:
        lines.append("No term scored by both reviewers yet: no agreement to report.")
        return lines
    n = ag["n_both_scored"]
    lines += [
        f"Exact agreement: {ag['exact']['count']}/{n} ({ag['exact']['proportion']:.1%}); "
        f"within one: {ag['within_one']['count']}/{n} ({ag['within_one']['proportion']:.1%})",
        f"Cohen's kappa: nominal {_fmt(ag['cohen_kappa']['nominal'])}, "
        f"linear {_fmt(ag['cohen_kappa']['linear'])}, quadratic {_fmt(ag['cohen_kappa']['quadratic'])}",
        f"Krippendorff's alpha: nominal {_fmt(ag['krippendorff_alpha']['nominal'])}, "
        f"ordinal {_fmt(ag['krippendorff_alpha']['ordinal'])}, "
        f"interval {_fmt(ag['krippendorff_alpha']['interval'])}",
        f"Both 4 (gold): {ag['both_4']}; both at least 3: {ag['both_at_least_3']}; "
        f"both at most 2: {ag['both_at_most_2']}; split across 2/3: {ag['split_across_2_and_3']}",
    ]
    boot = report.get("bootstrap")
    if boot and boot["intervals"].get("alpha_ordinal"):
        iv = boot["intervals"]
        lines.append(f"95% bootstrap intervals ({boot['resamples']} resamples, seed {boot['seed']}): "
                     f"exact {_fmt(iv['exact']['low'])} to {_fmt(iv['exact']['high'])}, "
                     f"alpha ordinal {_fmt(iv['alpha_ordinal']['low'])} to "
                     f"{_fmt(iv['alpha_ordinal']['high'])}")
    for code in (a, b):
        r = report["reviewers"][code]
        if r.get("n_scored", 0) == 0:
            lines.append(f"{code}: nothing scored in this set")
            continue
        d = r["distribution"]
        lines.append(f"{code}: scores 1/2/3/4 = {d['1']}/{d['2']}/{d['3']}/{d['4']}, "
                     f"mean {r['mean_score']:.2f}, notes on {r['with_note']}, "
                     f"alternatives on {r['with_alternative']}, "
                     f"re-scored {r['terms_scored_more_than_once']}; "
                     f"{len(r['sittings']['sittings'])} sitting(s)")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reviewer agreement for the annotation round, from a backup folder.")
    parser.add_argument("--backup", help="a dated folder written by scripts/export_scores.py "
                                         "(default: the newest under ~/LinguaMedica-backups)")
    parser.add_argument("--corpus", default="v1", help="corpus version (default v1)")
    parser.add_argument("--terms", choices=TERM_SETS, default="pilot",
                        help="which terms: pilot (default), all, or non-pilot")
    parser.add_argument("--round-closed", action="store_true",
                        help="required for --terms all or non-pilot: the round has closed")
    parser.add_argument("--reviewers", help="two reviewer codes, e.g. OU,YV (default: the "
                                            "two accounts in the backup)")
    parser.add_argument("--gap-minutes", type=float, default=60,
                        help="a pause longer than this starts a new sitting (default 60)")
    parser.add_argument("--bootstrap", type=int, default=2000,
                        help="bootstrap resamples for the intervals (default 2000; 0 = none)")
    parser.add_argument("--seed", type=int, default=20261010, help="bootstrap seed")
    parser.add_argument("--tz", action="append", metavar="CODE=Area/City",
                        help="show a reviewer's sittings in a local zone too (repeatable)")
    parser.add_argument("--out", help="folder for the outputs (default: the backup folder); "
                                      "never inside the repository")
    args = parser.parse_args(argv)

    if args.terms != "pilot" and not args.round_closed:
        sys.exit(f"--terms {args.terms} reads the round's scores. Scores are read after the "
                 "round closes: add --round-closed when it has. Until then, --terms pilot "
                 "analyses the pilot alone.")

    folder = Path(args.backup).expanduser() if args.backup else newest_backup()
    reviewers = args.reviewers.split(",") if args.reviewers else None
    report, side_rows, gold_rows, a, b = analyse(
        folder, corpus=args.corpus, term_set=args.terms, reviewers=reviewers,
        gap_minutes=args.gap_minutes, resamples=args.bootstrap, seed=args.seed,
        zones=_parse_tz(args.tz))
    out_dir, written = write_outputs(report, side_rows, gold_rows, a, b,
                                     args.out or folder, args.terms)
    for line in summary_lines(report):
        print(line)
    print(f"Written to {out_dir}:")
    for name, rows in written.items():
        print(f"  {name:<34} {rows:>5} row(s)" if not name.endswith(".json") else f"  {name}")


if __name__ == "__main__":
    main()
