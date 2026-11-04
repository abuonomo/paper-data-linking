"""Draw the seeded claim sample for a claim-scoped config-comparison campaign.

Compares the campaign's two configs on a source paper set by reviewing only the
claims where they DISAGREE: a claim both configs assert counts the same for
both, so it cannot change the comparison. Claims whose exact (paper,
instrument, window) already carries a verdict in the reference campaign are
skipped too — the analysis carries that verdict over instead.

Strata, drawn separately for each config:

  window_divergent  the other config has the same (paper, instrument) but no
                    claim with this window — the time-window validity question
  pair_unique       the other config has no claim for this (paper, instrument)

``--window-share`` of each config's ``--per-config`` claims come from
window_divergent; a shortfall in either stratum backfills from the other.
``--max-per-paper`` caps each config's claims per paper so one claim-heavy
paper cannot dominate. The two configs' claims are shuffled together.

Output is JSON on stdout: ``claim_usage_ids`` (freeze into
``VALIDATION_CAMPAIGNS[...].claim_usage_ids``) plus a per-claim key with config
and stratum. The key UNBLINDS the review — write it straight to the private
paper repo and do not read it before reviewing. Unless --dry-run, the sampled
claims' papers get the campaign set tag and each reviewer's tag; that exposes
nothing until the ids are frozen (claim-scoped campaigns with an empty id list
show no claims).
"""
import json
import random
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import DateTimeField, F, Func

from paper_data_linking.config.settings import get_validation_campaign

from ...models import DatasetUsage, DatasetUsageValidation, Paper


def _with_bounds(qs):
    return qs.annotate(
        start_lower=Func(F('observation_window'), function='lower', output_field=DateTimeField()),
        end_upper=Func(F('observation_window'), function='upper', output_field=DateTimeField()),
    )


def _key(row):
    return (row['paper_id'], row['instrument_id'], row['start_lower'], row['end_upper'])


def judged_keys(reference):
    """Claim keys that carry a reviewer verdict in the reference campaign."""
    validations = DatasetUsageValidation.objects.filter(
        user__username__in=reference.reviewers,
        dataset_usage__paper_analysis__configuration_name__in=reference.configs,
        dataset_usage__paper__tags__contains=[reference.set_tag],
    )
    if reference.started_at:
        validations = validations.filter(created_at__gte=reference.started_at)
    usages = _with_bounds(DatasetUsage.objects.filter(
        id__in=validations.values('dataset_usage_id'),
    )).values('paper_id', 'instrument_id', 'start_lower', 'end_upper')
    return {_key(row) for row in usages}


def candidate_pools(campaign, source_tag, skip_keys):
    """Per config: {'window_divergent': [...], 'pair_unique': [...]} of claim rows."""
    rows = _with_bounds(DatasetUsage.objects.filter(
        paper__tags__contains=[source_tag],
        paper_analysis__configuration_name__in=campaign.configs,
    )).values(
        'id', 'paper_id', 'paper__bibcode', 'instrument_id', 'start_lower', 'end_upper',
        'paper_analysis__configuration_name',
    )
    keys = defaultdict(set)
    pairs = defaultdict(set)
    representative = {}
    for row in rows:
        cfg = row['paper_analysis__configuration_name']
        key = _key(row)
        keys[cfg].add(key)
        pairs[cfg].add(key[:2])
        # Lowest id per (config, key) is the representative, as in group_claims.
        current = representative.get((cfg, key))
        if current is None or str(row['id']) < str(current['id']):
            representative[(cfg, key)] = row

    pools = {}
    for cfg in campaign.configs:
        (other,) = [c for c in campaign.configs if c != cfg]
        pool = {'window_divergent': [], 'pair_unique': []}
        for key in keys[cfg] - keys[other] - skip_keys:
            stratum = 'window_divergent' if key[:2] in pairs[other] else 'pair_unique'
            pool[stratum].append(representative[(cfg, key)])
        for stratum in pool:
            pool[stratum].sort(key=lambda r: str(r['id']))  # deterministic before the seeded shuffle
        pools[cfg] = pool
    return pools


def draw(pool, targets, max_per_paper, rng):
    """Seeded draw of {stratum: n} from pool, capped per paper, with cross-stratum backfill."""
    order = {stratum: rng.sample(rows, len(rows)) for stratum, rows in pool.items()}
    per_paper = defaultdict(int)
    picked = []

    def take(stratum, n):
        got = 0
        remaining = []
        for row in order[stratum]:
            if got < n and per_paper[row['paper_id']] < max_per_paper:
                per_paper[row['paper_id']] += 1
                picked.append((row, stratum))
                got += 1
            else:
                remaining.append(row)
        order[stratum] = remaining
        return got

    shortfall = 0
    for stratum, n in targets.items():
        shortfall += n - take(stratum, n)
    for stratum in targets:
        if shortfall:
            shortfall -= take(stratum, shortfall)
    return picked, shortfall


