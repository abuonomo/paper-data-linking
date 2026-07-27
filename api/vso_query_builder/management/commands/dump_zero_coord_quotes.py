"""Export zero-coordinate SupportQuotes as offline bench fixtures.

Read-only. Bridges the replay DB (the absent-coordinate population the bulk
enrichment targets) to the offline `experiments/quote_search_bench` harness:
for every paper that has a local PDF and at least one quote with
`coordinate_regions == []`, write a per-paper quotes JSON and an aggregate
`index.json` of {pdf, quotes_file} pairs the runner consumes.

Only papers whose PDF actually exists on local disk are emitted (the harness
runs offline against `api/media/`), so a subset of the DB is expected.

Usage (pointed at the replay DB on the host):

    DB_NAME=paper_analyzer_db_replay DB_HOST=localhost DB_PORT=5436 \
      uv run python api/manage.py dump_zero_coord_quotes \
        --config bedrock-120b-mixed-v5@fake3 --out-dir experiments/quote_search_bench/fixtures/quotes
"""

import json
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from vso_query_builder.models import SupportQuote


class Command(BaseCommand):
    help = "Export zero-coordinate SupportQuotes (with a local PDF) as offline bench fixtures."

    def add_arguments(self, parser):
        parser.add_argument("--config", type=str, default=None,
                            help="Filter by paper_analysis.configuration_name")
        parser.add_argument("--limit", type=int, default=None,
                            help="Cap the number of papers emitted")
        parser.add_argument("--out-dir", type=Path,
                            default=Path("experiments/quote_search_bench/fixtures/quotes"),
                            help="Directory to write per-paper quote JSONs + index.json")
        parser.add_argument("--include-ocr", action="store_true",
                            help="Include papers flagged used_ocr (excluded by default, "
                                 "matching the enrichment task's OCR skip)")

    def handle(self, *args, **opts):
        qs = SupportQuote.objects.filter(coordinate_regions=[]).exclude(quote="")
        if opts["config"]:
            qs = qs.filter(paper_analysis__configuration_name=opts["config"])
        qs = qs.filter(paper_analysis__paper__pdf__isnull=False).exclude(
            paper_analysis__paper__pdf="")
        if not opts["include_ocr"]:
            qs = qs.exclude(paper_analysis__paper__used_ocr=True)

        qs = qs.select_related("paper_analysis__paper").order_by(
            "paper_analysis__paper_id", "id")

        # Group quotes by paper; dedupe identical (quote, instrument, parameter)
        # triples so a paper with the same quote across analyses isn't double-counted.
        by_paper = defaultdict(lambda: {"paper": None, "seen": set(), "quotes": []})
        for sq in qs.iterator():
            paper = sq.paper_analysis.paper
            bucket = by_paper[paper.id]
            bucket["paper"] = paper
            key = (sq.quote, sq.instrument, sq.parameter)
            if key in bucket["seen"]:
                continue
            bucket["seen"].add(key)
            bucket["quotes"].append({
                "quote": sq.quote,
                "instrument": sq.instrument,
                "parameter": sq.parameter,
                "expected": True,
            })

        media_root = Path(settings.MEDIA_ROOT)
        out_dir = opts["out_dir"].resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        index = []
        emitted = missing = 0
        for paper_id, bucket in by_paper.items():
            paper = bucket["paper"]
            pdf_path = (media_root / paper.pdf.name).resolve()
            if not pdf_path.exists():
                missing += 1
                continue
            quotes_file = out_dir / f"{paper_id}.quotes.json"
            quotes_file.write_text(json.dumps(bucket["quotes"], indent=2, ensure_ascii=False),
                                   encoding="utf-8")
            index.append({
                "pdf": str(pdf_path),
                "quotes_file": str(quotes_file),
                "bibcode": paper.bibcode,
                "count": len(bucket["quotes"]),
            })
            emitted += 1
            if opts["limit"] and emitted >= opts["limit"]:
                break

        index_path = out_dir / "index.json"
        index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

        total_quotes = sum(e["count"] for e in index)
        self.stdout.write(self.style.SUCCESS(
            f"Wrote {emitted} papers ({total_quotes} quotes) -> {index_path}"))
        if missing:
            self.stdout.write(self.style.WARNING(
                f"Skipped {missing} papers whose PDF was not found under {media_root}"))
