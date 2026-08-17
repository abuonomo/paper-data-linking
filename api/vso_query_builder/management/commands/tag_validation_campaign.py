"""Assign papers of a validation campaign to reviewers via Paper tags.

Takes the campaign's paper set (``set_tag``), draws the overlap subset (papers
reviewed independently by BOTH reviewers, for inter-rater reliability), and
splits the remainder between the reviewers — both draws seeded and stratified
by mission-bibliography tag so each reviewer sees a comparable mission mix.

Tags applied:
  ``<tag_prefix><username>``  bulk papers assigned to that reviewer
  ``<overlap_tag>``           overlap papers (both reviewers)

Deterministic for a given --seed. Use --dry-run to preview the composition.
Refuses to run when campaign tags already exist unless --force (which first
removes all existing ``<tag_prefix>*`` tags from the set's papers).
"""
import random
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from paper_data_linking.config.settings import get_validation_campaign

from ...models import Paper

# Mission-bib strata (merged case-variants), same merge logic as create_test_set.
DEFAULT_BIBS = ["soho+SOHO", "wind+Wind", "ACE", "IRIS",
                "PSP_FIELDS+PSP_SWEAP", "sdo_candidates", "mission_groups"]


class Command(BaseCommand):
    help = "Tag a validation campaign's papers with reviewer assignments (overlap + per-reviewer split)."

    def add_arguments(self, parser):
        parser.add_argument("--campaign", required=True, help="Campaign slug (see VALIDATION_CAMPAIGNS).")
        parser.add_argument("--seed", type=int, required=True, help="Random seed (record it; reruns reproduce the split).")
        parser.add_argument("--overlap-count", type=int, default=27,
                            help="Papers reviewed by BOTH reviewers (inter-rater reliability subset).")
        parser.add_argument("--bibs", default=",".join(DEFAULT_BIBS),
                            help="Comma-separated mission-bib strata (merged variants with '+').")
        parser.add_argument("--dry-run", action="store_true", help="Preview composition without applying tags.")
        parser.add_argument("--force", action="store_true",
                            help="Remove existing campaign tags first, then retag.")

    def handle(self, *args, **opts):
        campaign = get_validation_campaign(opts["campaign"])
        if campaign is None:
            raise CommandError(f"Unknown campaign: {opts['campaign']}")
        if len(campaign.reviewers) != 2:
            raise CommandError(
                f"This command implements a 2-reviewer split; campaign has {len(campaign.reviewers)} reviewers."
            )
        rng = random.Random(opts["seed"])
        dry = opts["dry_run"]

        papers = list(
            Paper.objects.filter(tags__contains=[campaign.set_tag])
            .order_by("bibcode")
            .only("id", "bibcode", "tags")
        )
        if not papers:
            raise CommandError(f"No papers carry the set tag '{campaign.set_tag}'.")

        # Idempotency guard: refuse to double-tag.
        already = [p for p in papers if any(t.startswith(campaign.tag_prefix) for t in p.tags)]
        if already and not opts["force"]:
            raise CommandError(
                f"{len(already)} papers already carry '{campaign.tag_prefix}*' tags "
                f"(e.g. {already[0].bibcode}). Re-run with --force to clear and retag."
            )

        # Stratify by first matching mission-bib tag; unmatched papers form 'other'.
        strata_defs = [b for b in opts["bibs"].split(",") if b]
        strata = defaultdict(list)
        for paper in papers:
            stratum = next(
                (b for b in strata_defs if set(b.split("+")) & set(paper.tags)),
                "other",
            )
            strata[stratum].append(paper)

        # Draw the overlap subset proportionally across strata, then split the
        # rest alternating within each stratum (seeded shuffle first).
        overlap, assignments = [], {campaign.reviewers[0]: [], campaign.reviewers[1]: []}
        total = len(papers)
        for stratum in strata_defs + ["other"]:
            group = strata.get(stratum, [])
            if not group:
                continue
            rng.shuffle(group)
            n_overlap = round(opts["overlap_count"] * len(group) / total)
            overlap.extend(group[:n_overlap])
            rest = group[n_overlap:]
            for i, paper in enumerate(rest):
                assignments[campaign.reviewers[i % 2]].append(paper)

        # Composition report.
        self.stdout.write(self.style.SUCCESS(
            f"\nCampaign '{campaign.slug}' — {total} papers "
            f"(seed={opts['seed']}, overlap={len(overlap)})"
        ))
        header = f"{'stratum':18s} {'papers':>7s} {'overlap':>8s} " + " ".join(
            f"{r[:12]:>12s}" for r in campaign.reviewers
        )
        self.stdout.write(header)
        overlap_ids = {p.id for p in overlap}
        for stratum in strata_defs + ["other"]:
            group = strata.get(stratum, [])
            if not group:
                continue
            n_over = sum(1 for p in group if p.id in overlap_ids)
            counts = [
                sum(1 for p in assignments[r] if p in group) for r in campaign.reviewers
            ]
            self.stdout.write(
                f"{stratum:18s} {len(group):7d} {n_over:8d} " + " ".join(f"{c:12d}" for c in counts)
            )
        for reviewer in campaign.reviewers:
            self.stdout.write(
                f"  {reviewer}: {len(assignments[reviewer])} bulk + {len(overlap)} overlap papers"
            )

        if dry:
            self.stdout.write(self.style.WARNING("\n[dry-run] no tags applied."))
            return

        with transaction.atomic():
            if opts["force"]:
                for paper in papers:
                    cleaned = [t for t in paper.tags if not t.startswith(campaign.tag_prefix)]
                    if cleaned != paper.tags:
                        paper.tags = cleaned
                        paper.save(update_fields=["tags"])
            for paper in overlap:
                paper.tags = paper.tags + [campaign.overlap_tag]
                paper.save(update_fields=["tags"])
            for reviewer, group in assignments.items():
                tag = f"{campaign.tag_prefix}{reviewer}"
                for paper in group:
                    paper.tags = paper.tags + [tag]
                    paper.save(update_fields=["tags"])
        self.stdout.write(self.style.SUCCESS(
            f"\nTagged {len(overlap)} overlap + "
            + " + ".join(f"{len(assignments[r])} ({r})" for r in campaign.reviewers)
            + " papers."
        ))
