"""Draw the seeded, stratified calibration sample for a validation campaign.

The calibration round is the first thing both reviewers do: they judge the
SAME ~25 claims (chosen to over-represent known-hard patterns plus a few clean
anchors), then meet, resolve disagreements, and freeze the rubric.

Strata (target counts for a 25-claim sample; heuristic predicates specced from
the v3 disagreement-review taxonomy in pdl-paper):

  config_a_only        5   extracted only by the first config (loose-inclusion boundary)
  config_b_only        3   extracted only by the second config
  window_divergent     3   same (paper, instrument) with differing windows across configs
  omni_composite       2   OMNI / composite data products (source-spacecraft rule)
  generic_series       2   GOES / constellation fan-out patterns
  suite_subinstrument  2   suite vs sub-instrument naming level
  catalog_derived      2   catalog/event-list derived values (quote text heuristic)
  weak_grounding       2   claims with at most one supporting quote
  clean_anchor         4   both-config, well-quoted claims with none of the above
                           (anchors prevent all-hard calibration drift toward
                           over-rejection)

Shortfall in any stratum is backfilled from clean anchors (logged). Output is
a JSON claim list on stdout — check it into the paper repo — plus, unless
--dry-run, the campaign's calibration tag applied to the claims' papers.
Freeze the printed usage ids into ``VALIDATION_CAMPAIGNS[...].calibration_usage_ids``.
"""
import json
import random
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from paper_data_linking.config.settings import get_validation_campaign

from ...campaign_claims import campaign_usages_queryset, group_claims
from ...models import Paper

STRATA_TARGETS = [
    ("config_a_only", 5),
    ("config_b_only", 3),
    ("window_divergent", 3),
    ("omni_composite", 2),
    ("generic_series", 2),
    ("suite_subinstrument", 2),
    ("catalog_derived", 2),
    ("weak_grounding", 2),
    ("clean_anchor", 4),
]

GENERIC_SERIES_MARKERS = ("goes", "cluster", "lanl", "stereo", "helios")
SUITE_NAMES = ("secchi", "fields", "sweap", "sem")
CATALOG_MARKERS = ("catalog", "catalogue", "event list", "database")


def _claim_configs(claim):
    return {
        m.paper_analysis.configuration_name
        for m in claim.members
        if m.paper_analysis_id and m.paper_analysis.configuration_name
    }


def _unique_quotes(claim):
    seen = set()
    for member in claim.members:
        for quote in member.supporting_quotes.all():
            seen.add((quote.quote, quote.page_number))
    return seen


def classify(claim, campaign, divergent_ids):
    """First matching stratum for a claim (priority = STRATA_TARGETS order)."""
    config_a, config_b = campaign.configs
    configs = _claim_configs(claim)
    rep = claim.representative
    obs_text = ' '.join(filter(None, [
        rep.instrument.observatory.short_name if rep.instrument and rep.instrument.observatory else '',
        rep.instrument.observatory.name if rep.instrument and rep.instrument.observatory else '',
    ])).lower()
    instr_text = (rep.instrument.short_name if rep.instrument else '').lower()
    quotes = _unique_quotes(claim)
    quote_text = ' '.join(q for q, _ in quotes).lower()

    if configs == {config_a}:
        return "config_a_only"
    if configs == {config_b}:
        return "config_b_only"
    if str(rep.id) in divergent_ids:
        return "window_divergent"
    if 'omni' in obs_text or 'omni' in instr_text:
        return "omni_composite"
    if any(marker in obs_text for marker in GENERIC_SERIES_MARKERS):
        return "generic_series"
    if '/' in instr_text or any(instr_text.startswith(s) or instr_text == s for s in SUITE_NAMES):
        return "suite_subinstrument"
    if any(marker in quote_text for marker in CATALOG_MARKERS):
        return "catalog_derived"
    if len(quotes) <= 1:
        return "weak_grounding"
    if configs == {config_a, config_b} and len(quotes) >= 2:
        return "clean_anchor"
    return None  # both-config but thin — not a useful calibration exemplar


