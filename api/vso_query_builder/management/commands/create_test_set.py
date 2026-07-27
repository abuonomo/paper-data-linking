"""Construct a variety-first test set by stratified sampling across mission-scientist
bibliography tags, and apply a new tag to the selection.

Design (see selection rationale): variety comes ONLY from the bibliography tags
(independent of the pipeline); ground-truth validations are reused where they exist
(soho/wind) via a validated-first ordering, but are never the variety signal. NOTHING
about the pipeline's extracted instruments / dataset usages is used for selection.

Per stratum (bib tag):
  eligible  = papers carrying the tag, with full_text > --min-text, and (by default)
              NOT already in any existing test_set_* tag (keep the set fresh).
  ordering  = validated papers first (by #DatasetUsageValidation desc), then the
              remaining papers spread evenly by bibcode (≈ chronological) for diversity.
  take      = --per-bib papers.
Papers are de-duplicated across strata (first stratum that picks a paper keeps it).

Deterministic (no randomness) → reproducible. Use --dry-run to preview composition.
"""
from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from ...models import Paper

# Strata = one per MISSION (counted once each). Tags for the same mission are merged
# with "+": soho/SOHO and wind/Wind are disjoint source bibs for one mission; PSP_FIELDS
# and PSP_SWEAP are two instrument bibs for one mission (Parker Solar Probe).
DEFAULT_BIBS = ["soho+SOHO", "wind+Wind", "ACE", "IRIS",
                "PSP_FIELDS+PSP_SWEAP", "sdo_candidates", "mission_groups"]


def _spread(items, k):
    """Pick k items evenly spaced across a sorted list (chronological spread)."""
    n = len(items)
    if n <= k:
        return list(items)
    step = n / k
    return [items[int(i * step)] for i in range(k)]


class Command(BaseCommand):
    help = "Variety-first test set: stratified sample across mission-bib tags, validated-first, apply a new tag."

    def add_arguments(self, parser):
        parser.add_argument("--tag", required=True, help="New tag to apply to the selected papers.")
        parser.add_argument("--per-bib", type=int, default=20, help="Papers per bibliography stratum.")
        parser.add_argument("--bibs", default=",".join(DEFAULT_BIBS), help="Comma-separated bib tags (strata).")
        parser.add_argument("--min-text", type=int, default=2000, help="Minimum full_text length to be analyzable.")
        parser.add_argument("--include-test-sets", action="store_true",
                            help="Allow papers already in an existing test_set_* tag (default: exclude).")
        parser.add_argument("--dry-run", action="store_true", help="Preview composition without applying the tag.")

    def handle(self, *args, **opts):
        bibs = [b for b in opts["bibs"].split(",") if b]
        per_bib = opts["per_bib"]
        min_text = opts["min_text"]
        exclude_test_sets = not opts["include_test_sets"]
        dry = opts["dry_run"]
        new_tag = opts["tag"]

        # validation count per paper (ground-truth richness) — the ONLY DU-derived signal, and not used for variety
        val_counts = dict(
            Paper.objects.filter(dataset_usages__validations__isnull=False)
            .annotate(nv=Count("dataset_usages__validations"))
            .values_list("id", "nv")
        )

        selected = {}   # paper_id -> stratum it was chosen for
        per_bib_stats = {}
        for bib in bibs:
            group = bib.split("+")              # merged case-variant tags for one mission
            qs = Paper.objects.filter(tags__overlap=group).exclude(id__in=selected.keys())
            # analyzable
            qs = qs.extra(where=["length(coalesce(full_text,'')) > %s"], params=[min_text])
            cand = list(qs.values_list("id", "bibcode", "tags"))
            if exclude_test_sets:
                cand = [(pid, bc, tags) for pid, bc, tags in cand
                        if not any(t.startswith("test_set") for t in tags)]
            # rank: validated-first (desc nv), then year-spread of the rest by bibcode
            validated = sorted([c for c in cand if c[0] in val_counts],
                               key=lambda c: (-val_counts[c[0]], c[1]))
            fresh = sorted([c for c in cand if c[0] not in val_counts], key=lambda c: c[1])
            chosen = validated[:per_bib]
            if len(chosen) < per_bib:
                chosen += [c for c in _spread(fresh, per_bib - len(chosen))]
            n_val = sum(1 for c in chosen if c[0] in val_counts)
            for pid, bc, tags in chosen:
                selected[pid] = bib
            per_bib_stats[bib] = (len(cand), len(chosen), n_val)

        # report
        self.stdout.write(self.style.SUCCESS(f"\nTest set '{new_tag}' — {len(selected)} papers across {len(bibs)} bibs"))
        self.stdout.write(f"{'bib':16s} {'eligible':>9s} {'picked':>7s} {'validated':>10s}")
        tot_val = 0
        for bib in bibs:
            elig, picked, nval = per_bib_stats[bib]
            tot_val += nval
            self.stdout.write(f"{bib:16s} {elig:9d} {picked:7d} {nval:10d}")
        self.stdout.write(f"{'TOTAL':16s} {'':>9s} {len(selected):7d} {tot_val:10d}  "
                          f"({100*tot_val//max(len(selected),1)}% carry validations)")

        if dry:
            self.stdout.write(self.style.WARNING("\n[dry-run] no tag applied."))
            return
        with transaction.atomic():
            for pid in selected:
                p = Paper.objects.get(id=pid)
                if new_tag not in p.tags:
                    p.tags = p.tags + [new_tag]
                    p.save(update_fields=["tags"])
        self.stdout.write(self.style.SUCCESS(f"\nApplied tag '{new_tag}' to {len(selected)} papers."))
