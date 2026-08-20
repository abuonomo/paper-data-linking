# Public API Guide

Base URL:

```text
https://paper-data.helioanalytics.io
```

The public API is read-only and does not require authentication. All endpoints
are `GET` and live under `/builder/public/`. The examples below were tested
against production on 2026-08-20.

A note on validation: dataset usage records are extracted automatically by an
LLM pipeline and then human-reviewed. By default the API returns only
**approved** (human-validated) records. Most records in the corpus are still
`pending` review, so for coverage-oriented use cases (e.g. citation metrics)
you will usually want `include_unvalidated=true`, which returns approved
**plus** pending records, and should treat `validation_status` as a confidence
signal.

## 1. Does This Paper Use A Dataset? (bibcode → usages)

```text
GET /builder/public/papers/{bibcode}/validated-usages/
```

Example:

```bash
curl 'https://paper-data.helioanalytics.io/builder/public/papers/2023ApJ...952L..13G/validated-usages/'
```

The response contains the paper and its dataset usage records:

```json
{
  "paper": {
    "id": "5cd5c3ca-2f6b-490a-996f-c96b00fe7ba8",
    "bibcode": "2023ApJ...952L..13G",
    "title": "What Do Halo CMEs Tell Us about Solar Cycle 25?",
    "authors": ["Gopalswamy, Nat", "Michalek, Grzegorz"],
    "year": "2023",
    "journal": "The Astrophysical Journal",
    "journal_abbrev": "ApJL"
  },
  "usages": [
    {
      "id": "0929e5f4-0784-40d3-b7fe-e85f8c8913d1",
      "instrument": {
        "short_name": "spase://SMWG/Instrument/OMNI",
        "display_name": "OMNI",
        "full_name": "OMNI"
      },
      "observatory": {
        "short_name": "spase://SMWG/Observatory/OMNI",
        "display_name": "OMNI",
        "name": "OMNI"
      },
      "datasource": {
        "slug": "cdaweb",
        "name": "Coordinated Data Analysis Web"
      },
      "start_time": "1996-08-01T00:00:00+00:00",
      "end_time": "1999-08-31T23:59:59+00:00",
      "duration_hours": 27024.0,
      "validation_status": "approved",
      "supporting_quotes": [
        {
          "quote": "The solar wind parameters averaged over the first 37 months in each cycle are also shown on the plots.",
          "page_number": 7,
          "support_category": "time_range"
        }
      ]
    }
  ],
  "mission_mentions": [
    {
      "id": "f4179ea2-3d73-4834-962f-65fdc1a465a2",
      "match_level": "mission_only",
      "observatory": {
        "short_name": "spase://SMWG/Observatory/SOHO",
        "display_name": "SOHO",
        "name": "Solar and Heliospheric Observatory",
        "datasource": {
          "slug": "cdaweb",
          "name": "Coordinated Data Analysis Web"
        }
      },
      "instrument": null,
      "created_at": "2026-03-06T20:48:39.495773Z"
    }
  ],
  "mission_mentions_count": 8
}
```

Important fields:

- `usages[]`: concrete dataset usage records — an instrument/observatory plus
  an inferred observation time window, with supporting quotes from the paper
  text as evidence. This is the "the paper analyzed data from X" signal.
- `mission_mentions[]`: mission or instrument mentions that did **not** become
  a full dataset usage record (e.g. the mission is discussed but no concrete
  data analysis was grounded). This is the "the paper merely mentions X" signal.
- `usages[].datasource`: source system, such as `vso` or `cdaweb`.
- `usages[].start_time` / `end_time`: inferred observation window.
- `usages[].validation_status`: `approved` (human-validated) or `pending`.

Query parameters:

- `include_unvalidated=true`: include pending records in addition to approved
  records (default is approved only).
- `include=abstract`: include the paper abstract in the `paper` object.

```bash
curl 'https://paper-data.helioanalytics.io/builder/public/papers/2023ApJ...952L..13G/validated-usages/?include_unvalidated=true'
```

## 2. What Did The Pipeline See In This Paper? (bibcode → all mentions)

```text
GET /builder/public/papers/{bibcode}/instrument-mentions/
```

Returns **every** instrument grounding attempt for the paper, including
partial matches that never became a dataset usage. Useful when you care about
the full mention-vs-usage spectrum.

```bash
curl 'https://paper-data.helioanalytics.io/builder/public/papers/2023ApJ...952L..13G/instrument-mentions/'
```

Query parameters:

