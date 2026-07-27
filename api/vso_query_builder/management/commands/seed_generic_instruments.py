# api/vso_query_builder/management/commands/seed_generic_instruments.py
"""Seed CUSTOM group-level generic instrument rows.

These rows let the grounder commit to a program-level answer (e.g. "GOES, X-ray,
this window") when a paper names a program but no specific spacecraft — instead
of stochastically guessing a satellite number or dropping the grounding entirely.

Each generic instrument:
  * hangs off the REAL SPASE ObservatoryGroup observatory (e.g.
    spase://SMWG/Observatory/GOES) — a genuine, HDPWS-queryable group ID,
  * is flagged catalog_source='custom' so snippet generation skips it (a standard
    CDAWeb query on a non-leaf ID would silently return nothing),
  * rides the existing cdaweb grounding pool (datasource='cdaweb') as one more
    candidate in mission/instrument selection — no new data system, no extra
    LLM calls.

Idempotent: get_or_create on both the observatory and the instrument, so
re-running updates nothing and creates no duplicates. To grow coverage, add
entries to GENERIC_GROUPS (one observatory + its generic instruments per group).
Start small (GOES/SEM) and extend only for (group, instrument-type) combos that
papers actually reference generically.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from ...models import Instrument, Observatory, DataSource, CatalogSource


# One entry per ObservatoryGroup. `observatory` is a real SPASE ObservatoryGroupID.
# `instruments` are authored group-level rows (catalog_source=custom).
GENERIC_GROUPS = [
    {
        "observatory": {
            "short_name": "spase://SMWG/Observatory/GOES",
            "name": "GOES",
            # Keep this SHORT and declarative — it is inlined alongside ~360 other
            # missions in the shared Stage-1 mission_identification prompt, so verbose
            # or imperative text here perturbs unrelated groundings. The "pick generic
            # vs numbered" steering lives in the mission_selection system prompt, not here.
            "description": (
                "NOAA GOES geostationary satellite series as a whole (all satellites "
                "combined); represents GOES observations not attributed to one specific "
                "GOES satellite number."
            ),
        },
        "instruments": [
            {
                "short_name": "spase://SMWG/Instrument/GOES/SEM",
                "full_name": "SEM (generic GOES)",
                "description": (
                    "GOES Space Environment Monitor (SEM) — generic across the GOES "
                    "series (any satellite). The SEM package carries the X-Ray Sensor "
                    "(XRS, soft/hard solar X-ray irradiance), Energetic Particle Sensor "
                    "(EPS: electrons, protons, alphas) and a magnetometer (MAG). Use for a "
                    "GOES X-ray / particle / magnetic-field mention that does not name a "
                    "specific GOES satellite number."
                ),
            },
        ],
    },
]


class Command(BaseCommand):
    help = "Seeds CUSTOM group-level generic instrument rows (e.g. GOES/SEM)."

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding generic group-level instruments...")

        cdaweb_source, _ = DataSource.objects.get_or_create(
            slug="cdaweb", defaults={"name": "Coordinated Data Analysis Web"}
        )

        created_obs = updated_obs = created_inst = existing_inst = 0
        try:
            with transaction.atomic():
                for group in GENERIC_GROUPS:
                    obs_spec = group["observatory"]
                    obs, obs_created = Observatory.objects.get_or_create(
                        short_name=obs_spec["short_name"].strip(),
                        defaults={
                            "datasource": cdaweb_source,
                            "name": obs_spec["name"],
                            "description": obs_spec.get("description", ""),
                        },
                    )
                    if obs_created:
                        created_obs += 1
                    else:
                        # Keep the group observatory's name/description in sync.
                        obs.datasource = cdaweb_source
                        obs.name = obs_spec["name"]
                        obs.description = obs_spec.get("description", "")
                        obs.save(update_fields=["datasource", "name", "description"])
                        updated_obs += 1

                    for inst_spec in group["instruments"]:
                        _, inst_created = Instrument.objects.get_or_create(
                            observatory=obs,
                            short_name=inst_spec["short_name"].strip(),
                            defaults={
                                "full_name": inst_spec.get("full_name", ""),
                                "description": inst_spec.get("description", ""),
                                "catalog_source": CatalogSource.CUSTOM,
                            },
                        )
                        if inst_created:
                            created_inst += 1
                        else:
                            existing_inst += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Observatories: {created_obs} created, {updated_obs} updated. "
                    f"Generic instruments: {created_inst} created, {existing_inst} already present."
                )
            )
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error during generic seeding: {e}"))
            raise
