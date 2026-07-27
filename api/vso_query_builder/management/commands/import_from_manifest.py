"""Import papers from a bibcode_collection JSONL manifest.

PDFs are expected to already be in S3 (uploaded by pdf_downloader with --s3-bucket).
This command creates Paper records pointing to those S3 keys without transferring files.
"""

import json

from django.core.management.base import BaseCommand

from ...models import Paper


def _sanitize_bibcode(bibcode: str) -> str:
    """Match the sanitization used by pdf_downloader."""
    return bibcode.replace("&", "_").replace("/", "_")


def _list_s3_keys(bucket, prefix):
    """List all keys under prefix in one paginated pass."""
    import boto3
    import botocore.session

    # Use IAM role, skip env vars (same as IAMRoleS3Storage)
    bc_session = botocore.session.Session()
    bc_session.get_component("credential_provider").remove("env")
    session = boto3.Session(botocore_session=bc_session)
    s3 = session.client("s3")

    keys = set()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix + "/"):
        for obj in page.get("Contents", []):
            keys.add(obj["Key"])
    return keys


class Command(BaseCommand):
    help = "Import papers from a bibcode_collection manifest (PDFs already in S3)"

    def add_arguments(self, parser):
        parser.add_argument("manifest", help="JSONL manifest file path")
        parser.add_argument(
            "--s3-prefix", default="papers",
            help="S3 key prefix where PDFs were uploaded (default: papers)",
        )
        parser.add_argument(
            "--verify-s3", action="store_true",
            help="List S3 keys and only import bibcodes whose PDF exists",
        )
        parser.add_argument(
            "--auto-tag", action="store_true",
            help="Set paper tags from manifest 'sources' field",
        )
        parser.add_argument(
            "--tags", nargs="*", default=[],
            help="Additional tags to apply to all imported papers",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview what would be imported without creating records",
        )

    def handle(self, *args, **options):
        manifest_path = options["manifest"]
        s3_prefix = options["s3_prefix"]
        extra_tags = set(options["tags"])
        auto_tag = options["auto_tag"]
        dry_run = options["dry_run"]
        verify_s3 = options["verify_s3"]

        records = []
        with open(manifest_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        # Only import records that have a downloadable PDF
        importable = [r for r in records if r.get("pdf_url") or r.get("arxiv_id")]

        # Optionally verify against actual S3 contents
        s3_keys = None
        if verify_s3:
            from django.conf import settings
            bucket = settings.AWS_STORAGE_BUCKET_NAME
            self.stdout.write(f"Listing s3://{bucket}/{s3_prefix}/...")
            s3_keys = _list_s3_keys(bucket, s3_prefix)
            self.stdout.write(f"  Found {len(s3_keys):,} objects in S3")

        created = 0
        skipped = 0
        no_s3 = 0

        for record in importable:
            bibcode = record["bibcode"]
            s3_key = f"{s3_prefix}/{_sanitize_bibcode(bibcode)}.pdf"

            if s3_keys is not None and s3_key not in s3_keys:
                no_s3 += 1
                continue

            if Paper.objects.filter(bibcode=bibcode).exists():
                skipped += 1
                continue

            # Build tags
            tags = list(extra_tags)
            if auto_tag:
                tags.append("helio")
                tags.extend(record.get("sources", []))
            tags = sorted(set(tags))

            if dry_run:
                self.stdout.write(f"  Would create: {bibcode} -> {s3_key}  tags={tags}")
                created += 1
                continue

            paper = Paper(bibcode=bibcode, tags=tags)
            paper.pdf.name = s3_key  # Point to existing S3 object
            paper.save()
            created += 1

        action = "Would create" if dry_run else "Created"
        msg = (
            f"{action} {created} papers, skipped {skipped} existing"
            f" (out of {len(importable)} importable / {len(records)} total records)"
        )
        if s3_keys is not None:
            msg += f", {no_s3} skipped (not in S3)"
        self.stdout.write(self.style.SUCCESS(msg))
