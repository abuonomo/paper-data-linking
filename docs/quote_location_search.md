# Quote Location Search: Algorithm, Files, Diagnostics, and Reproduction

This document describes the current quote-location search algorithm, where the
relevant code and diagnostics live in the repository, and how to repeat the
experiments that produced the current results. The intent is descriptive, not
prescriptive: it documents what exists and how to observe it.

## Overview

The quote-location system attempts to find the on-page PDF coordinates (rects)
for quoted strings. It has two complementary approaches:

- A fast, index-based searcher (`PDFTextSearcher`) that normalizes text across
the entire PDF once and searches quotes against that normalized stream, with
fallbacks and verification.
- Direct MuPDF page search fallbacks (`page.search_for`) used selectively for
layout-sensitive cases (e.g., multi-column pages) and when index-based search
is insufficient.

Cross-page (“ellipsis”) quotes are handled by several boundary-focused methods
that consider content at the end of one page and the start of the next.

## Code Locations

- Core searcher implementation
  - `paper_data_linking/processing/pdf_text_search.py`
    - Builds a normalized text index and mappings back to PDF tokens/rects
    - Implements search strategies and fallbacks (single-page and cross-page)
    - Emits structured debug for each quote when requested

- Legacy annotator (for reference/compatibility)
  - `paper_data_linking/processing/pdf_annotator.py`
    - Uses MuPDF `page.search_for` and page-local fragments

- Experiment and bench scripts
  - `scripts/test_pdf_quote_search.py` — run against a single PDF and a set of quotes
  - `scripts/generate_hard_quotes.py` — generate “hard” quotes per PDF under fixtures
  - `scripts/run_quote_bench.py` — batch evaluation over fixtures with metrics and debug

- Fixtures and outputs
  - Generated hard quotes per PDF: `fixtures/quotes/*.quotes.json`
  - Fixture index: `fixtures/quotes/index.json`
  - Batch debug output (when enabled): `fixtures/quotes/debug/*.debug.json`
  - Example manual cross-page test input: `fixtures/quotes/manual_cross_page_test.json`
  - Example per-run results JSON (from single-run script):
    - e.g., `fixtures/quotes/manual_cross_page_test.results.json`

## Normalization and Index Build (PDFTextSearcher)