class Command(BaseCommand):
    help = "Seeded disagreement-claim sample for a claim-scoped comparison campaign (JSON to stdout + paper tags)."

    def add_arguments(self, parser):
        parser.add_argument("--campaign", required=True, help="Claim-scoped campaign slug (see VALIDATION_CAMPAIGNS).")
        parser.add_argument("--seed", type=int, required=True, help="Random seed (record it).")
        parser.add_argument("--reference-campaign", default="val2026",
                            help="Campaign whose existing verdicts are carried over (claims skipped).")
        parser.add_argument("--source-tag", default=None,
                            help="Paper set to sample from (default: the reference campaign's set tag).")
        parser.add_argument("--per-config", type=int, default=50, help="Claims drawn per config.")
        parser.add_argument("--window-share", type=float, default=0.8,
                            help="Fraction of each config's claims drawn from window_divergent.")
        parser.add_argument("--max-per-paper", type=int, default=3, help="Cap per config per paper.")
        parser.add_argument("--dry-run", action="store_true", help="Print the sample without tagging papers.")

    def handle(self, *args, **opts):
        campaign = get_validation_campaign(opts["campaign"])
        if campaign is None:
            raise CommandError(f"Unknown campaign: {opts['campaign']}")
        if not campaign.claim_scoped:
            raise CommandError(f"Campaign '{campaign.slug}' is not claim-scoped.")
        if len(campaign.configs) != 2:
            raise CommandError("Campaign must compare exactly two configs.")
        reference = get_validation_campaign(opts["reference_campaign"])
        if reference is None:
            raise CommandError(f"Unknown reference campaign: {opts['reference_campaign']}")
        source_tag = opts["source_tag"] or reference.set_tag
        rng = random.Random(opts["seed"])

        skip = judged_keys(reference)
        pools = candidate_pools(campaign, source_tag, skip)
        n_window = round(opts["per_config"] * opts["window_share"])
        targets = {"window_divergent": n_window, "pair_unique": opts["per_config"] - n_window}

        self.stderr.write(self.style.SUCCESS(
            f"\nSource set '{source_tag}'; {len(skip)} claim keys already judged in '{reference.slug}' (skipped)"
        ))
        sample = []
        for index, cfg in enumerate(campaign.configs):
            pool = pools[cfg]
            # Config names stay out of the report (it may be on screen while reviewing).
            self.stderr.write(
                f"config {index + 1}: eligible window_divergent={len(pool['window_divergent'])} "
                f"pair_unique={len(pool['pair_unique'])}"
            )
            picked, short = draw(pool, targets, opts["max_per_paper"], rng)
            if short:
                self.stderr.write(self.style.WARNING(f"  config {index + 1} short by {short} claims"))
            sample.extend((row, cfg, stratum) for row, stratum in picked)
        rng.shuffle(sample)

        output = {
            "campaign": campaign.slug,
            "seed": opts["seed"],
            "reference_campaign": reference.slug,
            "source_tag": source_tag,
            "n_claims": len(sample),
            "claim_usage_ids": [str(row["id"]) for row, _, _ in sample],
            "key": [
                {
                    "usage_id": str(row["id"]),
                    "paper_id": str(row["paper_id"]),
                    "bibcode": row["paper__bibcode"],
                    "config": cfg,
                    "stratum": stratum,
                    "window": [
                        row["start_lower"].isoformat() if row["start_lower"] else None,
                        row["end_upper"].isoformat() if row["end_upper"] else None,
                    ],
                }
                for row, cfg, stratum in sample
            ],
        }
        self.stdout.write(json.dumps(output, indent=2))
        self.stderr.write(self.style.SUCCESS(
            f"{len(sample)} claims. Freeze output['claim_usage_ids'] into "
            f"VALIDATION_CAMPAIGNS['{campaign.slug}'].claim_usage_ids."
        ))

        if opts["dry_run"]:
            self.stderr.write(self.style.WARNING("[dry-run] papers not tagged."))
            return
        wanted = [campaign.set_tag] + [f"{campaign.tag_prefix}{r}" for r in campaign.reviewers]
        paper_ids = {row["paper_id"] for row, _, _ in sample}
        with transaction.atomic():
            for paper in Paper.objects.filter(id__in=paper_ids):
                missing = [t for t in wanted if t not in paper.tags]
                if missing:
                    paper.tags = paper.tags + missing
                    paper.save(update_fields=["tags"])
        self.stderr.write(self.style.SUCCESS(f"Tagged {len(paper_ids)} papers with {wanted}."))
