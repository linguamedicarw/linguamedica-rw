"""
Two runs of the pipeline over the same items, side by side: how far the results of one
setting carry over to another. Built for Dr. Dastour's request of 8 November 2026: 8-bit
for development, 16-bit for every reported result, and a comparison of the two on 50 to
100 development sentences, reported as the difference in the chosen metric.

    python scripts/compare_runs.py RUN_A RUN_B [--references REFS.tsv]
        [--resamples 2000] [--seed 20261111] [--out FOLDER]

RUN_A is the setting being checked (the 8-bit development run), RUN_B the reference
setting (the 16-bit run). Both must be finished, and must share the items file, the
resource, K, the arm, the prompt template, the matching rules and the decoding settings,
so that what differs is the model side only (checkpoint, precision, runtime). That side
is printed and recorded, because on Ollama against transformers the comparison measures
the whole development setup against the reported one: the quantization and the runtime
together.

The chosen metric is adherence (thesis 4.3.5): of the retrieved terms shown to the model,
how many the output uses. Strict reading, plus the tolerant reading once
rag/matching_rules.json has lists, plus each with variants accepted. Reported for each
run, as the difference B - A with a 95% paired bootstrap interval over items, and as the
terms where the two runs disagree. Beside it, never combined with it: the share of items
whose outputs are identical, and, with --references, chrF++ (sacrebleu) for each run with
a paired bootstrap interval on the difference.

Writes compare_<A>__<B>.json, aggregates only (no output text), next to RUN_B unless --out
says otherwise, and never inside the repository.
"""

import argparse
import csv
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag.pipeline import outside_repo, repo_state  # noqa: E402

DEFAULT_SEED = 20261111
READINGS = (("strict", "lead_strict", None), ("strict_with_variants", "lead_strict", "variant_strict"),
            ("tolerant", "lead_tolerant", None),
            ("tolerant_with_variants", "lead_tolerant", "variant_tolerant"))
NOT_GENERATED = ("skipped", "not_generated")


class Mismatch(SystemExit):
    """The two runs differ in something other than the model."""


