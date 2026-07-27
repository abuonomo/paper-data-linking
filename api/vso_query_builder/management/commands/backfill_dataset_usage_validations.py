"""
Backfill DatasetUsageValidation records from legacy DatasetUsage.validated_by field.

For every DatasetUsage that has a validated_by user and a non-pending validation_status,
create a corresponding DatasetUsageValidation record if one doesn't already exist.
"""
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Backfill DatasetUsageValidation records from legacy validated_by field"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without writing to the database',
        )

    def handle(self, *args, **options):
        from vso_query_builder.models import DatasetUsage, DatasetUsageValidation

        dry_run = options['dry_run']

        qs = (
            DatasetUsage.objects
            .filter(validated_by__isnull=False)
            .exclude(validation_status='pending')
            .select_related('validated_by')
        )

        total = qs.count()
        self.stdout.write(f"Found {total} DatasetUsage records with a validated_by user.")

        created = 0
        skipped = 0

        for usage in qs.iterator():
            already_exists = DatasetUsageValidation.objects.filter(
                dataset_usage=usage,
                user=usage.validated_by,
            ).exists()

            if already_exists:
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(
                    f"  [dry-run] Would create: usage={usage.id} "
                    f"user={usage.validated_by.username} "
                    f"status={usage.validation_status}"
                )
                created += 1
            else:
                with transaction.atomic():
                    DatasetUsageValidation.objects.create(
                        dataset_usage=usage,
                        user=usage.validated_by,
                        validation_status=usage.validation_status,
                        validation_notes=usage.validation_notes or '',
                        # Use validated_at as created_at isn't settable (auto_now_add),
                        # but the record will reflect the correct status.
                    )
                created += 1

        suffix = ' (dry run)' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f"Done{suffix}: {created} created, {skipped} already existed."
        ))
