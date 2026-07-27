"""
Management command to clean up duplicate quotes on DatasetUsage records.

Background:
- A bug in the old normalized workflow linked DatasetUsages to 100+ quotes because:
  1. `icontains` string matching was too broad (e.g., "IMPACT" matched all sub-instruments)
  2. No period filtering — all quotes were linked to every DatasetUsage indiscriminately
- The fix was committed in 9f5493a (Jan 16 2026): quotes are now created inline during
  `_upsert_dataset_usages_from_normalized`, pulled directly from normalized JSON.
- This command cleans up existing production data by deleting the over-associated quotes
  and re-inserting via `insert_datasetusages_only` (no LLM calls — uses existing JSON).

Usage:
    python manage.py rebuild_normalized_quotes --dry-run
    python manage.py rebuild_normalized_quotes --dry-run --configuration-name default
    python manage.py rebuild_normalized_quotes --configuration-name default
    python manage.py rebuild_normalized_quotes
"""
from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Max, Min

from vso_query_builder.models import DatasetUsage, PaperAnalysis
from vso_query_builder.tasks import insert_datasetusages_only


class Command(BaseCommand):
    help = "Delete over-associated normalized quotes/usages and re-insert from existing normalized JSON"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be changed without making any changes",
        )
        parser.add_argument(
            "--configuration-name",
            type=str,
            default=None,
            help="Only process PaperAnalysis records with this configuration_name",
        )
        parser.add_argument(
            "--paper-analysis-id",
            type=int,
            default=None,
            help="Only process a single PaperAnalysis by ID (for testing)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Progress reporting batch size (default: 100)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        configuration_name = options["configuration_name"]
        paper_analysis_id = options["paper_analysis_id"]
        batch_size = options["batch_size"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE — no changes will be made"))

        # Query PaperAnalysis records that:
        # 1. Have normalized_instrument_details (required for re-insert)
        # 2. Have at least one DatasetUsage linked to them
        qs = PaperAnalysis.objects.filter(
            normalized_instrument_details__isnull=False,
            dataset_usages__isnull=False,
        ).distinct()

        if paper_analysis_id:
            qs = qs.filter(id=paper_analysis_id)
        if configuration_name:
            qs = qs.filter(configuration_name=configuration_name)

        total_pa = qs.count()

        if total_pa == 0:
            self.stdout.write(self.style.SUCCESS("No matching PaperAnalysis records found. Nothing to do."))
            return

        self.stdout.write(f"Found {total_pa} PaperAnalysis records to process")
        if configuration_name:
            self.stdout.write(f"  (filtered to configuration_name='{configuration_name}')")

        # Gather stats
        total_quotes = sum(pa.support_quotes.count() for pa in qs)
        total_usages = DatasetUsage.objects.filter(paper_analysis__in=qs).count()

        usage_quote_counts = (
            DatasetUsage.objects.filter(paper_analysis__in=qs)
            .annotate(quote_count=Count("supporting_quotes"))
            .aggregate(
                min_quotes=Min("quote_count"),
                max_quotes=Max("quote_count"),
                avg_quotes=Avg("quote_count"),
            )
        )

        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write("IMPACT SUMMARY")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  PaperAnalysis records:        {total_pa}")
        self.stdout.write(f"  SupportQuotes to delete:      {total_quotes}")
        self.stdout.write(f"  DatasetUsages (kept, no delete): {total_usages}")
        if usage_quote_counts["min_quotes"] is not None:
            self.stdout.write(
                f"  Quotes per usage — "
                f"min: {usage_quote_counts['min_quotes']}, "
                f"max: {usage_quote_counts['max_quotes']}, "
                f"avg: {usage_quote_counts['avg_quotes']:.1f}"
            )
        self.stdout.write("=" * 60)

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN complete. Run without --dry-run to apply changes."))
            return

        # Execute the cleanup
        quotes_deleted = 0
        tasks_enqueued = 0
        skipped = 0

        pa_list = list(qs)
        total = len(pa_list)

        for i, pa in enumerate(pa_list, 1):
            if i % batch_size == 0 or i == total:
                self.stdout.write(f"  Processing {i}/{total}...")

            if not pa.normalized_instrument_details:
                self.stdout.write(
                    self.style.WARNING(f"  Skipping pa.id={pa.id} — no normalized_instrument_details")
                )
                skipped += 1
                continue

            # Delete all support quotes for this PaperAnalysis.
            # DatasetUsage records are kept — _upsert_dataset_usages_from_normalized uses
            # get_or_create so existing usages won't be duplicated; it will just re-link quotes.
            pa_quotes = pa.support_quotes.count()
            if pa_quotes:
                pa.support_quotes.all().delete()
                quotes_deleted += pa_quotes

            # Enqueue Celery task to re-link quotes from existing normalized JSON
            insert_datasetusages_only.delay(pa.id)
            tasks_enqueued += 1

        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write("DONE")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  SupportQuotes deleted:  {quotes_deleted}")
        self.stdout.write(f"  Celery tasks enqueued:  {tasks_enqueued}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"  Skipped (no normalized JSON): {skipped}"))
        self.stdout.write("")
        self.stdout.write("Re-linking is asynchronous. Monitor Celery workers for completion.")
