# api/vso_query_builder/management/commands/seed_cdaweb_instruments.py

import json
from django.core.management.base import BaseCommand
from django.db import transaction
from paper_data_linking.config.paths import DATA_ASSETS_DIR
from ...models import Instrument, Observatory, DataSource


class Command(BaseCommand):
    help = 'Seeds the database with instruments from the CDAWEB JSONL catalog.'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting CDAWEB instrument seeding process...")

        data_dir = DATA_ASSETS_DIR / "vso"
        catalog_path = data_dir / "cdaweb_instrument_records_07_22_2025.jsonl"

        if not catalog_path.exists():
            self.stderr.write(self.style.ERROR("CDAWEB catalog file not found."))
            return

        catalog_data = []
        with open(catalog_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    catalog_data.append(json.loads(line))

        try:
            with transaction.atomic():
                self.stdout.write("Creating CDAWEB data source...")
                cdaweb_source, _ = DataSource.objects.get_or_create(
                    slug="cdaweb", defaults={"name": "Coordinated Data Analysis Web"}
                )

                observatories_cache = {}
                instruments_to_create = []

                for entry in catalog_data:
                    mission_code = entry.get("mission_code")
                    observatory_obj = None

                    if mission_code:
                        if mission_code not in observatories_cache:
                            observatory_obj, _ = Observatory.objects.get_or_create(
                                short_name=mission_code.strip(),
                                defaults={
                                    "datasource": cdaweb_source,
                                    "name": entry.get("mission_name", mission_code),
                                }
                            )
                            observatories_cache[mission_code] = observatory_obj
                        else:
                            observatory_obj = observatories_cache[mission_code]

                    instruments_to_create.append(
                        Instrument(
                            observatory=observatory_obj,
                            short_name=entry.get("instrument_code", "").strip(),
                            full_name=entry.get("instrument_name", ""),
                            description=entry.get("description", ""),
                            provider=entry.get("provider"),
                        )
                    )

                Instrument.objects.bulk_create(instruments_to_create)

            self.stdout.write(self.style.SUCCESS(f"Successfully seeded {len(catalog_data)} CDAWEB instruments."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"An error occurred during CDAWEB seeding: {e}"))