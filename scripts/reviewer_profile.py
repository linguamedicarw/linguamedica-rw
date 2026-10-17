#!/usr/bin/env python3
"""
reviewer_profile.py - how each reviewer scored, by domain and over a sitting.

WHAT THIS DOES
    Reads one backup folder written by scripts/export_scores.py (the same input
    as scripts/agreement.py, checked against the manifest the same way) and
    describes each reviewer's latest blind scores, aggregates only:

        by domain        the 1/2/3/4 distribution per reviewer in each domain
        by sitting half  every sitting of 4 or more terms cut in two halves by
                         time: terms, share of 1s, share of 4s, comment rate,
                         median seconds between saves, and the 1s per domain
                         in each half (the drift / fatigue check)

    Writes reviewer_profile_<set>_<date>.json beside the backup and prints a
    short summary. No term, rendering or comment appears in either.

WHY IT EXISTS
    To test, from the data and not by reading, whether disagreement between the
    reviewers follows the domain (a reviewer's field of expertise) or the
    sitting (pace and fatigue). Methods chapter, quality control.

RULES
    The same as scripts/agreement.py: latest blind row per reviewer and term,
    adjudication rows out; a sitting ends where two saves are more than
    --gap-minutes apart (default 60). --terms all / non-pilot need
    --round-closed.

HOW TO RUN (repo root, venv active)
    python scripts/reviewer_profile.py --terms all --round-closed
"""
import argparse
import importlib.util
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "agreement", Path(__file__).resolve().parent / "agreement.py")
agreement = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agreement)

LEVELS = agreement.LEVELS


def _dist(rows):
    c = Counter(int(r["score"]) for r in rows)
    return {str(k): c.get(k, 0) for k in LEVELS}


def _half_block(rows, term_map):
    n = len(rows)
    if n == 0:
        return None
    whens = [agreement._when(r["reviewed_at"]) for r in rows]
    ones = [r for r in rows if int(r["score"]) == 1]
    domains = Counter((term_map[int(r["term_id"])].get("domain") or "(no domain)") for r in rows)
    ones_dom = Counter((term_map[int(r["term_id"])].get("domain") or "(no domain)") for r in ones)
    return {
        "terms": n,
        "distribution": _dist(rows),
        "share_1": len(ones) / n,
        "share_4": sum(1 for r in rows if int(r["score"]) == 4) / n,
        "comment_rate": sum(1 for r in rows if agreement._has_text(r.get("note"))
                            or agreement._has_text(r.get("proposed_rw"))) / n,
        "median_gap_seconds": agreement._median_gap_seconds(whens),
        "terms_by_domain": dict(sorted(domains.items())),
        "ones_by_domain": dict(sorted(ones_dom.items())),
    }


def profile(folder, corpus="v1", term_set="all", reviewers=None, gap_minutes=60, now=None):
    folder, manifest, checks, tables = agreement.read_backup(folder)
    accounts = [(r.get("code") or "").strip() for r in tables["reviewers.csv"]]
    codes = [c.strip() for c in reviewers] if reviewers else [c for c in accounts if c]
    term_map = agreement.select_terms(tables["terms.csv"], corpus, term_set)
    if not term_map:
        sys.exit(f"No terms in corpus {corpus!r} for --terms {term_set}.")
    latest, _ = agreement.latest_blind(tables["term_reviews.csv"], set(term_map), codes)
    domains = sorted({(t.get("domain") or "(no domain)") for t in term_map.values()})

    out = {}
    for code in codes:
        rows = list(latest[code].values())
        by_domain = {}
        for d in domains:
            rd = [r for r in rows if (term_map[int(r["term_id"])].get("domain") or "(no domain)") == d]
            by_domain[d] = {"terms": len(rd), "distribution": _dist(rd)}
        timed = sorted((r for r in rows if agreement._when(r.get("reviewed_at"))),
                       key=lambda r: (agreement._when(r["reviewed_at"]), int(r["id"])))
        groups, cur = [], []
        for r in timed:
            if cur and (agreement._when(r["reviewed_at"]) - agreement._when(cur[-1]["reviewed_at"])
                        ).total_seconds() > gap_minutes * 60:
                groups.append(cur)
                cur = []
            cur.append(r)
        if cur:
            groups.append(cur)
        sittings = []
        for g in groups:
            if len(g) < 4:
                continue
            h = len(g) // 2
            sittings.append({
                "start_utc": agreement._when(g[0]["reviewed_at"]).isoformat(timespec="minutes"),
                "terms": len(g),
                "first_half": _half_block(g[:h], term_map),
                "second_half": _half_block(g[h:], term_map),
            })
        out[code] = {"terms": len(rows), "distribution": _dist(rows),
                     "by_domain": by_domain, "sittings_of_4_or_more": sittings}

    now = now or datetime.now().astimezone()
    return {
        "script": {"name": "scripts/reviewer_profile.py", "repository": agreement.repo_state(),
                   "run_at": now.isoformat(timespec="seconds")},
        "inputs": {"backup": folder.name, "sha256": checks, "verified_against_manifest": True},
        "parameters": {"corpus": corpus, "terms": term_set, "reviewers": codes,
                       "gap_minutes": gap_minutes},
        "reviewers": out,
    }, folder


def main(argv=None):
    p = argparse.ArgumentParser(description="Per-reviewer profile by domain and sitting half.")
    p.add_argument("--backup")
    p.add_argument("--corpus", default="v1")
    p.add_argument("--terms", choices=agreement.TERM_SETS, default="pilot")
    p.add_argument("--round-closed", action="store_true")
    p.add_argument("--reviewers")
    p.add_argument("--gap-minutes", type=float, default=60)
    p.add_argument("--out")
    a = p.parse_args(argv)
    if a.terms != "pilot" and not a.round_closed:
        sys.exit(f"--terms {a.terms} reads the round's scores; add --round-closed once it has closed.")
    folder = Path(a.backup).expanduser() if a.backup else agreement.newest_backup()
    report, folder = profile(folder, a.corpus, a.terms,
                             a.reviewers.split(",") if a.reviewers else None, a.gap_minutes)
    out_dir = agreement._outside_repo(a.out or folder)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d")
    path = out_dir / f"reviewer_profile_{a.terms}_{stamp}.json"
    path.write_text(json.dumps(agreement._rounded(report), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    for code, r in report["reviewers"].items():
        print(f"{code}: {r['terms']} terms, 1/2/3/4 = " +
              "/".join(str(r["distribution"][str(k)]) for k in LEVELS))
        for d, b in r["by_domain"].items():
            print(f"  {d:<20} {b['terms']:>3} terms, 1/2/3/4 = " +
                  "/".join(str(b["distribution"][str(k)]) for k in LEVELS))
        for s in r["sittings_of_4_or_more"]:
            f, h = s["first_half"], s["second_half"]
            print(f"  sitting {s['start_utc']} ({s['terms']} terms): 1s {f['share_1']:.0%} -> "
                  f"{h['share_1']:.0%}, comments {f['comment_rate']:.0%} -> {h['comment_rate']:.0%}, "
                  f"median gap {f['median_gap_seconds']:.0f}s -> {h['median_gap_seconds']:.0f}s")
    print(f"Written to {path}")


if __name__ == "__main__":
    main()