- Normalization
  - Unicode NFKD
  - Common punctuation replacements: dashes (−–— → -), quotes (‘ ’ → ', “ ” → "), ellipsis (… → ...)
  - Ligatures: ﬁ, ﬂ, ﬀ, ﬃ, ﬄ → fi, fl, ff, ffi, ffl
  - Remove invisible characters (soft hyphen, zero-width) and collapse whitespace

- Index
  - Extracts page text as spans and lines with `page.get_text("dict")`
  - Builds a concatenated normalized string (`norm_text`) for the document
  - Maintains `char_to_token` mapping for later coordinate reconstruction
  - Records `page_ranges` to map document char index → page
  - Records `page_lines` as a list of normalized lines with their union rects (for boundary windows)
  - Detects dehyphenation joins at line breaks (stores concatenated token pairs)

## Search Strategy (Single Page)

- Exact and space-insensitive matches on the index (`norm_text`)
  - Verify by reconstructing normalized segment via `char_to_token`
  - Score/verify by token order coverage and length ratio

- Punctuation-collapsed regex match on the index
  - Collapses consecutive non-alphanumeric chars to wildcard classes
  - Verifies token order coverage and length ratio; hyphen-join aware relaxation

- Hyphen-join variant probe on the index
  - Replaces token pairs with a joined variant where a known dehyphenation join was detected
  - Verifies token order coverage and length ratio

- Anchor-gapped match on the index
  - Requires 2+ distinctive tokens (“anchors”) in order with bounded char gaps
  - Verifies token order coverage, length ratio, and anchor presence

- MuPDF fallbacks (per page)
  - `page.search_for` on the full normalized quote text (with flags)
  - `page.search_for` on a small set of 4–6 word substrings sampled from the quote
  - Returns one or more rectangles on the matching page

## Cross-Page Strategy (Ellipsis)

- Index-based boundary match
  - Searches ordered parts split by ellipsis across `norm_text` near page boundaries
  - Verifies parts-in-order and reconstructs segment into rects

- Combined boundary line window (multi-line)
  - Builds a combined normalized string from last N lines of page N and first N lines of page N+1
  - Filters header/footer-like lines (e.g., page numbers, emails, arXiv ids)
  - Methods attempted:
    - Parts-in-order substring match in combined window
    - Token-anchor chaining in combined window
  - Maps matched character span back to contributing lines and unions rects per page

- MuPDF-based cross-page chaining
  - For quotes with ellipsis, searches `left_part` via `page.search_for` on page N and `right_part` on N+1
  - Alternative: token-anchor chaining near bottom/top bands using `page.search_for` on distinctive tokens
  - If both sides found, builds a cross-page result from those rects

## Diagnostics (Per-Quote Debug)

When `debug=True`, each quote result includes a `debug` object. Common fields:

- `method`: which method accepted the match (if any), e.g.,
  - `exact_ci`, `punctuation_fallback`, `hyphen_join_variant`, `anchor_gapped`,
  - `ellipsis_chain`, `cross_page_chain`, `cross_page_lines_combined`,
  - `fitz_search`, `fitz_phrase_search`, `fitz_cross_page_chain`, `fitz_anchor_chain`
- `attempt`: last-attempted method when no match was accepted
- `reject_reason`: reason for rejection (e.g., `verification_failed`, `parts_not_found_in_line_windows`, `no_boundary_matches`)
- `coverage_ratio`, `len_ratio`: token-based coverage and segment/quote length ratio used in verification
- `anchors`, `anchors_found`, `anchors_total`: distinctive tokens used for matching and how many were found
- `pattern`, `span`, `segment_norm_preview`: matching pattern or span and segment previews
- `doc`: document-level context (total length, page ranges, hyphen_joins_count)
- Cross-page line windows
  - `cross_page_lines_windows`: raw normalized last/first lines per boundary
  - `cross_page_lines_combined`: combined window length and (when matched) anchors and span

## How to Reproduce Experiments

- Generate hard-quote fixtures (first 10 PDFs)

```bash
python scripts/generate_hard_quotes.py --limit 10 --glob "api/media/papers/*.pdf"
```

- Run the batch bench (summary only)

```bash
python scripts/run_quote_bench.py --limit 10 --out fixtures/quotes/bench_report.json
```

- Run the batch bench with per-PDF debug JSON

```bash
python scripts/run_quote_bench.py --limit 10   --debug   --debug-dir fixtures/quotes/debug   --out fixtures/quotes/bench_report_debug.json
```

- Run a single-PDF, single-quote test (prints summary and writes results JSON)

```bash
python -m scripts.test_pdf_quote_search   --pdf api/media/papers/<pdf-id>.pdf   --quotes fixtures/quotes/<pdf-id>.quotes.json   -v   --out-json fixtures/quotes/<pdf-id>.results.json
```

- Manual example (provided cross-page quote)

```bash
python -m scripts.test_pdf_quote_search   --pdf api/media/papers/0004ad59-0807-45d4-8e68-863a382e8a39.pdf   --quotes fixtures/quotes/manual_cross_page_test.json   -v   --out-json fixtures/quotes/manual_cross_page_test.results.json
```

- Inspect per-PDF debug
  - `fixtures/quotes/debug/<pdf-id>.debug.json`
  - Each file contains per-quote `debug` objects with methods/attempts, reasons, and boundary windows.

## Current Observations (from experiments)

- Single-page, multi-column content
  - `page.search_for`-based fallbacks return rectangles in the correct column
  - Normalization differences (e.g., punctuation spacing) are handled via flags and token-order verification

- Cross-page content (“ellipsis”)
  - Boundary contexts often include header/footer lines (e.g., page numbers, emails, arXiv ids)
  - Left/right parts may span multiple lines; strict single-line containment fails
  - Normalization sometimes yields spaced punctuation (e.g., “( 2017 )” vs “(2017)”) which affects substring matches
  - Combined windows and token anchors provide additional diagnostics and context

## Files to Inspect

- Implementation and search methods
  - `paper_data_linking/processing/pdf_text_search.py`

- Batch bench and outputs
  - `scripts/run_quote_bench.py`
  - `fixtures/quotes/index.json`
  - `fixtures/quotes/*.quotes.json`
  - `fixtures/quotes/bench_report.json`
  - `fixtures/quotes/debug/*.debug.json`

- Single-run outputs
  - `scripts/test_pdf_quote_search.py`
  - Per-run results JSON: e.g., `fixtures/quotes/<id>.results.json`

## Notes

- This document describes the current algorithm and diagnostics, and how to
observe their behavior on real PDFs and quotes. It aims to enable reproduction
and independent assessment using the provided scripts and outputs.
