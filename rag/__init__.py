"""
LinguaMedica RW: the grounded translation pipeline (thesis, chapter 4).

The code follows the pipeline figure in 4.2.1, one module per component:

    (1) input           items.py      English sentences, with the medical terms they carry
                                      when an item is annotated
    (2) term matching   matching.py   the English headwords and variants found in a sentence
    (3) retrieval       resource.py   the matched entries, from the exported dictionary
    (4) prompt          prompt.py     the sentence and the entries, in a versioned template
    (5) backbone        backbones.py  a frozen model, greedy decoding
    (6) checks          checks.py     term recall, adherence (strict and tolerant), misses

pipeline.py runs the six in order and writes the log; `python -m rag` is the command line.

What the code holds to, from the design memo:
- Nothing is trained. The resource is the only source of a term.
- Retrieval runs over English. Kinyarwanda is the payload, never the key.
- No model-written Kinyarwanda ever enters the resource or a prompt.
- A medical term the resource does not hold is flagged and stays in English, marked, for
  a human to fill. The model's own attempt goes to the log (miss_candidates.jsonl), never
  to the output.
- Decoding is greedy, and every setting is logged with the resource version, so any number
  can be regenerated from the log alone.
- The test set stays away from every system until it is frozen (items.py refuses it).
- A run that could not be regenerated from its log (uncommitted code, a resource
  outside the repository) does not start, unless --allow-dirty marks it so.
"""

__version__ = "0.1.0"
