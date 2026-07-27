# api/vso_query_builder/management/commands/seed_instruments.py

import json
import numpy as np
from django.core.management.base import BaseCommand
from django.db import transaction
from paper_data_linking.config.paths import DATA_ASSETS_DIR
from ...models import Instrument, Observatory, DataSource


class Command(BaseCommand):
    help = 'Seeds the database with instruments from the VSO JSON catalog.'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting instrument seeding process...")

        data_dir = DATA_ASSETS_DIR / "vso"
        catalog_path = data_dir / "enhanced_instrument_catalog.json"

        # We no longer need the embeddings file
        # embeddings_path = data_dir / "instrument_embeddings.npy"

        if not catalog_path.exists():
            self.stderr.write(self.style.ERROR("Catalog file not found."))
            return

        with open(catalog_path, 'r', encoding='utf-8') as f:
            catalog_data = json.load(f)

        # All logic related to loading and checking embeddings has been removed.

        try:
            with transaction.atomic():
                self.stdout.write("Deleting existing instrument data in correct order...")
                Instrument.objects.all().delete()
                Observatory.objects.all().delete()
                DataSource.objects.all().delete()

                self.stdout.write("Seeding new data...")
                vso_source, _ = DataSource.objects.get_or_create(
                    slug="vso", defaults={"name": "Virtual Solar Observatory"}
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
                                    "datasource": vso_source,
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
                            provider=entry.get("provider", ""),
                            # The embedding field is no longer set, so it will be null
                        )
                    )

                Instrument.objects.bulk_create(instruments_to_create)

            self.stdout.write(self.style.SUCCESS(f"Successfully seeded {len(catalog_data)} instruments."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"An error occurred during seeding: {e}"))