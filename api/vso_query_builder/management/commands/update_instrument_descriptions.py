# api/vso_query_builder/management/commands/update_instrument_descriptions.py
"""
Apply enriched instrument catalog to the database.

Reads llm_enriched_catalog.json (or merged_instrument_catalog.json) and performs
targeted bulk updates of:
  - Instrument.description
  - Instrument.full_name  (from instrument_name in catalog)
  - Observatory.name      (probe-specific, e.g. "MMS-1" instead of "MMS")

Matching is done by short_name (instrument_code / mission_code in catalog).

Usage:
    docker compose exec api python manage.py update_instrument_descriptions
    docker compose exec api python manage.py update_instrument_descriptions --dry-run
    docker compose exec api python manage.py update_instrument_descriptions \
        --catalog /path/to/custom_catalog.json
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from paper_data_linking.config.paths import DATA_ASSETS_DIR
from ...models import Instrument, Observatory

DEFAULT_CATALOG = DATA_ASSETS_DIR / "vso" / "merged_instrument_catalog.json"
ENRICHED_CATALOG = Path(__file__).parent.parent.parent.parent.parent / \
    "experiments" / "instrument_grounding_evaluation" / "llm_enriched_catalog.json"


class Command(BaseCommand):
    help = "Apply enriched descriptions/names from catalog JSON to Instrument and Observatory records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--catalog",
            type=str,
            default=None,
            help="Path to catalog JSON. Defaults to llm_enriched_catalog.json if it exists, "
                 "otherwise merged_instrument_catalog.json.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Show what would be updated without writing to the database.",
        )
        parser.add_argument(
            "--skip-observatory-names",
            action="store_true",
            default=False,
            help="Skip updating Observatory.name (useful when only descriptions changed).",
        )
        parser.add_argument(
            "--regenerate-embeddings",
            action="store_true",
            default=False,
            help="After updating descriptions, regenerate Instrument embeddings via the OpenAI API. "
                 "Required because bulk_update does not trigger post_save signals.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        skip_obs = options["skip_observatory_names"]

        # Always back up current DB values before any changes
        if not dry_run:
            self._backup_current_values(skip_obs)

        # Determine catalog path
        if options["catalog"]:
            catalog_path = Path(options["catalog"])
        elif ENRICHED_CATALOG.exists():
            catalog_path = ENRICHED_CATALOG
        else:
            catalog_path = DEFAULT_CATALOG

        if not catalog_path.exists():
            self.stderr.write(self.style.ERROR(f"Catalog not found: {catalog_path}"))
            return

        self.stdout.write(f"Loading catalog: {catalog_path}")
        catalog = json.loads(catalog_path.read_text())
        self.stdout.write(f"Catalog entries: {len(catalog)}")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be written."))
        self.stdout.write("")

        # Build lookup maps from catalog
        # (mission_code, instrument_code) → {description, full_name}
        # Keyed by BOTH codes: VSO short codes repeat across missions (e.g. IMPACT
        # under STEREO_A and STEREO_B), so instrument_code alone silently assigns
        # one mission's text to every same-named entry.
        instrument_updates: dict[tuple, dict] = {}
        # mission_code (Observatory.short_name) → new name
        observatory_updates: dict[str, str] = {}

        for entry in catalog:
            inst_code = entry.get("instrument_code", "").strip()
            entry_mission = entry.get("mission_code", "").strip()
            if inst_code:
                instrument_updates[(entry_mission, inst_code)] = {
                    "description": entry.get("description", ""),
                    "full_name":   entry.get("instrument_name", ""),
                }

            if not skip_obs:
                mission_code = entry.get("mission_code", "").strip()
                mission_name = entry.get("mission_name", "").strip()
                if mission_code and mission_name:
                    # Only store if the name is probe-specific (contains a dash separator
                    # after the mission identifier, e.g. "MMS-1", "GOES-13", "STEREO-A")
                    # This avoids overwriting generic names with equally generic ones.
                    observatory_updates[mission_code] = mission_name

        # ── Update Instruments ────────────────────────────────────────────────
        self.stdout.write("=== Instrument updates ===")

        instruments_qs = Instrument.objects.filter(
            short_name__in=[k[1] for k in instrument_updates.keys()]
        ).select_related("observatory")

        matched_instruments = {
            ((inst.observatory.short_name if inst.observatory else ""), inst.short_name): inst
            for inst in instruments_qs
        }
        self.stdout.write(f"  Catalog entries   : {len(instrument_updates)}")
        self.stdout.write(f"  DB matches        : {len(matched_instruments)}")
        self.stdout.write(f"  Unmatched in DB   : {len(instrument_updates) - len(matched_instruments)}")

        to_update_desc = []
        to_update_name = []
        changed_desc = 0
        changed_name = 0

        for key, updates in instrument_updates.items():
            inst = matched_instruments.get(key)
            if not inst:
                continue

            new_desc = updates["description"]
            new_full  = updates["full_name"]

            if new_desc and inst.description != new_desc:
                inst.description = new_desc
                to_update_desc.append(inst)
                changed_desc += 1

            if new_full and inst.full_name != new_full:
                inst.full_name = new_full
                to_update_name.append(inst)
                changed_name += 1

        self.stdout.write(f"  Description changes : {changed_desc}")
        self.stdout.write(f"  full_name changes   : {changed_name}")

        if not dry_run and to_update_desc:
            # bulk_update is safe even when sets overlap; update each field separately
            # to avoid redundant saves
            all_inst_to_save = {i.pk: i for i in to_update_desc + to_update_name}
            fields = []
            if to_update_desc:
                fields.append("description")
            if to_update_name:
                fields.append("full_name")
            if fields:
                Instrument.objects.bulk_update(list(all_inst_to_save.values()), fields, batch_size=200)
            self.stdout.write(self.style.SUCCESS(f"  Updated {len(all_inst_to_save)} instrument records."))
        elif dry_run and (to_update_desc or to_update_name):
            # Show a sample of changes
            sample = list(matched_instruments.items())[:5]
            for key, inst in sample:
                upd = instrument_updates.get(key)
                if not upd:
                    continue
                code = inst.short_name
                self.stdout.write(f"  [DRY] {key[0][:30]}/{code[:40]}")
                self.stdout.write(f"        desc: {inst.description[:80]!r}")
                self.stdout.write(f"          → : {upd['description'][:80]!r}")

        # ── Update Observatories ──────────────────────────────────────────────
        if not skip_obs:
            self.stdout.write("")
            self.stdout.write("=== Observatory.name updates ===")

            obs_qs = Observatory.objects.filter(
                short_name__in=list(observatory_updates.keys())
            )
            matched_obs = {obs.short_name: obs for obs in obs_qs}
            self.stdout.write(f"  Catalog entries : {len(observatory_updates)}")
            self.stdout.write(f"  DB matches      : {len(matched_obs)}")

            to_update_obs = []
            changed_obs = 0
            for short_name, new_name in observatory_updates.items():
                obs = matched_obs.get(short_name)
                if not obs:
                    continue
                if obs.name != new_name:
                    obs.name = new_name
                    to_update_obs.append(obs)
                    changed_obs += 1

            self.stdout.write(f"  Name changes    : {changed_obs}")

            if not dry_run and to_update_obs:
                Observatory.objects.bulk_update(to_update_obs, ["name"], batch_size=200)
                self.stdout.write(self.style.SUCCESS(f"  Updated {changed_obs} observatory records."))
            elif dry_run and to_update_obs:
                sample = to_update_obs[:5]
                for obs in sample:
                    new_name = observatory_updates[obs.short_name]
                    self.stdout.write(f"  [DRY] {obs.short_name}")
                    self.stdout.write(f"        name: {obs.name!r} → {new_name!r}")

        # ── Regenerate Embeddings ─────────────────────────────────────────────
        if not dry_run and options["regenerate_embeddings"] and to_update_desc:
            self._regenerate_embeddings(to_update_desc)

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run complete — no DB changes were made."))
        else:
            self.stdout.write(self.style.SUCCESS("Done."))
            if not options["regenerate_embeddings"] and to_update_desc:
                self.stdout.write(
                    "Note: bulk_update does NOT trigger post_save signals. "
                    "Re-run with --regenerate-embeddings to update instrument embeddings."
                )

    def _regenerate_embeddings(self, instruments: list) -> None:
        """Regenerate OpenAI embeddings for the given Instrument instances."""
        from openai import OpenAI
        from django.conf import settings
        from paper_data_linking.config.settings import get_llm_configuration

        # Strip litellm provider prefix (e.g. "openai/text-embedding-3-small" → "text-embedding-3-small")
        model = get_llm_configuration("standard").embeddings.model
        if "/" in model:
            model = model.split("/", 1)[1]
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        self.stdout.write("")
        self.stdout.write(f"=== Regenerating embeddings for {len(instruments)} instruments (model: {model}) ===")
        success = 0
        errors = 0

        for inst in instruments:
            if not inst.description:
                continue
            try:
                response = client.embeddings.create(
                    input=[inst.description],
                    model=model,
                )
                embedding = response.data[0].embedding
                Instrument.objects.filter(id=inst.id).update(embedding=embedding)
                success += 1
            except Exception as e:
                self.stderr.write(f"  Error embedding {inst.short_name}: {e}")
                errors += 1

        self.stdout.write(self.style.SUCCESS(f"  Embeddings regenerated: {success}"))
        if errors:
            self.stdout.write(self.style.WARNING(f"  Errors: {errors}"))

    def _backup_current_values(self, include_observatories: bool = True) -> None:
        """
        Dump current Instrument.description, full_name, and Observatory.name to a
        timestamped JSON file before any changes are applied.

        The backup file is written to the same directory as this command so it
        persists inside the container and can be volume-mounted or copied out.
        Restore with: python manage.py update_instrument_descriptions --catalog <backup>
        (after adjusting field names — see backup format below).
        """
        import datetime

        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = Path(__file__).parent
        backup_path = backup_dir / f"instrument_descriptions_backup_{timestamp}.json"

        instruments = list(
            Instrument.objects.select_related("observatory").values(
                "short_name", "full_name", "description",
                "observatory__short_name",
            )
        )
        observatories = (
            list(Observatory.objects.values("short_name", "name"))
            if include_observatories
            else []
        )

        backup = {
            "created_at": timestamp,
            "instruments": [
                {
                    "instrument_code": r["short_name"],
                    "instrument_name": r["full_name"],
                    "description":     r["description"],
                    "mission_code":    r["observatory__short_name"],
                }
                for r in instruments
            ],
            "observatories": [
                {"short_name": r["short_name"], "name": r["name"]}
                for r in observatories
            ],
        }

        backup_path.write_text(json.dumps(backup, indent=2, ensure_ascii=False))
        self.stdout.write(self.style.SUCCESS(f"Backup saved: {backup_path}"))
        self.stdout.write(f"  Instruments : {len(instruments)}")
        self.stdout.write(f"  Observatories: {len(observatories)}")
        self.stdout.write("")
