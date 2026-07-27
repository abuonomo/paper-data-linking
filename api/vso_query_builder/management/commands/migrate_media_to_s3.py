"""
Management command to migrate existing media files from local filesystem to S3.

Usage:
    python manage.py migrate_media_to_s3 --dry-run     # Preview what would be uploaded
    python manage.py migrate_media_to_s3               # Actually upload files
"""

import boto3
from django.conf import settings
from django.core.management.base import BaseCommand
from tqdm import tqdm

from vso_query_builder.models import Paper, PaperAnalysis


class Command(BaseCommand):
    help = 'Migrate existing media files (PDFs) from local filesystem to S3'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview what would be uploaded without actually uploading',
        )
        parser.add_argument(
            '--bucket',
            type=str,
            default=None,
            help='S3 bucket name (defaults to AWS_STORAGE_BUCKET_NAME setting)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        bucket_name = options['bucket'] or getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None)

        if not bucket_name:
            self.stderr.write(self.style.ERROR(
                'No bucket specified. Set AWS_STORAGE_BUCKET_NAME or use --bucket.'
            ))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(f'DRY RUN - no files will be uploaded'))
        self.stdout.write(f'Target bucket: {bucket_name}')

        s3_client = boto3.client('s3')

        # Collect all file fields to migrate
        file_records = []

        # Paper PDFs
        papers_with_pdf = Paper.objects.exclude(pdf='').exclude(pdf__isnull=True)
        for paper in papers_with_pdf:
            file_records.append(('Paper', paper.bibcode, paper.pdf))

        # PaperAnalysis annotated PDFs
        analyses_with_pdf = PaperAnalysis.objects.exclude(
            annotated_pdf=''
        ).exclude(
            annotated_pdf__isnull=True
        ).select_related('paper')
        for analysis in analyses_with_pdf:
            file_records.append(('PaperAnalysis', analysis.paper.bibcode, analysis.annotated_pdf))

        self.stdout.write(f'Found {len(file_records)} files to migrate')

        uploaded = 0
        skipped = 0
        errors = 0

        for model_name, bibcode, file_field in tqdm(file_records, desc='Migrating'):
            s3_key = file_field.name  # e.g. "papers/uuid.pdf"

            if dry_run:
                try:
                    local_path = file_field.path
                    import os
                    size_mb = os.path.getsize(local_path) / 1024 / 1024
                    self.stdout.write(f'  Would upload: {s3_key} ({size_mb:.1f} MB) [{model_name}: {bibcode}]')
                    uploaded += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'  Missing locally: {s3_key} [{model_name}: {bibcode}] - {e}'))
                    skipped += 1
                continue

            try:
                # Check if already exists in S3
                try:
                    s3_client.head_object(Bucket=bucket_name, Key=s3_key)
                    skipped += 1
                    continue
                except s3_client.exceptions.ClientError:
                    pass  # Not found, proceed with upload

                # Read from local storage and upload to S3
                file_field.open('rb')
                try:
                    s3_client.upload_fileobj(
                        file_field,
                        bucket_name,
                        s3_key,
                        ExtraArgs={'ContentType': 'application/pdf'},
                    )
                    uploaded += 1
                finally:
                    file_field.close()

            except Exception as e:
                self.stderr.write(self.style.ERROR(
                    f'  Error uploading {s3_key} [{model_name}: {bibcode}]: {e}'
                ))
                errors += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Uploaded: {uploaded}'))
        self.stdout.write(f'Skipped (already in S3): {skipped}')
        if errors:
            self.stdout.write(self.style.ERROR(f'Errors: {errors}'))
