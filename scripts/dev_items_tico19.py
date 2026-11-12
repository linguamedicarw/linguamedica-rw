"""
Development items from TICO-19: English sentences of the English-Kinyarwanda dev split
that hold at least one term of the dictionary export, drawn with a fixed seed.

For development only (the 8-bit against 16-bit comparison, K, the backbone), never for a
reported test. Only the dev split is accepted, so TICO-19's test split stays free for the
NLLB calibration and any later evaluation.

    python scripts/dev_items_tico19.py --tico PATH/dev.en-rw.tsv
        [--n 100] [--seed 20261111] [--resource data/terms.json] [--out ~/LinguaMedica-dev]

TICO-19's files are tab-separated and unquoted: a quotation mark is part of the text.
Read with csv quoting, the 2,100 rows of the English-Kinyarwanda test file collapse into
2,085, so the reader here turns quoting off and checks every row has the 8 fields.

Writes three files to --out, outside the repository:

    tico19-dev_<n>_seed<seed>_<resource sha12>.csv     the items: item, sentence. No terms
                                                      column, so the items are not
                                                      annotated: the pipeline scores
                                                      adherence on what retrieval finds and
                                                      marks outputs `unchecked`
    ..._references.tsv                                item and the Kinyarwanda reference,
                                                      for chrF++ in compare_runs.py only.
                                                      The pipeline never reads it
    ..._manifest.json                                 how the file was made: the source
                                                      file's SHA-256, the resource version,
                                                      the seed, eligible and chosen counts,
                                                      the terms found, the licences of the
                                                      chosen rows, this script's SHA-256

The same inputs give the same items, so the items file can be regenerated from the
manifest. The draw is uniform over the eligible sentences: no term is favoured.
"""

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag.matching import nfc  # noqa: E402
from rag.pipeline import DEFAULT_RESOURCE, outside_repo, repo_state, sha256_file  # noqa: E402
from rag.resource import Resource  # noqa: E402

COLUMNS = ["sourceLang", "targetLang", "sourceString", "targetString", "stringID", "url",
           "license", "translator_ID"]
DEFAULT_OUT = Path.home() / "LinguaMedica-dev"
DEFAULT_SEED = 20261111


class TicoError(ValueError):
    pass


def read_tico(path, source="en", target="rw"):
    """[dict] from a TICO-19 dev or test file: tab-separated, no quoting, 8 fields."""
    path = Path(path)
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
    if not rows:
        raise TicoError(f"{path.name} is empty")
    header = [h.strip() for h in rows[0]]
    if [h.casefold() for h in header] != [c.casefold() for c in COLUMNS]:
        raise TicoError(f"{path.name}: unexpected header {header}")
    out, seen = [], set()
    for n, row in enumerate(rows[1:], start=2):
        if not row:
            continue
        if len(row) != len(COLUMNS):
            raise TicoError(f"{path.name} line {n}: {len(row)} fields, not {len(COLUMNS)}")
        r = dict(zip(COLUMNS, row))
        if (r["sourceLang"], r["targetLang"]) != (source, target):
            raise TicoError(f"{path.name} line {n}: {r['sourceLang']}-{r['targetLang']}, "
                            f"not {source}-{target}")
        if r["stringID"] in seen:
            raise TicoError(f"{path.name} line {n}: the id {r['stringID']} is used twice")
        seen.add(r["stringID"])
        r["english"] = nfc(r["sourceString"]).strip()
        r["kinyarwanda"] = nfc(r["targetString"]).strip()
        out.append(r)
    return out


def dev_only(path):
    name = Path(path).name.casefold()
    if not name.startswith("dev."):
        raise SystemExit(f"Refusing {Path(path).name}: development items come from TICO-19's "
                         "dev split only (dev.en-rw.tsv); the test split stays free for "
                         "evaluation.")


def choose(rows, resource, n, seed):
    """(eligible rows with the terms each holds, the chosen ones in file order)."""
    eligible = []
    for r in rows:
        if not r["english"]:
            continue
        found = resource.retrieve(r["english"], None)
        if found:
            terms = [x.entries[0].english if x.entries else x.span.text for x in found]
            eligible.append((r, terms))
    picked = random.Random(seed).sample(range(len(eligible)), min(n, len(eligible)))
    return eligible, [eligible[i] for i in sorted(picked)]


def write(out, n, seed, resource, source, rows, eligible, chosen):
    base = f"tico19-dev_{n}_seed{seed}_{resource.sha256[:12]}"
    items_path = out / f"{base}.csv"
    refs_path = out / f"{base}_references.tsv"
    manifest_path = out / f"{base}_manifest.json"
    for p in (items_path, refs_path, manifest_path):
        if p.exists():
            raise SystemExit(f"{p} exists already: the same inputs give the same file, so "
                             "there is nothing to redo. Remove it first to regenerate.")
    with open(items_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["item", "sentence"])
        for r, _ in chosen:
            w.writerow([r["stringID"], r["english"]])
    with open(refs_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["item", "reference"])
        for r, _ in chosen:
            w.writerow([r["stringID"], r["kinyarwanda"]])
    terms = Counter(t for _, ts in chosen for t in ts)
    manifest = {
        "made": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"file": str(Path(source).resolve()), "sha256": sha256_file(source),
                   "rows": len(rows), "split": "dev"},
        "resource": resource.version(),
        "rule": "uniform draw, fixed seed, over the dev sentences in which retrieval finds "
                "at least one term of the resource",
        "seed": seed, "asked": n, "eligible": len(eligible), "chosen": len(chosen),
        "terms_in_chosen": {"occurrences": sum(terms.values()), "distinct": len(terms),
                            "by_term": dict(terms.most_common())},
        "licences_of_chosen": dict(Counter(r["license"] for r, _ in chosen).most_common()),
        "files": {"items": {"path": str(items_path), "sha256": sha256_file(items_path)},
                  "references": {"path": str(refs_path), "sha256": sha256_file(refs_path)}},
        "script": {"path": "scripts/dev_items_tico19.py",
                   "sha256": sha256_file(Path(__file__).resolve()),
                   "repository": repo_state()},
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return items_path, refs_path, manifest_path, manifest


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tico", required=True, help="TICO-19 dev.en-rw.tsv")
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--resource", default=str(DEFAULT_RESOURCE))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    a = p.parse_args(argv)
    if a.n < 1:
        raise SystemExit("--n is at least 1")
    dev_only(a.tico)
    rows = read_tico(a.tico)
    resource = Resource(a.resource)
    out = outside_repo(a.out)
    out.mkdir(parents=True, exist_ok=True)
    eligible, chosen = choose(rows, resource, a.n, a.seed)
    items, refs, manifest_path, m = write(out, a.n, a.seed, resource, a.tico, rows,
                                          eligible, chosen)
    print(f"{len(rows)} dev sentences; {len(eligible)} hold a term of {m['resource']['label']}; "
          f"{len(chosen)} chosen (seed {a.seed}), {m['terms_in_chosen']['occurrences']} term "
          f"occurrences, {m['terms_in_chosen']['distinct']} distinct terms")
    if len(chosen) < a.n:
        print(f"  only {len(chosen)} sentences were eligible, fewer than the {a.n} asked")
    print(f"Items:      {items}\nReferences: {refs}\nManifest:   {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
