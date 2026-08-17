"""Claim grouping for manual validation campaigns.

A *claim* is the unit of review in a validation campaign: the deduplicated
tuple (paper, instrument, exact observation window) across the campaign's
configurations. DatasetUsage rows from different configurations that assert
the same claim are grouped together so a reviewer judges each claim once and
the verdict propagates to every member row.

Grouping is done on the annotated lower/upper bounds of the observation
window (the same ``Func(lower/upper)`` pattern used by
``PaperDatasetUsagesView``) rather than on raw range equality, which
sidesteps bound-form (``[)`` vs ``(]``) representation mismatches. NULL
windows group together as their own key.

Same instrument but a *different* window is deliberately a separate claim —
window divergence between configurations is signal the campaign wants a
verdict on.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from django.db.models import DateTimeField, F, Func

from .models import DatasetUsage

# Sort sentinel for NULL window bounds.
_EPOCH = datetime(1, 1, 1, tzinfo=timezone.utc)


@dataclass
class Claim:
    """A deduplicated claim: one or more DatasetUsage rows asserting the same
    (paper, instrument, observation window) across campaign configurations."""

    # Deterministic representative: the member DU with the smallest UUID.
    representative: DatasetUsage
    members: list = field(default_factory=list)

    @property
    def usage_id(self):
        return self.representative.id

    @property
    def member_ids(self):
        return [du.id for du in self.members]


def campaign_usages_queryset(campaign, paper_id=None):
    """Base queryset of DatasetUsages participating in a campaign.

    Restricted to the campaign's configurations (rows with a NULL
    paper_analysis have no knowable configuration and are excluded) and to
    papers carrying the campaign's set tag.
    """
    qs = DatasetUsage.objects.filter(
        paper__tags__contains=[campaign.set_tag],
        paper_analysis__configuration_name__in=campaign.configs,
    )
    if paper_id is not None:
        qs = qs.filter(paper__id=paper_id)
    return qs.select_related(
        'instrument',
        'instrument__observatory',
        'instrument__observatory__datasource',
        'paper',
        'paper_analysis',
    ).defer(
        # PaperAnalysis carries huge JSON/text fields and Paper carries the
        # full text; materializing them for every DU OOMs the api container on
        # set-wide sweeps (e.g. the calibration sampler). Claim grouping and
        # serialization only need configuration_name / bibcode / pdf.
        'paper_analysis__context',
        'paper_analysis__instruments_details',
        'paper_analysis__structured_instruments_details',
        'paper_analysis__normalized_instrument_details',
        'paper_analysis__token_usage',
        'paper__full_text',
    ).prefetch_related('supporting_quotes').annotate(
        start_lower=Func(F('observation_window'), function='lower', output_field=DateTimeField()),
        end_upper=Func(F('observation_window'), function='upper', output_field=DateTimeField()),
    )


def claim_key(usage):
    """Grouping key for a DatasetUsage: (paper, instrument, window bounds).

    The paper id is part of the key so grouping stays correct when a queryset
    spans multiple papers (e.g. the calibration sampler) — the same
    instrument+window in two different papers is two different claims.

    Requires the queryset annotations from ``campaign_usages_queryset``
    (``start_lower`` / ``end_upper``). Open bounds (None) share a key.
    """
    return (usage.paper_id, usage.instrument_id, usage.start_lower, usage.end_upper)


def _claim_sort_key(claim):
    """Deterministic claim ordering: observatory > instrument > window > id.

    Mirrors the default DatasetUsage ordering of ``PaperDatasetUsagesView``.
    Deterministic order is fine for blinding: after deduplication the order
    carries no configuration signal.
    """
    rep = claim.representative
    instrument = rep.instrument
    observatory = instrument.observatory if instrument else None
    datasource = observatory.datasource if observatory else None
    return (
        (datasource.slug if datasource else '') or '',
        (observatory.short_name if observatory else '') or '',
        (instrument.short_name if instrument else '') or '',
        rep.start_lower or _EPOCH,
        rep.end_upper or _EPOCH,
        str(rep.id),
    )


def group_claims(usages):
    """Group an iterable of annotated DatasetUsages into ordered Claims."""
    groups = {}
    for usage in usages:
        groups.setdefault(claim_key(usage), []).append(usage)

    claims = []
    for members in groups.values():
        members = sorted(members, key=lambda du: str(du.id))
        claims.append(Claim(representative=members[0], members=members))
    claims.sort(key=_claim_sort_key)
    return claims


def get_paper_claims(campaign, paper_id):
    """All claims for one paper in a campaign, in deterministic order."""
    return group_claims(campaign_usages_queryset(campaign, paper_id=paper_id))


def resolve_claim(campaign, usage_id):
    """Resolve the full claim a DatasetUsage belongs to, or None.

    Returns None when the usage does not exist or does not participate in the
    campaign (wrong configuration or paper outside the campaign set).
    """
    try:
        target = campaign_usages_queryset(campaign).get(id=usage_id)
    except DatasetUsage.DoesNotExist:
        return None

    members = [
        du for du in campaign_usages_queryset(campaign, paper_id=target.paper_id)
        if claim_key(du) == claim_key(target)
    ]
    members = sorted(members, key=lambda du: str(du.id))
    return Claim(representative=members[0], members=members)
