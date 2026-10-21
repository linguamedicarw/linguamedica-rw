"""
The pipeline: the six components in order, for every item, and the run log (4.4.3).

A run writes one new folder, outside the repository (a run holds model output; the
public repository holds the method):

    run.json               settings, versions and the summary: the resource version (file,
                           SHA-256, last commit), K, the arm, the backbone and its exact
                           checkpoint, the decoding settings, the prompt template's version
                           and SHA-256, the matching-rule lists' version and SHA-256, the
                           items file's SHA-256, and the code's commit and SHA-256
    items.jsonl            per item: the matches, the misses, the prompt as sent, the raw
                           output, the output with missed terms marked, and the checks
    outputs.tsv            item id, status and output, for reading
    miss_candidates.jsonl  the model's own attempts at missed terms. Model-written
                           Kinyarwanda: never shown, never data, never read back by any
                           code here. At most a lead for the editor's suggestion queue.

A number is only as good as its log, so a run stops before it starts unless the code,
the resource and the matching rules are committed and unchanged (git status clean for
rag/, data/ and scripts/export_terms.py) and the resource is the repository's own file.
--allow-dirty runs anyway and marks the run `reproducible: false`, for trying things.

Item statuses: ok; needs_review (a placeholder lost or repeated, or the output cut at the
maximum length); unchecked (generated, but the item is not annotated, so a medical term
the resource does not hold may stand in the output in the model's words); skipped (a
missed term could not be hidden from the model, so nothing was sent); not_generated
(--backbone none).
"""

import csv
import hashlib
import json
import os
import re
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, checks, prompt
from .backbones import Decoding, make, runtime
from .items import Item, read_items
from .matching import ENGLISH_RULE, SPELLING, fold, locate_all, names, nfc, term_keys, words
from .resource import Resource

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESOURCE = REPO_ROOT / "data" / "terms.json"
DEFAULT_OUT = Path.home() / "LinguaMedica-runs"
TRACKED = ("rag", "data", "scripts/export_terms.py")


def outside_repo(folder):
    folder = Path(folder).expanduser().resolve()
    if folder == REPO_ROOT or REPO_ROOT in folder.parents:
        raise SystemExit("Refusing to write a run inside the repository: runs hold model "
                         "output, and the public repository holds the method. Use --out "
                         "with a folder outside it.")
    return folder


def _git(*args):
    """Read-only git: GIT_OPTIONAL_LOCKS=0 keeps `git status` from writing the index."""
    try:
        done = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True,
                              text=True, timeout=10,
                              env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def repo_state():
    """The commit, and whether the files a run depends on are committed and unchanged."""
    status = _git("status", "--porcelain", "--", *TRACKED)
    return {"commit": _git("rev-parse", "HEAD"),
            "clean": (status == "") if status is not None else None,
            "changed": status.splitlines() if status else []}


def file_git(path):
    """The last commit that touched a file in the repository."""
    path = Path(path).resolve()
    if REPO_ROOT not in path.parents:
        return {"in_repository": False}
    rel = str(path.relative_to(REPO_ROOT))
    return {"in_repository": True, "last_commit": _git("log", "-1", "--format=%H", "--", rel)}


