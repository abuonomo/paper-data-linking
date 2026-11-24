"""Export the instrument catalog as a snapshot file for database-free runs.

The snapshot freezes what DjangoInstrumentFinder returns right now, so a runner using
SnapshotInstrumentFinder builds the same grounding prompts as this database would.

Usage: python manage.py export_catalog_snapshot --out catalog_snapshot.json
"""

import json

from django.core.management.base import BaseCommand

from paper_data_linking.linkers.general.snapshot_finder import build_snapshot

from ...finders import DjangoInstrumentFinder
from ...models import Instrument


class Command(BaseCommand):
    help = "Export the instrument catalog as a snapshot file for database-free runs"

    def add_arguments(self, parser):
        parser.add_argument("--out", help="Output path (default: stdout)")

    def handle(self, *args, **options):
        ids = {
            (inst.observatory.datasource.slug, inst.observatory.short_name, inst.short_name): {
                "instrument_id": str(inst.id),
                "observatory_id": str(inst.observatory_id),
            }
            for inst in Instrument.objects.select_related("observatory__datasource").filter(
                observatory__isnull=False, observatory__datasource__isnull=False
            )
        }
        snapshot = build_snapshot(
            DjangoInstrumentFinder(),
            id_lookup=lambda e: ids.get((e.data_system, e.mission_code, e.instrument_code)),
        )
        text = json.dumps(snapshot, indent=1, ensure_ascii=False)
        if options["out"]:
            with open(options["out"], "w", encoding="utf-8") as f:
                f.write(text + "\n")
            self.stderr.write(
                f"Wrote {len(snapshot['instruments'])} instruments, "
                f"{len(snapshot['unique_missions'])} missions, hash {snapshot['content_hash'][:12]} to {options['out']}"
            )
        else:
            self.stdout.write(text)
