"""
The command line. From the repository root, with the venv active:

    python -m rag resource
        the resource version, its keys, and notes on entries to tidy

    python -m rag run --items DEV.csv
        the English side only (no model): matches, misses, term recall, and the prompts

    python -m rag run --items DEV.csv --backbone ollama --model gemma3:4b
        the 4B model on this computer, through Ollama

    python -m rag run --items DEV.csv --backbone transformers --model google/gemma-3-27b-it
        a Hugging Face checkpoint (Hellbender). TranslateGemma: add --prompt-format gemma-raw

Options for run: --k 1|3|5|all (candidates kept per matched span, default 1), --arm
base|example (the example sentence in the prompt or not), --resource (default
data/terms.json), --rules (default rag/matching_rules.json), --max-new-tokens, --seed,
--context-tokens (Ollama's context window), --revision (a checkpoint's exact commit),
--out (default ~/LinguaMedica-runs), --limit, --allow-dirty (run with uncommitted
changes; the run is marked not reproducible).

rag/examples/smoke_items.csv holds five English sentences around published terms, for
trying the plumbing. They are not development items.
"""

import argparse
import sys

from .backbones import BACKBONES, PROMPT_FORMATS, Decoding
from .pipeline import DEFAULT_OUT, DEFAULT_RESOURCE, run
from .prompt import ARMS
from .resource import Resource


def _k(value):
    if value == "all":
        return None
    try:
        k = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("K is a whole number or 'all'") from None
    if k < 1:
        raise argparse.ArgumentTypeError("K is at least 1")
    return k


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="python -m rag", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    res = sub.add_parser("resource", help="the resource version, its keys and notes")
    res.add_argument("--resource", default=str(DEFAULT_RESOURCE))

    r = sub.add_parser("run", help="run the pipeline over an items file")
    r.add_argument("--items", required=True)
    r.add_argument("--backbone", choices=BACKBONES, default="none")
    r.add_argument("--model")
    r.add_argument("--k", type=_k, default=1)
    r.add_argument("--arm", choices=ARMS, default="base")
    r.add_argument("--resource", default=str(DEFAULT_RESOURCE))
    r.add_argument("--rules")
    r.add_argument("--max-new-tokens", type=int, default=Decoding.max_new_tokens)
    r.add_argument("--seed", type=int, default=Decoding.seed)
    r.add_argument("--context-tokens", type=int, default=Decoding.context_tokens)
    r.add_argument("--allow-dirty", action="store_true")
    r.add_argument("--prompt-format", choices=PROMPT_FORMATS, default="chat")
    r.add_argument("--revision")
    r.add_argument("--out", default=str(DEFAULT_OUT))
    r.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    if args.command == "resource":
        resource = Resource(args.resource)
        v = resource.version()
        keys = resource.db.execute("SELECT COUNT(*) FROM keys").fetchone()[0]
        print(f"{v['label']}")
        print(f"  sha256 {v['sha256']}")
        print(f"  schema {v['schema_version']}, {keys} English keys, longest key "
              f"{resource.max_words} words, variants exported: {'yes' if v['has_variants'] else 'no'}")
        for note in resource.notes:
            print(f"  note: {note}")
        return 0

    decoding = Decoding(max_new_tokens=args.max_new_tokens, seed=args.seed,
                        context_tokens=args.context_tokens)
    run(args.items, args.resource, args.out, args.backbone, args.model, args.k, args.arm,
        args.rules, decoding, args.prompt_format, args.revision, args.limit,
        argv=["python -m rag", *argv], allow_dirty=args.allow_dirty)
    return 0


if __name__ == "__main__":
    sys.exit(main())
