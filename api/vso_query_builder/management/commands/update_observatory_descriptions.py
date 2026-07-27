"""
Load observatory descriptions from a JSON file into the database.

Reads a JSON file keyed by Observatory.short_name and updates the
Observatory.description field for matching records.

Usage:
    docker compose exec api python manage.py update_observatory_descriptions descriptions.json
    docker compose exec api python manage.py update_observatory_descriptions descriptions.json --dry-run
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from ...models import Observatory


class Command(BaseCommand):
    help = "Load observatory descriptions from a JSON file into Observatory.description."

    def add_arguments(self, parser):
        parser.add_argument(
            "json_file",
            type=str,
            help="Path to JSON file mapping Observatory.short_name to description string.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Show what would be updated without writing to the database.",
        )

    def handle(self, *args, **options):
        json_path = Path(options["json_file"])
        dry_run = options["dry_run"]

        if not json_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {json_path}"))
            return

        descriptions = json.loads(json_path.read_text())
        self.stdout.write(f"Loaded {len(descriptions)} descriptions from {json_path}")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be written."))

        # Match by short_name (case-insensitive since SPASE URIs may vary in case)
        all_obs = Observatory.objects.all()
        obs_by_short = {obs.short_name: obs for obs in all_obs}
        # Also build case-insensitive lookup
        obs_by_short_lower = {obs.short_name.lower(): obs for obs in all_obs}

        to_update = []
        matched = 0
        unmatched = 0

        for short_name, desc in descriptions.items():
            obs = obs_by_short.get(short_name) or obs_by_short_lower.get(short_name.lower())
            if obs:
                if obs.description != desc:
                    obs.description = desc
                    to_update.append(obs)
                matched += 1
            else:
                unmatched += 1

        self.stdout.write(f"  Matched: {matched}")
        self.stdout.write(f"  Unmatched: {unmatched}")
        self.stdout.write(f"  Changed: {len(to_update)}")

        if dry_run:
            for obs in to_update[:5]:
                self.stdout.write(f"  [DRY] {obs.short_name}: {obs.description[:80]}")
        elif to_update:
            Observatory.objects.bulk_update(to_update, ["description"], batch_size=200)
            self.stdout.write(self.style.SUCCESS(f"Updated {len(to_update)} observatory descriptions."))
        else:
            self.stdout.write("No changes needed.")