def load(run_dir):
    run_dir = Path(run_dir).expanduser().resolve()
    manifest_path = run_dir / "run.json"
    if not manifest_path.exists():
        raise SystemExit(f"{run_dir} holds no run.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "finished":
        raise SystemExit(f"{run_dir.name} is not finished (status {manifest.get('status')}); "
                         "resume it first")
    # split on "\n" only: str.splitlines() also breaks at U+2028 and U+0085, which
    # json.dumps(ensure_ascii=False) leaves unescaped inside a model's output
    records = [json.loads(line) for line in
               (run_dir / "items.jsonl").read_text(encoding="utf-8").split("\n") if line]
    return run_dir, manifest, records


def shared(manifest):
    """What must be the same in both runs."""
    b = manifest.get("backbone") or {}
    rules = manifest.get("matching_rules") or {}
    return {
        "items": (manifest.get("items") or {}).get("sha256"),
        "item count": (manifest.get("items") or {}).get("count"),
        "resource": (manifest.get("resource") or {}).get("sha256"),
        "settings": manifest.get("settings"),
        "prompt": manifest.get("prompt"),
        "matching rules": {k: rules.get(k) for k in ("version", "sha256")},
        "decoding": b.get("decoding"),
        "pipeline code": (manifest.get("code") or {}).get("sha256"),
    }


def model_side(manifest):
    b = manifest.get("backbone") or {}
    keep = ("backbone", "model", "checkpoint", "precision", "dtype", "prompt_format",
            "transformers", "torch", "ollama_version", "device")
    code = manifest.get("code") or {}
    repo = code.get("repository") or {}
    return dict({k: b[k] for k in keep if k in b}, run=manifest.get("run"),
                reproducible=manifest.get("reproducible"),
                pipeline=code.get("rag"), code_sha256=code.get("sha256"),
                commit=repo.get("commit"), clean=repo.get("clean"),
                python=code.get("python"), platform=code.get("platform"))


def check_comparable(ma, mb):
    a, b = shared(ma), shared(mb)
    differ = [k for k in a if a[k] != b[k]]
    if differ:
        raise Mismatch("Not comparable: the runs differ in " + ", ".join(differ)
                       + ". Only the model side may differ.")


def _term_key(t):
    return (t.get("term"), tuple(t.get("entry_ids") or ()), bool(t.get("wrong_sense")))


def pair(records_a, records_b):
    """
    [(item id, [(a_term, b_term)], output_a, output_b)] for the items generated in both,
    and the counts of what was left out. The terms must be the same retrievals in both.
    """
    ids_a, ids_b = [r["id"] for r in records_a], [r["id"] for r in records_b]
    if ids_a != ids_b:
        raise Mismatch("Not comparable: the runs do not hold the same items in the same order")
    pairs, left_out = [], {"not_generated_in_a": 0, "not_generated_in_b": 0}
    for ra, rb in zip(records_a, records_b):
        if ra.get("status") in NOT_GENERATED or rb.get("status") in NOT_GENERATED:
            left_out["not_generated_in_a"] += ra.get("status") in NOT_GENERATED
            left_out["not_generated_in_b"] += rb.get("status") in NOT_GENERATED
            continue
        ta = [t for t in ra.get("terms") or [] if not t.get("wrong_sense")]
        tb = [t for t in rb.get("terms") or [] if not t.get("wrong_sense")]
        if [_term_key(t) for t in ta] != [_term_key(t) for t in tb]:
            raise Mismatch(f"Not comparable: item {ra['id']} has different retrievals in the "
                           "two runs, though the resource and settings are the same")
        pairs.append((ra["id"], list(zip(ta, tb)), ra.get("output") or "", rb.get("output") or ""))
    return pairs, left_out


def _used(t, lead, variant):
    if t.get(lead) is None:
        return None
    return bool(t.get(lead) or (variant and t.get(variant)))


def _percentile(sorted_values, q):
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def bootstrap(per_item, statistic, resamples, seed):
    """95% percentile interval of statistic(resampled items), items drawn with replacement."""
    rng = random.Random(seed)
    n = len(per_item)
    if n == 0:
        return None
    values = []
    for _ in range(resamples):
        sample = [per_item[rng.randrange(n)] for _ in range(n)]
        v = statistic(sample)
        if v is not None:
            values.append(v)
    values.sort()
    return [_percentile(values, 0.025), _percentile(values, 0.975)]


def adherence(pairs, resamples, seed):
    out = {}
    for name, lead, variant in READINGS:
        per_item, disagreements = [], []
        complete = True
        for item, terms, _, _ in pairs:
            row = []
            for ta, tb in terms:
                ua, ub = _used(ta, lead, variant), _used(tb, lead, variant)
                if ua is None or ub is None:
                    complete = False
                    break
                row.append((ua, ub))
                if ua != ub:
                    disagreements.append({"item": item, "term": ta.get("term"),
                                          "a": ua, "b": ub})
            if not complete:
                break
            per_item.append(row)
        if not complete:
            out[name] = None            # the tolerant reading needs the editor's lists
            continue

        def totals(sample):
            n = sum(len(r) for r in sample)
            a = sum(ua for r in sample for ua, _ in r)
            b = sum(ub for r in sample for _, ub in r)
            return n, a, b

        n, a, b = totals(per_item)

        def diff(sample):
            m, x, y = totals(sample)
            return (y - x) / m if m else None

        out[name] = {
            "terms": n,
            "a": {"used": a, "rate": a / n if n else None},
            "b": {"used": b, "rate": b / n if n else None},
            "difference_b_minus_a": (b - a) / n if n else None,
            "ci95": bootstrap(per_item, diff, resamples, seed) if n else None,
            "used_in_a_only": sum(1 for d in disagreements if d["a"]),
            "used_in_b_only": sum(1 for d in disagreements if d["b"]),
            "disagreements": disagreements,
        }
    return out


def read_references(path):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows or [h.strip().casefold() for h in rows[0][:2]] != ["item", "reference"]:
        raise SystemExit(f"{Path(path).name}: expected a header 'item<TAB>reference'")
    refs = {}
    for row in rows[1:]:
        if len(row) >= 2:
            refs[row[0]] = row[1]
    return refs


def chrf(pairs, refs, resamples, seed):
    """chrF++ of each run against the references, with a paired bootstrap on B - A."""
    try:
        import sacrebleu
        from sacrebleu.metrics import CHRF
    except ImportError:
        return {"skipped": "sacrebleu is not installed (pip install sacrebleu)"}
    rows = [(oa, ob, refs[item]) for item, _, oa, ob in pairs if item in refs]
    if not rows:
        return {"skipped": "no compared item has a reference"}
    metric = CHRF(word_order=2)
    hyp_a, hyp_b, ref = ([r[i] for r in rows] for i in range(3))
    score_a = metric.corpus_score(hyp_a, [ref])
    score_b = metric.corpus_score(hyp_b, [ref])
    try:                                   # sentence statistics, summed per resample
        stats_a = metric._extract_corpus_statistics(hyp_a, [ref])
        stats_b = metric._extract_corpus_statistics(hyp_b, [ref])

        def corpus(stats, idx):
            summed = [sum(stats[i][j] for i in idx) for j in range(len(stats[0]))]
            return metric._compute_score_from_stats(summed).score
    except AttributeError:                 # a sacrebleu without them: slower, same result
        def corpus(stats, idx):
            hyps = [stats[i] for i in idx]
            return metric.corpus_score(hyps, [[ref[i] for i in idx]]).score
        stats_a, stats_b = hyp_a, hyp_b
    idx_all = list(range(len(rows)))
    interval = bootstrap(idx_all, lambda s: corpus(stats_b, s) - corpus(stats_a, s),
                         resamples, seed)
    return {"items": len(rows), "signature": str(metric.get_signature()),
            "sacrebleu": sacrebleu.__version__,
            "a": round(score_a.score, 2), "b": round(score_b.score, 2),
            "difference_b_minus_a": round(score_b.score - score_a.score, 2),
            "ci95": [round(x, 2) for x in interval] if interval else None}


def compare(run_a, run_b, references=None, resamples=2000, seed=DEFAULT_SEED):
    dir_a, ma, ra = load(run_a)
    dir_b, mb, rb = load(run_b)
    check_comparable(ma, mb)
    pairs, left_out = pair(ra, rb)
    identical = sum(1 for _, _, oa, ob in pairs if oa.strip() == ob.strip())
    result = {
        "written": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "a": model_side(ma), "b": model_side(mb),
        "shared": {"items": ma["items"], "resource": ma["resource"].get("label"),
                   "resource_sha256": ma["resource"].get("sha256"),
                   "settings": ma.get("settings"), "prompt": ma.get("prompt"),
                   "matching_rules": shared(ma)["matching rules"],
                   "decoding": shared(ma)["decoding"]},
        "items": {"in_runs": len(ra), "compared": len(pairs), **left_out,
                  "needs_review_in_a": sum(1 for r in ra if r.get("status") == "needs_review"),
                  "needs_review_in_b": sum(1 for r in rb if r.get("status") == "needs_review")},
        "adherence": adherence(pairs, resamples, seed),
        "identical_outputs": {"items": identical, "of": len(pairs),
                              "share": identical / len(pairs) if pairs else None},
        "chrf_plus_plus": chrf(pairs, read_references(references), resamples, seed)
        if references else None,
        "bootstrap": {"resamples": resamples, "seed": seed, "unit": "item",
                      "interval": "95% percentile"},
        "script": {"path": "scripts/compare_runs.py",
                   "sha256": hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest(),
                   "repository": repo_state()},
    }
    if references:
        result["references"] = {"path": str(Path(references).resolve()),
                                "sha256": hashlib.sha256(Path(references).read_bytes()).hexdigest()}
    return dir_a, dir_b, result


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def report(result):
    a, b = result["a"], result["b"]
    lines = [f"A: {a.get('run')}  {a.get('checkpoint')}  precision {a.get('precision')}",
             f"B: {b.get('run')}  {b.get('checkpoint')}  precision {b.get('precision')}",
             f"Items compared: {result['items']['compared']} of {result['items']['in_runs']}"]
    for name in ("strict", "tolerant"):
        x = result["adherence"].get(name)
        if not x:
            lines.append(f"Adherence, {name}: not reported"
                         + (" (rag/matching_rules.json has no lists yet)" if name == "tolerant" else ""))
            continue
        if not x["terms"]:
            lines.append(f"Adherence, {name}: no retrieved term in the compared items")
            continue
        ci = x["ci95"]
        lines.append(f"Adherence, {name}: A {x['a']['used']}/{x['terms']} ({_pct(x['a']['rate'])}), "
                     f"B {x['b']['used']}/{x['terms']} ({_pct(x['b']['rate'])}); B - A "
                     f"{100 * x['difference_b_minus_a']:+.1f} points"
                     + (f", 95% CI [{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]" if ci else "")
                     + f"; terms used in A only {x['used_in_a_only']}, in B only {x['used_in_b_only']}")
    for side in ("a", "b"):
        if result[side].get("reproducible") is False:
            lines.append(f"WARNING: run {side.upper()} is marked not reproducible; do not report it")
    io = result["identical_outputs"]
    lines.append(f"Identical outputs: {io['items']} of {io['of']} ({_pct(io['share'])})")
    c = result.get("chrf_plus_plus")
    if c and "skipped" not in c:
        lines.append(f"chrF++: A {c['a']}, B {c['b']}; B - A {c['difference_b_minus_a']:+.2f}, "
                     f"95% CI {c['ci95']}  ({c['signature']})")
    elif c:
        lines.append(f"chrF++: {c['skipped']}")
    return lines


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.add_argument("--references")
    p.add_argument("--resamples", type=int, default=2000)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--out")
    a = p.parse_args(argv)
    dir_a, dir_b, result = compare(a.run_a, a.run_b, a.references, a.resamples, a.seed)
    out = outside_repo(a.out or dir_b.parent)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"compare_{dir_a.name}__{dir_b.name}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for line in report(result):
        print(line)
    print(f"Written: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
