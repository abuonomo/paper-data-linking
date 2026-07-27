"""Deliberately run phenomena over a chosen paper set.

Phenomena never run in the standard chain (extraction was ~20% of downstream
LLM calls, largely spent on ungrounded/out-of-scope instruments, and the
subsystem is less hardened than the DU path). This command is the intentional
entry point: per paper it extracts phenomena over the stored normalized
periods (idempotent — already-extracted periods are skipped), merges them into
normalized_instrument_details, and upserts PhenomenonMentions for the
validation UI.

Usage:
  python manage.py run_phenomena_enrichment --config bedrock-120b-mixed-v5@c10k
  python manage.py run_phenomena_enrichment --config X --only-grounded
  python manage.py run_phenomena_enrichment --config X --papers id1 id2 --sync
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run phenomena extraction + mention upsert over a config's papers (intentional-only)"

    def add_arguments(self, parser):
        parser.add_argument("--config", required=True, help="configuration_name to enrich")
        parser.add_argument("--papers", nargs="*", default=None, help="restrict to these paper ids")
        parser.add_argument("--only-grounded", action="store_true",
                            help="only papers with >=1 grounded instrument (skips the out-of-scope tail)")
        parser.add_argument("--sync", action="store_true",
                            help="run inline instead of dispatching to the cpu queue")

    def handle(self, *args, **opts):
        from vso_query_builder.tasks import (
            run_phenomena_enrichment, submit_batch_phenomena_enrichment)

        if opts["sync"]:
            from vso_query_builder.models import PaperAnalysis
            qs = PaperAnalysis.objects.filter(
                configuration_name=opts["config"],
                normalized_instrument_details__isnull=False)
            if opts["papers"]:
                qs = qs.filter(paper_id__in=opts["papers"])
            done = 0
            for pa_id in qs.values_list("id", flat=True).iterator(chunk_size=500):
                res = run_phenomena_enrichment.run(pa_id)
                done += 1
                self.stdout.write(f"{pa_id}: {res}")
            self.stdout.write(self.style.SUCCESS(f"enriched {done} papers inline"))
            return

        res = submit_batch_phenomena_enrichment.delay(
            opts["config"], paper_ids=opts["papers"], only_grounded=opts["only_grounded"])
        self.stdout.write(self.style.SUCCESS(
            f"Dispatched submit_batch_phenomena_enrichment ({res.id}); "
            "watch the celery-cpu worker / Flower for progress."))
