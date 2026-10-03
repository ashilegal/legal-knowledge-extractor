# Legal Knowledge Extractor

Turns large collections of legal PDFs into a searchable library of **independently worded,
structured knowledge records** (cases, concepts, rules, examples and comparisons). Every record
is traceable to its source document and pages.

> This is a technical method for avoiding unnecessary reproduction of the source's original
> expression. It is **not** a legal guarantee: records are not automatically "copyright-free".

```
PDF folder → text / OCR → topics & sections → content types → facts (LLM pass 1)
          → records from facts only (LLM pass 2) → validation → linked, searchable library
```

## Setup (once)

```powershell
python -m venv .venv
.venv\Scripts\activate            # Mac/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

### Choose the AI model

**Free (default): a model on your own computer, through [Ollama](https://ollama.com/download).**
No API key, no cost, and the documents never leave your computer. It is slower and less accurate
than the paid API.

1. Install Ollama from https://ollama.com/download and start it.
2. Download a model that fits your computer's memory (RAM):

   | RAM | Command | `ollama_model` in config.yaml |
   |---|---|---|
   | 8–12 GB | `ollama pull qwen2.5:7b` | `qwen2.5:7b` |
   | 16 GB+ | `ollama pull qwen2.5:14b` | `qwen2.5:14b` (default) |

**Paid: the Anthropic API** (better quality, faster). Set `provider: anthropic` in
`config.yaml`, copy `.env.example` to `.env` and put your API key there. With the API you can
also raise `sectioning.target_tokens` to 5000, `max_tokens` to 8000 and
`max_concurrent_requests` to 4.

For scanned PDFs, also install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) and set
`TESSDATA_PREFIX` in `.env`.

## Everyday use

1. Put PDFs in `data/inbox/` (sub-folders are fine).
2. Check what it will cost: `lke run --dry-run`
3. Process everything: `lke run`
4. Look at the results:

| Command | What it does |
|---|---|
| `lke open` | **Open the library as a readable page in your browser** (print it to PDF with Ctrl+P) |
| `lke status` | Documents, progress per stage, record counts |
| `lke failures` | Sections that failed and why |
| `lke topics` | Topic → subtopic tree with record counts |
| `lke search "retrenchment notice"` | Keyword search (`--semantic` for meaning-based search, needs `pip install -e ".[search]"`) |
| `lke show <record_id>` | One record as JSON, with its relationships |
| `lke review list` / `show` / `approve` / `reject` | Records flagged for a human decision |
| `lke export` | `library.html`, `records.jsonl`, `relations.jsonl`, `topics.jsonl`, `records.csv` in `data/library/export/` |
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

### Output format

`lke export` (and `lke open`) write `data/library/export/knowledge_records.json`:

```json
{
  "topic": "", "subtopic": "", "content_type": "CASE", "title": "",
  "knowledge": { "case_name": "", "court": "", "year": "", "material_facts": [], "...": "" },
  "related_concepts": [], "related_cases": [],
  "source": { "document_id": "", "original_file": "", "page_start": 0, "page_end": 0 },
  "validation": { "status": "PASS | REGENERATE | HUMAN_REVIEW", "similarity_score": 0.0, "reason": "" }
}
```

`similarity_score` (0–1) is the larger of: the share of the record's 8-word sequences found in
the source, and the similarity of its closest sentence to a source sentence.

### Safeguards

- **No copying:** the record writer never sees the source text. Each record is then compared
  with its section. It is marked REGENERATE if it reproduces 12+ consecutive words of ordinary
  source wording, more than 15 % of its 8-word sequences, or a whole source sentence (≥ 85 %
  similar). It is regenerated **once**; if it is still too similar it goes to HUMAN_REVIEW.
  Case names, parties, courts, statutes, section numbers, dates, defined terms and legal terms
  of art never count as copying, and are never changed to lower the score.
- **No inferences:** only facts stated in the source are kept (`allow_interpretation: false`).
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
With the paid API, set `extract_model` / `compose_model` to `claude-sonnet-5-5` for a lower cost.

## Tests

```powershell
pytest -q
```
The tests use a fake LLM, so they run offline and cost nothing.
