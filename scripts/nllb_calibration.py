"""
Calibration of the NLLB-200 baseline (thesis Aim 3): NLLB-200 3.3B translating the
English-Kinyarwanda TICO-19 dev and test splits through CTranslate2, at the settings
Moslem et al. (2023a) report (int8, beam size 4), and the same at 16-bit, the precision of
every reported result (Dr. Dastour, 8 November 2026). The published score is checked in
the original before the two are compared; nothing here holds it.

Three steps, so that the GPU job needs no network and scoring needs no GPU:

    python scripts/nllb_calibration.py convert [--model facebook/nllb-200-3.3B]
        [--to ~/data/ct2/nllb-200-3.3B]
        Hugging Face checkpoint (already downloaded) -> CTranslate2, float32 weights, so
        that --compute-type int8 runs as int8_float32. Records the source commit in
        ct2_provenance.json. Runs offline, and never empties a folder holding other files.

    python scripts/nllb_calibration.py translate --tico DIR --model CT2_DIR
        --compute-type int8|int8_float32|int8_float16|float16|bfloat16|float32 [--beam 4]
        [--batch 16]
        [--max-length 256] [--tokenizer facebook/nllb-200-3.3B] [--name NAME]
        [--out ~/LinguaMedica-runs]
        On the GPU. run.json records the compute type CTranslate2 actually used (int8 on
        float32 weights is int8_float32; which int8 variant the paper ran is to be checked). Writes run.json and hyp.dev.jsonl, hyp.test.jsonl to --out/NAME, one
        line per sentence, flushed after every batch. The same command again continues
        where a preempted job stopped, and refuses to if any setting changed.

    python scripts/nllb_calibration.py score RUN_FOLDER [--tico DIR]
        Anywhere with sacrebleu and sentencepiece (it fetches the SentencePiece models the
        first time, so not on a node without network). Writes scores.json: spBLEU with the
        FLORES-200 and with the FLORES-101 SentencePiece model (which one the paper used is
        to be checked in its table), chrF++ and TER, for each split and for both together,
        with sacrebleu's signatures.

TICO-19 is read without quoting (see dev_items_tico19.py): 971 dev and 2,100 test rows,
3,071 in all; the paper reports 3,070 segments, so the per-split scores are given too.
Public data only (TICO-19 is a public benchmark), as Hellbender and Nautilus require.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag.pipeline import outside_repo, repo_state, sha256_file  # noqa: E402

_spec = importlib.util.spec_from_file_location("dev_items_tico19",
                                               ROOT / "scripts" / "dev_items_tico19.py")
_tico = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tico)
read_tico = _tico.read_tico

SPLITS = ("dev", "test")
COMPUTE_TYPES = ("int8", "int8_float32", "int8_float16", "float16", "bfloat16", "float32")
CT2_OUTPUT = {"model.bin", "config.json", "shared_vocabulary.json", "shared_vocabulary.txt",
              "source_vocabulary.json", "target_vocabulary.json", "vocabulary.json",
              "vocabulary.txt"}
DEFAULT_MODEL = "facebook/nllb-200-3.3B"
DEFAULT_OUT = Path.home() / "LinguaMedica-runs"
SRC, TGT = "eng_Latn", "kin_Latn"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tico_files(folder):
    folder = Path(folder).expanduser().resolve()
    files = {s: folder / s / f"{s}.en-rw.tsv" for s in SPLITS}
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        raise SystemExit("TICO-19 files not found: " + ", ".join(missing)
                         + " (--tico is the tico19-testset folder from tico19-testset.zip)")
    return files


# --- convert ----------------------------------------------------------------------

def convert(model_id, to):
    """
    float32 weights: loaded with --compute-type int8, CTranslate2 then runs int8 weights
    with float32 activations (int8_float32), as after a plain int8 conversion of the float32
    checkpoint; float16 and bfloat16 are cast at load. The effective type is in run.json.
    """
    to = Path(to).expanduser()
    if (to / "ct2_provenance.json").exists():       # written last: the conversion finished
        raise SystemExit(f"{to} holds a converted model already")
    if to.exists():
        others = sorted(p.name for p in to.iterdir() if p.name not in CT2_OUTPUT)
        if others:                                   # force would delete the whole folder
            raise SystemExit(f"{to} holds other files ({', '.join(others[:5])}); convert "
                             "into a new or empty folder")
    import ctranslate2
    import transformers
    from huggingface_hub import snapshot_download
    local = Path(snapshot_download(model_id, local_files_only=True))
    # force: a conversion stopped part-way (a preempted job) is redone from the start
    ctranslate2.converters.TransformersConverter(str(local)).convert(
        str(to), quantization="float32", force=True)
    provenance = {"source": model_id, "commit": local.name, "weights": "float32",
                  "ctranslate2": ctranslate2.__version__,
                  "transformers": transformers.__version__, "converted": now()}
    (to / "ct2_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n",
                                            encoding="utf-8")
    return to, provenance


# --- translate --------------------------------------------------------------------

class CT2Engine:
    """NLLB through CTranslate2: tokenizer from Hugging Face, decoding in CTranslate2."""

    def __init__(self, model_dir, tokenizer_id, compute_type, beam, max_length):
        import ctranslate2
        import transformers
        self.ctranslate2, self.transformers = ctranslate2, transformers
        self.tokenizer = transformers.AutoTokenizer.from_pretrained(tokenizer_id, src_lang=SRC)
        self.translator = ctranslate2.Translator(str(model_dir), device="cuda",
                                                 compute_type=compute_type)
        self.beam, self.max_length = beam, max_length

    def translate(self, sentences):
        tok = self.tokenizer
        sources = [tok.convert_ids_to_tokens(tok.encode(s)) for s in sentences]
        results = self.translator.translate_batch(
            sources, target_prefix=[[TGT]] * len(sources), beam_size=self.beam,
            max_decoding_length=self.max_length)
        out = []
        for r in results:
            tokens = r.hypotheses[0]
            if tokens and tokens[0] == TGT:
                tokens = tokens[1:]
            out.append(tok.decode(tok.convert_tokens_to_ids(tokens),
                                  skip_special_tokens=True).strip())
        return out

    def describe(self):
        return {"runtime": "ctranslate2", "ctranslate2": self.ctranslate2.__version__,
                "transformers": self.transformers.__version__,
                # what CTranslate2 resolved the requested type to on this device
                "compute_type_effective": getattr(self.translator, "compute_type", None)}


def gpu_name():
    try:
        done = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                               "--format=csv,noheader"], capture_output=True, text=True,
                              timeout=20)
        return done.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _complete(path):
    """
    The JSON objects on a file's complete lines. Read as bytes: a stop can cut a line
    inside a multi-byte character, and that line is dropped, not an error.
    """
    if not path.exists():
        return []
    *lines, _tail = path.read_bytes().split(b"\n")
    out = []
    for raw in lines:
        try:
            out.append(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            break
    return out


def _atomic(path, text):
    """Write a file whole, by a rename, so a stop never leaves it half written."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _save(run_dir, manifest):
    _atomic(run_dir / "run.json", json.dumps(manifest, indent=2) + "\n")


