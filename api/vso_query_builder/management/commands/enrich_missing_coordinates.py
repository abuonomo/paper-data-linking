"""Bulk-enrich review-UI PDF coordinates for SupportQuotes left absent by
corpus-mode commits (coordinate_regions == []).

The scriptable "ahead of time" entry point for the coordinate sweep — the
coordinate counterpart to embedding's beat-scheduled `embed_missing_quotes`,
but triggered explicitly (coordinates are wanted only for papers a human will
review, so they are never auto-swept corpus-wide).

By default it dispatches the fan-out driver to the celery `cpu` fleet and
returns immediately. `--sync` runs every paper inline in this process (no
workers needed) — handy for local/E2E validation against the fixture DB.

    # dispatch across the cpu fleet (one task per paper):
    uv run python api/manage.py enrich_missing_coordinates --config bedrock-120b-mixed-v5@fake3
    # run inline, no celery workers:
    uv run python api/manage.py enrich_missing_coordinates --config ... --sync
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from vso_query_builder.models import SupportQuote
from vso_query_builder.tasks import (
    submit_batch_enrich_coordinates, enrich_quote_coordinates,
)


class Command(BaseCommand):
    help = "Bulk-enrich absent SupportQuote coordinates (coordinate_regions=[])."

    def add_arguments(self, parser):
        parser.add_argument('--config', type=str, default=None,
                            help='Filter by paper_analysis.configuration_name')
        parser.add_argument('--sync', action='store_true',
                            help='Run inline in this process instead of dispatching to celery')

    def handle(self, *args, **opts):
        config = opts['config']
        if not opts['sync']:
            res = submit_batch_enrich_coordinates.delay(configuration_name=config)
            self.stdout.write(self.style.SUCCESS(
                f"Dispatched submit_batch_enrich_coordinates (task {res.id}, config={config}). "
                f"Watch the celery-cpu worker / Flower for progress."))
            return

        # --sync: resolve the distinct papers here and run each task inline.
        sq = SupportQuote.objects.filter(coordinate_regions=[]).exclude(quote='')
        if config:
            sq = sq.filter(paper_analysis__configuration_name=config)
        sq = sq.filter(paper_analysis__paper__used_ocr=False).exclude(
            Q(paper_analysis__paper__pdf='') | Q(paper_analysis__paper__pdf__isnull=True))
        pids = list(sq.values_list('paper_analysis__paper_id', flat=True).distinct())

        self.stdout.write(f"Enriching {len(pids)} papers inline (config={config}) ...")
        total_cand = total_enriched = 0
        for pid in pids:
            r = enrich_quote_coordinates.run(str(pid))
            total_cand += r.get('candidates', 0)
            total_enriched += r.get('enriched', 0)
        self.stdout.write(self.style.SUCCESS(
            f"Done: {total_enriched}/{total_cand} quotes located across {len(pids)} papers."))
