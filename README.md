# Legal Knowledge Extractor

Turns large collections of legal PDFs into a searchable library of **independently worded,
structured knowledge records** (cases, concepts, rules, examples and comparisons). Every record
is traceable to its source document and pages. The library holds no copy or paraphrase of the source.

```
PDF folder → text / OCR → topics & sections → content types → facts (LLM pass 1)
          → records from facts only (LLM pass 2) → validation → linked, searchable library
```

## Setup (once)

```powershell
python -m venv .venv
.venv\Scripts\activate            # Mac/Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env            # then put your Anthropic API key in .env
```

For scanned PDFs, also install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) and set
`TESSDATA_PREFIX` in `.env`.

## Everyday use

1. Put PDFs in `data/inbox/` (sub-folders are fine).
2. Check what it will cost: `lke run --dry-run`
3. Process everything: `lke run`
4. Look at the results:

| Command | What it does |
|---|---|
| `lke status` | Documents, progress per stage, record counts |
| `lke failures` | Sections that failed and why |
| `lke topics` | Topic → subtopic tree with record counts |
| `lke search "retrenchment notice"` | Keyword search (`--semantic` for meaning-based search, needs `pip install -e ".[search]"`) |
| `lke show <record_id>` | One record as JSON, with its relationships |
| `lke review list` / `show` / `approve` / `reject` | Records flagged for a human decision |
| `lke export` | `records.jsonl`, `relations.jsonl`, `topics.jsonl`, `records.csv` in `data/library/export/` |
| `lke reprocess <doc_id> --from compose` | Redo a document after changing prompts or models |
| `lke schemas` | Write the JSON schema of each record type to `schemas/` |

`lke run` can be stopped at any time (Ctrl+C, crash, shutdown). Run it again to continue:
finished sections are never sent to the LLM twice, and failed sections are retried.
Each run writes a summary to `data/reports/run-<time>.md`.

## How it works

| Stage | Code | Output (in `data/work/<doc_id>/`) | LLM? |
|---|---|---|---|
| 1. Read PDF, OCR scanned pages, remove headers/footers | `ingest/` | `pages.jsonl`, `document.json` | no |
| 2. Topic tree from bookmarks or headings (font size, bold, numbering) | `structure/` | `structure.json` | no |
| 3. Logical sections of ~5k tokens, with `[[p. N]]` page markers | `structure/sectioner.py` | `sections.jsonl` | no |
| 4. Content types, skip front matter, spot author commentary | `classify/` | `classified.jsonl` | optional |
| 5. Pass 1: short notes + exact identifiers + page numbers | `extract/fact_extractor.py` | `facts/<section>.json` | yes |
| 6. Pass 2: records written **from the notes only** | `extract/record_composer.py` | `records/<section>.json` | yes |
| 7. Validation (see below) | `validate/` | pass / reword / review | no |
| 8. Merge same case/rule across documents, entities, relationships | `link/` | `data/library/library.db` | no |

### Safeguards

- **No copying:** the record writer never sees the source text. Each record is then compared
  with its section: if it shares a run of ≥ 12 words, or more than 15 % of its 8-word sequences,
  it is reworded once and otherwise sent to review. Legal identifiers are excluded from this
  check because they are supposed to match.
- **Legal terms kept exact:** case names, citations, courts, statutes and provisions come from
  pass 1 *as written* and are copied into records by code. Any identifier that does not occur in
  the source is treated as possibly invented, and the record goes to review.
- **Source vs. interpretation:** every statement is marked `source` or `interpretation` and
  cites the notes (and so the pages) it is based on.
- **Proprietary content:** practice pointers, author opinions, original examples and distinctive
  tables are flagged and held in the review queue instead of entering the library.
- **Traceability:** every record lists its document ids and page numbers.

## Configuration

Everything is in `config.yaml`: section sizes, OCR, models and effort, overlap thresholds,
whether short statutory quotes may be stored, parallelism and prices for cost estimates.
For a lower cost, set `extract_model` / `compose_model` to `claude-sonnet-5-5`.

## Tests

```powershell
pytest -q
```
The tests use a fake LLM, so they run offline and cost nothing.