def _identity(m):
    return dict({k: m.get(k) for k in ("settings", "model", "tico", "tokenizer")},
                script=(m.get("code") or {}).get("script_sha256"))


def translate(tico_dir, model_dir, compute_type, name, out=DEFAULT_OUT, beam=4, batch=16,
              max_length=256, tokenizer=DEFAULT_MODEL, engine=None, say=print):
    if compute_type not in COMPUTE_TYPES:
        raise SystemExit(f"--compute-type must be one of {', '.join(COMPUTE_TYPES)}")
    files = tico_files(tico_dir)
    data = {s: read_tico(p) for s, p in files.items()}
    model_dir = Path(model_dir).expanduser().resolve()
    prov_path = model_dir / "ct2_provenance.json"
    provenance = (json.loads(prov_path.read_text(encoding="utf-8")) if prov_path.exists()
                  else {"note": "no ct2_provenance.json: convert with this script to record "
                                "the source commit"})
    run_dir = outside_repo(out) / name
    manifest = {
        "run": name, "status": "running", "started": now(),
        "settings": {"compute_type": compute_type, "beam": beam, "max_length": max_length,
                     "batch": batch, "source": SRC, "target": TGT},
        "model": {"path": str(model_dir), "provenance": provenance},
        "tokenizer": tokenizer,
        "tico": {s: {"file": str(p), "sha256": sha256_file(p), "rows": len(data[s])}
                 for s, p in files.items()},
        "code": {"script_sha256": sha256_file(Path(__file__).resolve()),
                 "repository": repo_state(), "python": platform.python_version()},
    }
    if (run_dir / "run.json").exists():
        saved = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        if saved.get("status") == "finished":
            raise SystemExit(f"{name} is finished; nothing to resume")
        if _identity(saved) != _identity(json.loads(json.dumps(manifest))):
            raise SystemExit(f"Not resuming {name}: its settings, model, tokenizer or TICO-19 "
                             "files differ from this command's. Start a new --name.")
        saved.setdefault("resumed", []).append(now())
        manifest = saved
    else:
        run_dir.mkdir(parents=True, exist_ok=True)
    engine = engine or CT2Engine(model_dir, tokenizer, compute_type, beam, max_length)
    manifest["engine"], manifest["gpu"] = engine.describe(), gpu_name()
    _save(run_dir, manifest)

    for split in SPLITS:
        path = run_dir / f"hyp.{split}.jsonl"
        done = _complete(path)
        ids = [r["stringID"] for r in data[split]]
        if [d.get("id") for d in done] != ids[:len(done)]:
            raise SystemExit(f"{path.name} does not follow the order of the TICO-19 file")
        _atomic(path, "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in done))  # drop a cut line
        todo = data[split][len(done):]
        if done:
            say(f"{split}: {len(done)} of {len(ids)} already translated")
        with open(path, "a", encoding="utf-8") as f:
            for i in range(0, len(todo), batch):
                chunk = todo[i:i + batch]
                hyps = engine.translate([r["english"] for r in chunk])
                for r, h in zip(chunk, hyps):
                    f.write(json.dumps({"id": r["stringID"], "hyp": h}, ensure_ascii=False) + "\n")
                f.flush()
                say(f"{split}: {len(done) + i + len(chunk)} of {len(ids)}")
    manifest.update(status="finished", finished=now())
    _save(run_dir, manifest)
    return run_dir, manifest


# --- score ------------------------------------------------------------------------

def _metrics():
    from sacrebleu.metrics import BLEU, CHRF, TER
    metrics = {"chrF++": lambda: CHRF(word_order=2), "TER": lambda: TER()}
    for spm in ("flores200", "flores101"):
        metrics[f"spBLEU ({spm})"] = (lambda s=spm: BLEU(tokenize=s))
    return metrics


def score(run_dir, tico_dir=None):
    import sacrebleu
    run_dir = Path(run_dir).expanduser().resolve()
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "finished":
        raise SystemExit(f"{run_dir.name} is not finished; run translate again to complete it")
    files = (tico_files(tico_dir) if tico_dir
             else {s: Path(manifest["tico"][s]["file"]) for s in SPLITS})
    for s, p in files.items():
        if sha256_file(p) != manifest["tico"][s]["sha256"]:
            raise SystemExit(f"{p} is not the TICO-19 file the run translated (SHA-256 differs)")
    hyps, refs = {}, {}
    for s in SPLITS:
        rows = read_tico(files[s])
        got = {d["id"]: d["hyp"] for d in _complete(run_dir / f"hyp.{s}.jsonl")}
        missing = [r["stringID"] for r in rows if r["stringID"] not in got]
        if missing:
            raise SystemExit(f"{s}: {len(missing)} sentences have no translation")
        hyps[s] = [got[r["stringID"]] for r in rows]
        refs[s] = [r["kinyarwanda"] for r in rows]
    hyps["all"], refs["all"] = hyps["dev"] + hyps["test"], refs["dev"] + refs["test"]
    scores = {"run": manifest["run"], "scored": now(), "sacrebleu": sacrebleu.__version__,
              "settings": manifest["settings"], "model": manifest["model"],
              "segments": {k: len(v) for k, v in hyps.items()}, "scores": {}}
    for name, make in _metrics().items():
        try:
            metric = make()
            values = {k: round(metric.corpus_score(hyps[k], [refs[k]]).score, 2)
                      for k in ("dev", "test", "all")}
            # the signature exists only once the metric has scored something
            scores["scores"][name] = {"signature": str(metric.get_signature()), **values}
        except (ImportError, OSError, RuntimeError) as exc:
            scores["scores"][name] = {"skipped": f"{type(exc).__name__}: {exc}"[:300]}
    (run_dir / "scores.json").write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
    return scores


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--model", default=DEFAULT_MODEL)
    c.add_argument("--to", default=str(Path.home() / "data" / "ct2" / "nllb-200-3.3B"))
    t = sub.add_parser("translate")
    t.add_argument("--tico", required=True)
    t.add_argument("--model", required=True, help="the CTranslate2 model folder")
    t.add_argument("--compute-type", required=True, choices=COMPUTE_TYPES)
    t.add_argument("--beam", type=int, default=4)
    t.add_argument("--batch", type=int, default=16)
    t.add_argument("--max-length", type=int, default=256)
    t.add_argument("--tokenizer", default=DEFAULT_MODEL)
    t.add_argument("--name")
    t.add_argument("--out", default=str(DEFAULT_OUT))
    s = sub.add_parser("score")
    s.add_argument("run")
    s.add_argument("--tico")
    a = p.parse_args(argv)
    if a.command == "convert":
        to, prov = convert(a.model, a.to)
        print(f"Converted {prov['source']}@{prov['commit']} to {to}")
    elif a.command == "translate":
        name = a.name or f"nllb-calibration_{a.compute_type}_{os.environ.get('SLURM_JOB_ID', 'local')}"
        run_dir, _ = translate(a.tico, a.model, a.compute_type, name, a.out, a.beam, a.batch,
                               a.max_length, a.tokenizer)
        print(f"Finished: {run_dir}")
    else:
        result = score(a.run, a.tico)
        for metric, v in result["scores"].items():
            print(f"{metric}: " + (v["skipped"] if "skipped" in v else
                                   f"dev {v['dev']}, test {v['test']}, all {v['all']}  ({v['signature']})"))
        print(f"Segments: {result['segments']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