- `match_level=mission_only,instrument_no_time,partial,full,unmatched`:
  comma-separated filter; defaults to all levels.

Match levels, roughly from weakest to strongest: `mission_only` (mission
mentioned, no instrument grounded), `instrument_no_time` (instrument grounded
but no time window), `partial`, `full` (became a complete dataset usage),
`unmatched` (extracted but could not be grounded to the catalog).

## 3. Which Papers Use A Mission Or Instrument? (filters → papers)

```text
GET /builder/public/papers/validated/
```

Example — mission plus instrument plus time range:

```bash
curl 'https://paper-data.helioanalytics.io/builder/public/papers/validated/?missions=SOHO&instruments=LASCO&start_date=2020-01-01&end_date=2023-12-31&page_size=3&include=1'
```

The time filter returns papers whose dataset usage observation window overlaps
the requested range.

> **Known limitation:** filtering by `instruments=` without a `start_date`/
> `end_date` currently times out (HTTP 504) at the current corpus size —
> always include a date range when filtering by instrument. Mission-only
> queries work without dates. Tracked in
> [issue #11](https://github.com/abuonomo/paper-data-linking/issues/11).

The response is paginated:

```json
{
  "count": 14,
  "next": "https://paper-data.helioanalytics.io/builder/public/papers/validated/?...&page=2",
  "previous": null,
  "results": [
    {
      "id": "5cd5c3ca-2f6b-490a-996f-c96b00fe7ba8",
      "bibcode": "2023ApJ...952L..13G",
      "validated_count": 0,
      "total_count": 0,
      "mission_only_match_count": 0,
      "has_matching_dataset_usage": false,
      "latest_end": "2022-12-31T23:59:59Z",
      "title": "What Do Halo CMEs Tell Us about Solar Cycle 25?",
      "authors": ["Gopalswamy, Nat", "Michalek, Grzegorz"],
      "year": "2023",
      "journal": "The Astrophysical Journal"
    }
  ]
}
```

Important fields:

- `bibcode`: use this to fetch the paper's dataset usages (section 1).
- `has_matching_dataset_usage`: `true` means the filter matched a concrete
  dataset usage record.
- `mission_only_match_count`: nonzero means the paper mentions the mission but
  may not have a concrete instrument/time-window usage for that match.
- `title`, `authors`, `year`, `journal`: included when `include=1` is present.
- `next`: URL for the next page of results.

Query parameters:

- `missions=SOHO`: filter by mission or observatory short name. Repeatable.
  Also accepts datasource-qualified keys such as `missions=vso:SOHO`.
- `instruments=LASCO`: filter by instrument short name. Repeatable. Combine
  with a date range (see limitation above).
- `start_date=2020-01-01` / `end_date=2023-12-31`: require overlap with the
  usage observation window.
- `validation_status=approved`: filter by validation state. Repeatable.
- `q=halo`: text search over bibcode and title.
- `include=1`: include paper metadata.
- `include_unvalidated=true`: include pending records in addition to approved.
- `page_size=100`, `page=2`: pagination.

Valid `missions`/`instruments` values (with per-mission paper and usage
counts) are discoverable from:

```text
GET /builder/public/papers/filter-options/
```

## 4. Bulk Export

CSV of matching papers (same filter parameters as section 3):

```bash
curl 'https://paper-data.helioanalytics.io/builder/public/papers/csv/?missions=SOHO&start_date=2020-01-01&end_date=2023-12-31'
```

Returns `Bibcode, URL` rows, where each URL is a human-readable public page
for the paper's usages.

## 5. Other Endpoints

- `GET /builder/public/papers/{bibcode}/similar/` — up to 10 similar papers by
  embedding similarity over supporting quotes, with scores and missions.
- `GET /builder/public/papers/{bibcode}/pdf/` — `{pdf_url, bibcode, has_pdf}`;
  `pdf_url` is a time-limited presigned link, so fetch it on demand rather
  than storing it.

## URL-Encoding Bibcodes

Bibcodes can contain characters such as `&`, so encode them when building URLs
in code.

Python:

```python
from urllib.parse import quote

bibcode = "2011A&A...525A..27P"
url = f"https://paper-data.helioanalytics.io/builder/public/papers/{quote(bibcode, safe='')}/validated-usages/"
```

JavaScript:

```js
const bibcode = "2011A&A...525A..27P";
const url = `https://paper-data.helioanalytics.io/builder/public/papers/${encodeURIComponent(bibcode)}/validated-usages/`;
```
