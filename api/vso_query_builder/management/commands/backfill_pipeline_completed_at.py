"""
Backfill PaperAnalysis.pipeline_completed_at for analyses that completed
before this field was introduced.

An analysis is considered "pipeline done" if it has no pipeline nodes in
'running' state AND at least one node exists in a terminal state, or it
has normalized_instrument_details set (meaning grounding/normalization ran).

pipeline_completed_at is set to the latest completed_at across all its
pipeline nodes, falling back to the analysis's updated_at if no nodes exist.

Usage:
    python manage.py backfill_pipeline_completed_at
    python manage.py backfill_pipeline_completed_at --dry-run
"""
from django.core.management.base import BaseCommand
from django.db.models import Max
from django.utils import timezone


class Command(BaseCommand):
    help = 'Backfill pipeline_completed_at on analyses that completed before the field existed'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be updated without making changes',
        )

    def handle(self, *args, **options):
        from vso_query_builder.models import PaperAnalysis, PipelineNode

        dry_run = options['dry_run']

        # Find analyses with no pipeline_completed_at set
        candidates = PaperAnalysis.objects.filter(pipeline_completed_at__isnull=True)
        self.stdout.write(f'Found {candidates.count()} analyses without pipeline_completed_at')

        updated = 0
        skipped_running = 0
        skipped_no_signal = 0

        for pa in candidates.iterator():
            nodes = PipelineNode.objects.filter(analysis=pa)

            # Skip if any node is still running — pipeline not done
            if nodes.filter(status='running').exists():
                skipped_running += 1
                continue

            # Determine completion timestamp from latest terminal node
            latest_completed = nodes.filter(
                completed_at__isnull=False
            ).aggregate(Max('completed_at'))['completed_at__max']

            # Determine if pipeline is done:
            # - has terminal nodes (completed/failed/skipped), OR
            # - has normalized data (grounding/normalization ran without node tracking)
            has_terminal_nodes = nodes.filter(status__in=['completed', 'failed', 'skipped']).exists()
            has_normalized = bool(pa.normalized_instrument_details)

            if not has_terminal_nodes and not has_normalized:
                skipped_no_signal += 1
                continue

            # Use latest node completion time, or fall back to now
            completed_at = latest_completed or timezone.now()

            if dry_run:
                self.stdout.write(
                    f'  [dry-run] Would set analysis {pa.id} ({pa.paper.bibcode}) '
                    f'pipeline_completed_at={completed_at}'
                )
            else:
                PaperAnalysis.objects.filter(id=pa.id).update(
                    pipeline_completed_at=completed_at
                )

            updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'\n{"[dry-run] Would update" if dry_run else "Updated"} {updated} analyses'
        ))
        self.stdout.write(f'Skipped {skipped_running} with running nodes')
        self.stdout.write(f'Skipped {skipped_no_signal} with no completion signal')