def code_sha256():
    """One SHA-256 over every file of the package, by name and bytes."""
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(str(p.relative_to(REPO_ROOT)).encode("utf-8") + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a < out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _phrases(e):
    return ([e.found_as] if e.found_as else []) + names(e.term) + sorted(term_keys(e.term))


def _fold_text(text):
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()


def _leaks(sentence, covered, misses):
    """
    The missed terms still visible once the masked and the shown spans are blanked: a
    looser check than locate_all (the start of the term's longest word, at the start of
    any word), so that a form matching did not foresee stops the item instead of
    reaching the model.
    """
    chars = list(sentence)
    for a, b in covered:
        chars[a:b] = " " * (b - a)
    rest = _fold_text("".join(chars))
    out = []
    for e in misses:
        for phrase in _phrases(e):
            ws = [w for w in words(phrase) if len(w) >= 4]
            if ws:
                w = max(ws, key=len)
                probe = w[:-2] if len(w) >= 6 else w
                if re.search(r"(?<![^\W_])" + re.escape(probe), rest):
                    out.append(e.term)
                    break
    return out


def process(item, resource, k, arm, backbone, rules):
    """(record, miss candidates) for one item: components 2 to 6."""
    if item.sentence != nfc(item.sentence):
        item = Item(item.id, nfc(item.sentence), item.expected, item.notes, item.wrong_sense)
    retrieved = resource.retrieve(item.sentence, k)                          # (2), (3)
    compared = checks.compare_expected(item, retrieved)

    def longer_span_over(spot):
        return [r.span.text for r in retrieved
                if r.span.char_start <= spot[0] and spot[1] <= r.span.char_end
                and (r.span.char_end - r.span.char_start) > (spot[1] - spot[0])]

    expected, mask_spans, miss_where, masked_misses = [], [], [], []
    for e, i, reason in compared:
        rec = {"term": e.term, "found_as": e.found_as, "entry_id": e.entry_id,
               "retrieved": reason is None}
        if reason == "dropped_by_k":
            # Matched, but the annotated entry fell beyond K: a miss at this K. Nothing
            # is hidden: the system did match the span and shows what K kept.
            rec.update(reason=reason, span=retrieved[i].span.text, held_by_resource=True)
        elif reason == "not_retrieved":
            spots = locate_all(item.sentence, _phrases(e))
            free = [s for s in spots if not longer_span_over(s)]
            if spots and not free:
                # Only inside a longer retrieved term: the longest span wins (4.3.4), so
                # this annotation is not a term of the sentence and is not counted.
                rec.update(counted=False, nested_in=sorted({t for s in spots
                                                            for t in longer_span_over(s)}))
            else:                                                             # a miss
                rec.update(reason=reason, held_by_resource=resource.holds(e.term, e.entry_id),
                           located=bool(free))
                mask_spans.extend(free)
                miss_where.extend((s, rec["held_by_resource"]) for s in free)
                masked_misses.append(e)
        else:
            rec["span"] = retrieved[i].span.text
        expected.append(rec)

    mask_spans = _merge(mask_spans)

    def hidden(r):
        return any(r.span.char_start < b and a < r.span.char_end for a, b in mask_spans)

    for (e, i, reason), rec in zip(compared, expected):
        if reason is None and hidden(retrieved[i]):
            # Inside a longer annotated term that is a miss: not a term of its own.
            rec.update(counted=False, nested_in=["a missed annotated term"])

    shown = [r for r in retrieved if not hidden(r)]
    score_ids = {}
    for (e, i, reason), rec in zip(compared, expected):
        if reason is None and e.entry_id is not None and rec.get("counted") is not False:
            score_ids.setdefault(id(retrieved[i]), set()).add(e.entry_id)
    masked, pieces = prompt.mask(item.sentence, mask_spans)                   # (4)
    text, details = prompt.build(item.sentence, masked, shown, arm, pieces)
    hit_index = {i for _, i, _ in compared if i is not None}

    record = {
        "id": item.id, "sentence": item.sentence, "annotated": item.annotated,
        "notes": list(item.notes),
        "expected": expected if item.annotated else None,
        "retrieved": [{
            "span": r.span.text, "chars": [r.span.char_start, r.span.char_end],
            "key": r.span.key, "plural": r.span.plural,
            "kept": [{"id": e.id, "english": e.english, "category": e.category} for e in r.entries],
            "dropped_by_k": r.dropped,
            "annotated": (n in hit_index) if item.annotated else None,
            "wrong_sense": checks.is_wrong_sense(item, r),
            "hidden_by_a_miss": hidden(r),
        } for n, r in enumerate(retrieved)],
        "masked_sentence": masked,
        "placeholders_sent": [ph for ph, _ in pieces],
        "prompt": text, "prompt_details": details,
        "raw_output": None, "output": None, "terms": [], "generation": [],
        "status": None,
    }
    covered = mask_spans + [(r.span.char_start, r.span.char_end) for r in shown]
    leaks = _leaks(item.sentence, covered, masked_misses)
    if any(e.get("located") is False for e in expected) or leaks:
        record["status"] = "skipped"
        record["skipped"] = ("a missed term could not be hidden from the model (not found in "
                             "the sentence, or still visible after masking: "
                             f"{', '.join(leaks) or 'not found'}); check its found_as")
        return record, []
    if backbone is None:
        record["status"] = "not_generated"
        return record, []

    raw = backbone.generate(text)                                             # (5)
    record["generation"].append(dict(backbone.last))
    output = prompt.unmask(raw, pieces)
    lost = [ph for ph, _ in pieces if raw.count(ph) == 0]
    repeated = [ph for ph, _ in pieces if raw.count(ph) > 1]
    cut = backbone.last.get("done_reason") in ("length", "prompt_cut")
    scored = [(r, score_ids.get(id(r)), checks.is_wrong_sense(item, r)) for r in shown]
    record.update(raw_output=raw, output=output, placeholders_lost=lost,
                  placeholders_repeated=repeated,
                  terms=checks.check_terms(scored, output, rules))           # (6)
    if lost or repeated or cut:
        record["status"] = "needs_review"
    elif not item.annotated:
        record["status"] = "unchecked"
    else:
        record["status"] = "ok"

    candidates, asked = [], set()
    for (a, b), (ph, surface) in zip(mask_spans, pieces):
        if fold(surface) in asked:          # one attempt per missed term in an item
            continue
        asked.add(fold(surface))
        attempt = backbone.generate(prompt.miss_prompt(surface, item.sentence))
        candidates.append({
            "item": item.id, "term_as_written": surface, "placeholder": ph,
            "attempt": attempt, "generation": dict(backbone.last),
            "model_written": True, "never_shown": True,
            "held_by_resource": any(h for (w, h) in miss_where if a <= w[0] and w[1] <= b),
        })
    return record, candidates


def _run_dir(out, backbone_name, model, k, arm):
    root = outside_repo(out)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    who = backbone_name if not model else f"{backbone_name}-{model}"
    who = "".join(ch if ch.isalnum() or ch in "-." else "-" for ch in who)
    base = f"{stamp}_{who}_k{'all' if k is None else k}_{arm}"
    for n in range(1, 100):
        path = root / (base if n == 1 else f"{base}-{n}")
        try:
            path.mkdir(parents=True, exist_ok=False)
            return path
        except FileExistsError:
            continue
    raise SystemExit(f"Could not make a new run folder under {root}")


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8")


def _reproducible(repo, resource, rules):
    """[reasons this run could not be regenerated from its log]; empty when it could."""
    reasons = []
    if repo["clean"] is not True:
        reasons.append("rag/, data/ or scripts/export_terms.py has uncommitted changes"
                       if repo["clean"] is False else "git could not tell whether the code is committed")
    if REPO_ROOT not in resource.path.parents:
        reasons.append(f"the resource {resource.path} is not the repository's own file")
    if rules.path and REPO_ROOT not in Path(rules.path).parents:
        reasons.append(f"the matching rules {rules.path} are not the repository's own file")
    return reasons


def run(items_path, resource_path=DEFAULT_RESOURCE, out=DEFAULT_OUT, backbone_name="none",
        model=None, k=1, arm="base", rules_path=None, decoding=Decoding(),
        prompt_format="chat", revision=None, limit=None, argv=None, backbone=None,
        allow_dirty=False, say=print):
    """Run the pipeline over an items file; returns (run folder, run.json as a dict)."""
    items = read_items(items_path)                                            # (1)
    if limit:
        items = items[:limit]
    resource = Resource(resource_path)
    rules = checks.load_rules(rules_path)
    if arm not in prompt.ARMS:
        raise SystemExit(f"--arm must be one of {', '.join(prompt.ARMS)}")
    repo = repo_state()
    reasons = _reproducible(repo, resource, rules)
    if reasons and not allow_dirty:
        raise SystemExit("Not running: this run could not be regenerated from its log, because "
                         + "; ".join(reasons) + ". Commit first, or add --allow-dirty to try "
                         "things (the run is then marked reproducible: false).")
    if backbone is None:
        backbone = make(backbone_name, model, decoding, prompt_format, revision)
    else:
        backbone_name = backbone.name
    described = backbone.describe() if backbone else {"backbone": "none"}
    run_dir = _run_dir(out, backbone_name, model, k, arm)

    manifest = {
        "run": run_dir.name,
        "folder": str(run_dir),
        "status": "running",
        "reproducible": not reasons,
        "not_reproducible_because": reasons,
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": " ".join(argv) if argv else None,
        "resource": dict(resource.version(), git=file_git(resource.path), notes=resource.notes),
        "items": {"path": str(Path(items_path).expanduser().resolve()),
                  "sha256": sha256_file(items_path), "count": len(items), "limit": limit},
        "settings": {"k": "all" if k is None else k, "arm": arm, "spelling": SPELLING,
                     "english_rule": ENGLISH_RULE, "prompt_format": prompt_format,
                     "example_overlap_limit": prompt.EXAMPLE_OVERLAP_LIMIT},
        "prompt": {"template": prompt.TEMPLATE_VERSION, "miss_template": prompt.MISS_TEMPLATE_VERSION,
                   "template_sha256": prompt.TEMPLATE_SHA256},
        "backbone": described,
        "matching_rules": rules.describe(),
        "code": {"rag": __version__, "sha256": code_sha256(), "repository": repo, **runtime()},
    }
    _write_json(run_dir / "run.json", manifest)

    records = []
    with open(run_dir / "items.jsonl", "w", encoding="utf-8") as items_log, \
         open(run_dir / "miss_candidates.jsonl", "w", encoding="utf-8") as miss_log, \
         open(run_dir / "outputs.tsv", "w", encoding="utf-8", newline="") as outputs:
        table = csv.writer(outputs, delimiter="\t", lineterminator="\n")
        table.writerow(["item", "status", "output"])
        for n, item in enumerate(items, start=1):
            record, candidates = process(item, resource, k, arm, backbone, rules)
            records.append(record)
            items_log.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            for c in candidates:
                miss_log.write(json.dumps(dict(c, run=run_dir.name), ensure_ascii=False,
                                          default=str) + "\n")
            table.writerow([item.id, record["status"], record["output"] or ""])
            if backbone is not None and n % 10 == 0:
                say(f"  {n} of {len(items)} items")

    manifest.update(status="finished",
                    finished=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    summary=checks.summarise(records, rules))
    _write_json(run_dir / "run.json", manifest)
    for line in report(manifest):
        say(line)
    return run_dir, manifest


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def report(manifest):
    s = manifest["summary"]
    e = s["english_side"]
    st = s["statuses"]
    lines = [f"Run {manifest['run']}",
             f"Resource {manifest['resource']['label']}",
             f"Items {s['items']} (annotated {s['annotated']}; ok {st['ok']}, needs review "
             f"{st['needs_review']}, unchecked {st['unchecked']}, skipped {st['skipped']}, "
             f"not generated {st['not_generated']})"]
    if s["annotated"]:
        lines.append(f"English side: {e['retrieved']} of {e['expected_terms']} annotated terms "
                     f"retrieved (term recall {_pct(e['term_recall'])}). Misses flagged: "
                     f"{e['misses']} (the resource holds {e['misses_held_by_resource']} of them; "
                     f"K dropped {e['misses_dropped_by_k']}). Retrievals not in the "
                     f"annotation: {e['retrievals_not_annotated']}")
        if e["annotations_nested_in_a_longer_term"]:
            lines.append(f"  {e['annotations_nested_in_a_longer_term']} annotated terms stood only "
                         "inside a longer term and were not counted (longest span wins)")
    else:
        lines.append("English side: no item is annotated, so misses and term recall are not computed")
    a = s["adherence"]
    if a:
        tolerant = (f"tolerant {a['tolerant']['used']} of {a['tolerant']['of']} "
                    f"({_pct(a['tolerant']['rate'])})" if a["tolerant"]
                    else "tolerant not reported (rag/matching_rules.json has no lists yet)")
        lines.append(f"Adherence: strict {a['strict']['used']} of {a['strict']['of']} "
                     f"({_pct(a['strict']['rate'])}); {tolerant}")
        w = a["wrong_sense_retrievals"]
        if w["of"]:
            lines.append(f"  wrong-sense retrievals: {w['of']}, rendering used in {w['used']}")
        p = s["placeholders"]
        if p["sent"]:
            lines.append(f"Placeholders: {p['sent']} sent, {p['lost']} lost, {p['repeated']} repeated")
        if s["outputs_cut_at_max_length"]:
            lines.append(f"  {s['outputs_cut_at_max_length']} outputs cut at the maximum length")
    else:
        lines.append("No model ran: the prompts are in items.jsonl")
    if not manifest["reproducible"]:
        lines.append("NOT REPRODUCIBLE: " + "; ".join(manifest["not_reproducible_because"]))
    lines.append(f"Log: {manifest['folder']}")
    return lines
