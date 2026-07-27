# api/vso_query_builder/management/commands/seed_phenomena.py
"""
Seed the Phenomenon table from the HelioKNOW phenomena ontology.

The TTL file lives at data/phenomena/hk_phenomena.ttl and uses:
  hkp:<LocalName>  rdf:type hk:Phenomenon ;
                   skos:prefLabel "Human Label"@en ;

We extract only triples explicitly typed as hk:Phenomenon and map them
to Phenomenon(name=label, iri=compact_iri).
"""

import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from ...models import Phenomenon


# Path relative to this file: walk up from the command file to find repo root
_HERE = Path(__file__).resolve()

# Try to find repo root by walking up and looking for the tests/ directory
def _find_ttl():
    """Search for hk_phenomena.ttl in several candidate locations."""
    candidates = [
        # Walk up from this file looking for data/phenomena/
        *[_HERE.parents[i] / "data" / "phenomena" / "hk_phenomena.ttl" for i in range(2, len(_HERE.parents))],
        # Common container paths
        Path("/repo/data/phenomena/hk_phenomena.ttl"),
        Path("/tmp/phenomena/hk_phenomena.ttl"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not find hk_phenomena.ttl. Pass --ttl <path> explicitly. "
        f"Tried: {[str(c) for c in candidates[:5]]}"
    )


def _parse_ttl(content: str) -> list[tuple[str, str]]:
    """
    Return a list of (compact_iri, label) pairs parsed from the TTL.

    Strategy (no rdflib required):
      Split the file into stanzas (dot-terminated blocks), then for each
      stanza that has an hkp: subject, extract the skos:prefLabel "@en" value.
    """
    # Extract prefix for hkp
    hkp_prefix_match = re.search(r'@prefix\s+hkp:\s*<([^>]+)>', content)
    if not hkp_prefix_match:
        raise ValueError("Could not find @prefix hkp: declaration in TTL")
    hkp_base = hkp_prefix_match.group(1)

    results = {}

    # Split into stanzas on " .\n" (each TTL subject block ends with a period)
    # Use a regex split that keeps the structure
    stanzas = re.split(r'\n(?=\S)', content)

    for stanza in stanzas:
        stanza = stanza.strip()
        if not stanza:
            continue

        # Determine subject
        subject = None
        # hkp:<Name> as subject
        m = re.match(r'^(hkp:\S+)', stanza)
        if m:
            subject = m.group(1)
        else:
            # <full-uri> as subject
            m = re.match(r'^<([^>]+)>', stanza)
            if m:
                full_iri = m.group(1)
                if full_iri.startswith(hkp_base):
                    local = full_iri[len(hkp_base):]
                    subject = f"hkp:{local}"

        if subject is None:
            continue

        # Include entities typed as hk:Phenomenon or any subclass (e.g. hkp:PrincipalPhenomenon)
        if 'rdf:type hk:Phenomenon' not in stanza and 'rdf:type hkp:PrincipalPhenomenon' not in stanza:
            continue

        # Extract prefLabel
        label_match = re.search(r'skos:prefLabel\s+"([^"]+)"@en', stanza)
        if label_match:
            label = label_match.group(1)
            results[subject] = label

    return list(results.items())


class Command(BaseCommand):
    help = "Seed (create/update) Phenomenon records from the HelioKNOW TTL ontology."

    def add_arguments(self, parser):
        parser.add_argument(
            '--ttl',
            type=str,
            default=None,
            help='Explicit path to hk_phenomena.ttl (overrides auto-detection)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Parse and print phenomena without writing to the database',
        )

    def handle(self, *args, **options):
        ttl_path = Path(options['ttl']) if options['ttl'] else _find_ttl()
        self.stdout.write(f"Reading ontology from {ttl_path}")

        content = ttl_path.read_text(encoding='utf-8')
        pairs = _parse_ttl(content)

        if not pairs:
            self.stderr.write(self.style.ERROR("No phenomena parsed — check TTL format."))
            return

        self.stdout.write(f"Found {len(pairs)} phenomena in ontology.")

        if options['dry_run']:
            for iri, label in sorted(pairs, key=lambda x: x[1]):
                self.stdout.write(f"  {iri:50s}  {label}")
            return

        created_count = 0
        updated_count = 0
        skipped_count = 0

        # Deduplicate: if two IRIs share the same label, append a suffix to make
        # names unique (e.g. "Ionization Feature (hkp:Cusp)").
        seen_names: dict[str, str] = {}  # name -> first iri
        deduplicated: list[tuple[str, str]] = []
        for iri, label in pairs:
            if label not in seen_names:
                seen_names[label] = iri
                deduplicated.append((iri, label))
            else:
                # Rename the collision by appending the local IRI name
                local = iri.split(':')[-1]
                unique_label = f"{label} ({local})"
                self.stdout.write(
                    self.style.WARNING(
                        f"  Name collision: '{label}' for {iri} — renaming to '{unique_label}'"
                    )
                )
                deduplicated.append((iri, unique_label))

        with transaction.atomic():
            for iri, label in deduplicated:
                obj, created = Phenomenon.objects.update_or_create(
                    iri=iri,
                    defaults={'name': label},
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created: {created_count}, Updated: {updated_count}, "
                f"Skipped: {skipped_count}, Total phenomena: {Phenomenon.objects.count()}"
            )
        )
