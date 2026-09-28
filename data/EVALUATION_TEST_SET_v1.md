# Evaluation test set: selection rule (v1)

Fixed on 27 September 2026, before any score exists: scoring of annotation corpus v1 opens on 1 October 2026. This file says which terms and sentences the evaluation of the grounded RAG system will use, so that none of it can be chosen after the scores are in.

## What the test set measures

Whether grounding translation on this dictionary raises terminology accuracy from English into Kinyarwanda over ungrounded baselines, and at what cost to fluency. Every reported comparison runs on this test set.

## Which terms can be tested

- Only terms of annotation corpus v1 (`data/annotation_corpus_v1.csv`, SHA-256 `2b7fc89a7876ce3219f74079b939e30768aa6fb9fa719ca11d110b77e90500fa`), scored in the October 2026 round.
- A term is gold when both independent reviewers, Olive Umuhoza (OU) and Yvette Nkurunziza (YV), gave its rendering a 4 as their latest blind score before the round closed.
- Scores by the editor, Christophe Mumaragishyika (CM), never qualify a term, because he wrote or edited the renderings. This is stricter than the site's computed validation status, which also counts his scores on terms he did not contribute.
- The gold rendering is the exact Kinyarwanda string the reviewers were shown, recorded with every score. A term whose rendering changes after it was scored leaves the gold.
- Pilot terms count like any other term.

## Development and test

Every gold term goes to test. Tuning runs on development items built the same way around the dictionary's published terms, which are not part of the round. Tuning covers the prompts, the number of retrieved entries, the policy for terms the dictionary does not hold, the matching rule, few-shot examples, the model checkpoint and the decoding settings. Each is fixed and recorded before the test run.

## What a test item is

- One English sentence from the same kinds of sources as the dictionary (consent forms, research documents, clinical texts), with a Kinyarwanda reference translation, tagged with the gold terms it contains. Tags come from string-matching the English headwords and their English variants, and every match is checked by hand.
- The reference is an existing human translation where one exists, with the tagged terms given their gold renderings; every such edit is logged. Where none exists, the editor translates the sentence himself, and the reference is marked as his.
- The dictionary's own example sentences are never test items, because a system can retrieve them together with the entry.
- TICO-19 English to Kinyarwanda is a separate calibration set, read as a soft ceiling because of possible training-data leakage.

## The walls

- The test file gets a SHA-256 and a git tag before any system sees it.
- Every system (NLLB-200, a zero-shot LLM, the lookup-only baseline and the grounded pipeline) runs once on the same items with the same measures, and every result names the dictionary version it ran against.
- The dictionary is not hidden. It is the grounded system's memory, so the gold terms sit in its retrieval store once they are published after the round. What is held out is the sentences.
- Nothing from a test item is used to write a prompt, pick a few-shot example or choose a setting.
- The pairwise human judgments (terminology adherence and fluency, by the two reviewers, with system identity hidden) are drawn from test items only.

## Still open

Whether a variant listed with an entry counts as a match for terminology adherence. It is decided together with the matching rule, before any system runs on the test set.

## Dates

The gold list is drawn the week the round closes (30 October 2026). The test set is frozen by the end of November 2026.
