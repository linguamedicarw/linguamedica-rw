# Annotation corpus v1

The frozen set of terms the reviewers score in the first validation round of LinguaMedica RW. This file describes it; the data is `annotation_corpus_v1.csv` beside it.

| | |
|---|---|
| File | `data/annotation_corpus_v1.csv` (UTF-8, comma-separated, LF line endings, one header row) |
| Terms | 189 |
| SHA-256 | `2b7fc89a7876ce3219f74079b939e30768aa6fb9fa719ca11d110b77e90500fa` |
| Built | 27 September 2026, from the priority pool the editor settled on 26 and 27 September 2026 |
| Freeze | 27 September 2026, git tag `annotation-corpus-v1`; scoring opens 1 October 2026 |

To check the file: `shasum -a 256 data/annotation_corpus_v1.csv` must print the SHA-256 above. The test suite checks it on every run, so an edit to the file after the freeze fails the tests until it is recorded here.

## What is in it

Terms recorded by two collectors between 3 and 31 August 2026, curated by the editor, Christophe Mumaragishyika, and sampled from four priority domains.

| Domain | Terms | In the pilot |
|---|---|---|
| Diagnostics | 74 | 6 |
| Infectious Disease | 51 | 6 |
| Obstetrics | 34 | 6 |
| Pharmacology | 30 | 6 |
| **Total** | **189** | **24** |

Contributor of record: Sarah Izabayo 93, Virginie Mpuhwezimana 88, Christophe Mumaragishyika 8.

The editor changed 17 renderings (refinement 6, correction 6, lead chosen 3, definition to headword 2); the other 172 keep the collector's rendering.

Nine terms show no example sentence. For five, the rendering was corrected and the collector's example went with it; for four (Contamination, Fetus, Placenta, Uterus), the example did not show the headword. Every example is in Kinyarwanda.

## The rules the entries follow

- **Curation criterion:** Keep the rendering that carries the concept most concretely for a native speaker. Where two renderings are equally concrete, keep the shorter. Length is the tiebreaker, never the test.
- **Substitution test:** a rendering stays in the headword field if a speaker can drop it into a sentence where the English term would sit. One that only answers "what is X", usually by carrying defining criteria inside it, moves to the example or etymology field (in this file, the note), and the headword field takes a form that substitutes.
- **Credit follows the rendering:** the collector whose Kinyarwanda is published is the contributor of record. Where the other collector recorded the same English first, her name goes into the provenance. A typo is a slip in recording, not a failure to record, so it does not cost a collector her priority.
- **The editor's changes**, recorded in the `change` column:
  - *Refinement:* the collector's rendering was right, or right in its build, and the editor made it more precise. She keeps the credit; the refinement is noted.
  - *Correction:* the collector's rendering was wrong for the term. The entry is credited to the editor; the collector is named only as the one who recorded the English term; her rendering is not published.
  - *Definition to headword:* the collector's rendering was a correct description, not a word. The editor's word takes the headword; her description moves to the note, credited to her.
  - *Lead chosen:* where a collector wrote two forms in one rendering, the editor picked the lead and the other became a variant; she keeps the credit.
- **One category per term, by what kind of thing it is.** When a term could take a label for what it is (Anatomy, Symptoms, Diagnostics, Pharmacology, Surgery) or a label for its medical field, what it is wins. Diagnostics holds tests, measurements, and the results only a test can show.
- **Domain:** when a term's category is one of the four domains, that is its domain; otherwise the field it serves decides (Placenta: category Anatomy, domain Obstetrics). Pool membership is by domain.

## Columns

| Column | What it holds |
|---|---|
| `key` | Stable id: S or V (the collector) and her row number. The app keys the import on it. |
| `collector_row` | The same row, written out ("Sarah 84"). |
| `domain` | Diagnostics, Infectious Disease, Obstetrics or Pharmacology. |
| `category` | What kind of thing the term is. |
| `english` | The English headword, the one term a reviewer is shown. |
| `english_variants` | Other English names, separated by " / ". Searchable, never shown to reviewers. |
| `kinyarwanda` | The rendering a reviewer scores, always one form. |
| `kinyarwanda_variants` | Other Kinyarwanda forms, separated by " / ". Searchable, never scored. |
| `example_rw` | The collector's example sentence, as the score page shows it. Empty where the example was dropped. |
| `contributor` | Contributor of record, by the credit rules above. |
| `change` | Kept, Refinement, Correction, Definition to headword, or Lead chosen. |
| `provenance` | Who recorded the term, when and from what kind of source, and what the editor changed. |
| `note` | The editor's note: etymology he gave, why a rendering was corrected, usage. Internal: never shown to reviewers, not part of the public entry. |
| `source_type` | The kind of source the collector recorded it from. |
| `recorded` | The date the collector recorded it. |
| `pool_route` | How the term entered the pool: as filed, moved in, or by the editor's call. |
| `pilot` | yes for the 24 pilot terms. |

## The pilot

Six terms per domain, 24 in all. Within each domain, among the terms no reviewer contributed (so every reviewer can score every pilot term), the pilot is the six whose SHA-256 of `linguamedica-pilot-v1:<key>` sorts lowest. The rule is fixed in advance and anyone can re-run it. Pilot scores are kept and count toward the round.

- **Diagnostics:** Computed tomography (V369), Dermoscopy (S283), Etiology (S93), Lumbar puncture (S241), To submit medical tests (S13), Venipuncture (V247)
- **Infectious Disease:** Antibody (S257), Contact tracing (S261), Hand hygiene (V222), Latent infection (S256), Plasmodium vivax (S36), Scabies (S276)
- **Obstetrics:** Amniotic fluid (V151), Cephalopelvic disproportion (V152), Cesarean section (V39), Post-term pregnancy (S213), Transverse lie (S217), Umbilical cord (V42)
- **Pharmacology:** Analgesic (V196), Anti-inflammatory (S151), Antipyretic (S150), Pharmacokinetics (S146), Prescription (V197), Sedative (S152)

## How the app uses it

- At startup the app loads the file once into the terms table, unpublished. From then on the database is the working copy and this file is the frozen record: a later change is recorded as an editorial decision in the code, never by editing the file.
- Unpublished terms stay off the public site, the API and the data export (`data/terms.json`, the store the RAG build reads) until the editor publishes them after the round.
- The review queue serves this corpus only. With `REVIEW_PHASE=pilot` (the default) it serves the 24 pilot terms; with `REVIEW_PHASE=round`, all 189. The guideline anchors and author exclusion apply as before: no reviewer is shown a term they contributed.