class Command(BaseCommand):
    help = "Seeded stratified calibration sample for a validation campaign (JSON to stdout + calibration tag)."

    def add_arguments(self, parser):
        parser.add_argument("--campaign", required=True, help="Campaign slug (see VALIDATION_CAMPAIGNS).")
        parser.add_argument("--seed", type=int, required=True, help="Random seed (record it).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Print the sample without applying the calibration tag.")

    def handle(self, *args, **opts):
        campaign = get_validation_campaign(opts["campaign"])
        if campaign is None:
            raise CommandError(f"Unknown campaign: {opts['campaign']}")
        rng = random.Random(opts["seed"])

        claims = group_claims(campaign_usages_queryset(campaign))
        if not claims:
            raise CommandError(
                f"No claims found — are both configs' runs present for set '{campaign.set_tag}'?"
            )

        # Window-divergent detection: same (paper, instrument) appearing as
        # multiple claims whose members span both configs.
        by_paper_instrument = defaultdict(list)
        for claim in claims:
            rep = claim.representative
            by_paper_instrument[(rep.paper_id, rep.instrument_id)].append(claim)
        divergent_ids = set()
        for group in by_paper_instrument.values():
            if len(group) < 2:
                continue
            group_configs = set().union(*(_claim_configs(c) for c in group))
            if len(group_configs) == 2:
                divergent_ids.update(str(c.usage_id) for c in group)

        # Classify every claim into its (single, priority-ordered) stratum.
        pools = defaultdict(list)
        for claim in claims:
            stratum = classify(claim, campaign, divergent_ids)
            if stratum:
                pools[stratum].append(claim)

        self.stderr.write(self.style.SUCCESS(
            f"\nClaim union: {len(claims)} claims across "
            f"{len({c.representative.paper_id for c in claims})} papers"
        ))
        self.stderr.write(f"{'stratum':22s} {'eligible':>9s} {'target':>7s}")
        for stratum, target in STRATA_TARGETS:
            self.stderr.write(f"{stratum:22s} {len(pools[stratum]):9d} {target:7d}")

        # Seeded draw per stratum; shortfall backfills from clean anchors.
        # (classify() puts each claim in exactly one stratum, so only the
        # backfill needs dedup — tracked by usage id.)
        selected, shortfall = [], 0
        chosen_ids = set()
        for stratum, target in STRATA_TARGETS:
            pool = [c for c in pools[stratum] if str(c.usage_id) not in chosen_ids]
            take = min(target, len(pool))
            if take < target:
                self.stderr.write(self.style.WARNING(
                    f"  stratum '{stratum}' short by {target - take} — backfilling from clean anchors"
                ))
                shortfall += target - take
            picked = rng.sample(pool, take)
            chosen_ids.update(str(c.usage_id) for c in picked)
            selected.extend((claim, stratum) for claim in picked)
        if shortfall:
            anchor_pool = [c for c in pools["clean_anchor"] if str(c.usage_id) not in chosen_ids]
            extra = rng.sample(anchor_pool, min(shortfall, len(anchor_pool)))
            chosen_ids.update(str(c.usage_id) for c in extra)
            selected.extend((claim, "clean_anchor(backfill)") for claim in extra)

        sample = [
            {
                "usage_id": str(claim.usage_id),
                "paper_id": str(claim.representative.paper_id),
                "bibcode": claim.representative.paper.bibcode,
                "stratum": stratum,
                "observatory": claim.representative.instrument.observatory.short_name
                if claim.representative.instrument and claim.representative.instrument.observatory else None,
                "instrument": claim.representative.instrument.short_name
                if claim.representative.instrument else None,
                "window": [
                    claim.representative.start_lower.isoformat() if claim.representative.start_lower else None,
                    claim.representative.end_upper.isoformat() if claim.representative.end_upper else None,
                ],
            }
            for claim, stratum in selected
        ]
        output = {
            "campaign": campaign.slug,
            "seed": opts["seed"],
            "n_claims": len(sample),
            "claims": sample,
        }
        self.stdout.write(json.dumps(output, indent=2))
        self.stderr.write(self.style.SUCCESS(
            "Freeze output['claims'][*]['usage_id'] into VALIDATION_CAMPAIGNS calibration_usage_ids."
        ))

        if opts["dry_run"]:
            self.stderr.write(self.style.WARNING("[dry-run] calibration tag not applied."))
            return
        paper_ids = {c["paper_id"] for c in sample}
        with transaction.atomic():
            for paper in Paper.objects.filter(id__in=paper_ids):
                if campaign.calibration_tag not in paper.tags:
                    paper.tags = paper.tags + [campaign.calibration_tag]
                    paper.save(update_fields=["tags"])
        self.stderr.write(self.style.SUCCESS(
            f"Applied '{campaign.calibration_tag}' to {len(paper_ids)} papers."
        ))
