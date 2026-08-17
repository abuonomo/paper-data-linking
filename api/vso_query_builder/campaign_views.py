"""API views for manual validation campaigns.

Deliberately separate from the legacy ``DatasetUsageValidationView``: campaign
review is blinded, so these endpoints must never reveal which configuration
produced a claim, the consensus status, or another reviewer's verdicts. The
legacy view returns ``consensus_status`` in its response and supports
anonymous voting — both wrong for a campaign.

Campaign definitions live in
``paper_data_linking.config.settings.VALIDATION_CAMPAIGNS`` (single source of
truth shared with the tagging/sampling management commands and the analysis
scripts).
"""

import logging

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from paper_data_linking.config.settings import get_validation_campaign

from .campaign_claims import get_paper_claims, group_claims, campaign_usages_queryset, resolve_claim
from .models import DatasetUsageValidation, Paper, recompute_consensus
from .serializers import SupportQuoteDetailSerializer

logger = logging.getLogger(__name__)


class CampaignAPIView(APIView):
    """Base view: resolves the campaign and enforces reviewer-only access."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_campaign_or_error(self, request, slug):
        """Return (campaign, None) or (None, error Response)."""
        campaign = get_validation_campaign(slug)
        if campaign is None:
            return None, Response(
                {"error": f"Unknown validation campaign: {slug}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        if request.user.username not in campaign.reviewers:
            return None, Response(
                {"error": "You are not a reviewer on this campaign"},
                status=status.HTTP_403_FORBIDDEN,
            )
        return campaign, None


def _my_validation_map(claims, user):
    """Map representative usage_id -> the user's validation row (or None).

    Propagation writes identical rows to every member DU, so checking the
    representative is equivalent to checking any member.
    """
    rep_ids = [claim.usage_id for claim in claims]
    rows = DatasetUsageValidation.objects.filter(
        dataset_usage_id__in=rep_ids, user=user,
    )
    by_usage = {row.dataset_usage_id: row for row in rows}
    return {claim.usage_id: by_usage.get(claim.usage_id) for claim in claims}


def _serialize_claim(claim, my_validation):
    """Blinded claim payload for the review interface.

    Mirrors the shape of ``DatasetUsageDetailSerializer`` closely enough for
    the streamlined interface, but excludes — by construction — everything
    that could unblind the reviewer: configuration name, analysis/model info,
    consensus status, other users' verdicts, and the member count (a
    two-member claim would reveal "both configs found it").
    """
    rep = claim.representative
    instrument = rep.instrument
    observatory = instrument.observatory if instrument else None

    # Union of supporting quotes across member DUs, deduplicated by
    # (text, page) so the same sentence found by both configurations is
    # shown once.
    quotes, seen = [], set()
    for member in claim.members:
        for quote in member.supporting_quotes.all():
            key = (quote.quote, quote.page_number)
            if key in seen:
                continue
            seen.add(key)
            quotes.append(quote)
    quotes.sort(key=lambda q: (q.page_number, q.y_coord_start, q.id))

    duration_hours = None
    if rep.start_lower and rep.end_upper:
        duration_hours = round((rep.end_upper - rep.start_lower).total_seconds() / 3600, 2)

    return {
        'id': str(rep.id),
        'paper': {
            'id': rep.paper.id,
            'bibcode': rep.paper.bibcode,
            'pdf_url': rep.paper.pdf.url if rep.paper.pdf else None,
        },
        'instrument': {
            'id': instrument.id,
            'short_name': instrument.short_name,
            'full_name': instrument.full_name,
            'display_name': instrument.display_name or instrument.short_name,
        } if instrument else None,
        'observatory': {
            'short_name': observatory.short_name,
            'name': observatory.name,
            'display_name': observatory.display_name or observatory.short_name,
        } if observatory else None,
        # Flat names too, matching PaperDatasetUsageListSerializer so queue
        # rendering works unchanged.
        'instrument_name': (instrument.display_name or instrument.short_name) if instrument else None,
        'instrument_full_name': instrument.full_name if instrument else None,
        'observatory_short_name': observatory.short_name if observatory else None,
        'observatory_name': (observatory.display_name or observatory.short_name) if observatory else None,
        'start_time': rep.start_lower.isoformat() if rep.start_lower else None,
        'end_time': rep.end_upper.isoformat() if rep.end_upper else None,
        'duration_hours': duration_hours,
        'supporting_quotes': SupportQuoteDetailSerializer(quotes, many=True).data,
        'my_validation_status': my_validation.validation_status if my_validation else None,
        'my_mission_correct': my_validation.mission_correct if my_validation else None,
        'my_instrument_correct': my_validation.instrument_correct if my_validation else None,
        'my_window_correct': my_validation.window_correct if my_validation else None,
        'my_validation_notes': my_validation.validation_notes if my_validation else None,
    }


class CampaignOverviewView(CampaignAPIView):
    """Per-reviewer campaign dashboard: sections, per-user progress, resume.

    Progress is computed from the requesting user's own validation rows only
    — never from consensus (which mixes historic/anonymous votes and would
    leak the co-reviewer's activity on overlap papers). Not cached: the page
    must reflect a vote made one second ago.
    """

    def get(self, request, slug):
        campaign, error = self.get_campaign_or_error(request, slug)
        if error:
            return error
        user = request.user

        # --- Calibration section (claim-level, from the frozen id list) ---
        calibration = {'total': 0, 'judged': 0, 'claims': []}
        calibration_ids = list(campaign.calibration_usage_ids)
        if calibration_ids:
            cal_usages = {
                str(du.id): du
                for du in campaign_usages_queryset(campaign).filter(id__in=calibration_ids)
            }
            judged_ids = set(
                str(u) for u in DatasetUsageValidation.objects.filter(
                    dataset_usage_id__in=calibration_ids, user=user,
                ).values_list('dataset_usage_id', flat=True)
            )
            for usage_id in calibration_ids:
                du = cal_usages.get(usage_id)
                if du is None:
                    logger.warning("Calibration usage %s not found in campaign %s", usage_id, slug)
                    continue
                calibration['claims'].append({
                    'usage_id': usage_id,
                    'paper_id': str(du.paper_id),
                    'judged': usage_id in judged_ids,
                })
            calibration['total'] = len(calibration['claims'])
            calibration['judged'] = sum(1 for c in calibration['claims'] if c['judged'])
        calibration_complete = (
            calibration['total'] > 0 and calibration['judged'] >= calibration['total']
        )

        # --- Bulk + overlap papers assigned to this reviewer ---
        my_tag = f"{campaign.tag_prefix}{user.username}"
        papers = list(
            Paper.objects.filter(tags__contains=[campaign.set_tag])
            .filter(tags__overlap=[my_tag, campaign.overlap_tag])
            .order_by('bibcode')
            .only('id', 'bibcode', 'title', 'tags')
        )

        # One pass over all campaign DUs for these papers, grouped to claims.
        usages_by_paper = {}
        for du in campaign_usages_queryset(campaign).filter(paper__in=papers):
            usages_by_paper.setdefault(du.paper_id, []).append(du)

        # Group every paper's claims first, then resolve the user's verdicts in
        # ONE query across all representative ids (a per-paper query here made
        # the overview ~96 round trips and noticeably slow in the UI).
        paper_claims = {}
        for paper in papers:
            claims = group_claims(usages_by_paper.get(paper.id, []))
            if not claims:
                # Neither campaign config asserted any data usage for this
                # paper — nothing to review, so keep it out of the queue.
                continue
            paper_claims[paper.id] = claims
        all_rep_ids = [c.usage_id for claims in paper_claims.values() for c in claims]
        judged_rep_ids = set(DatasetUsageValidation.objects.filter(
            dataset_usage_id__in=all_rep_ids, user=user,
        ).values_list('dataset_usage_id', flat=True))

        paper_rows = []
        for paper in papers:
            claims = paper_claims.get(paper.id)
            if not claims:
                continue
            judged = sum(1 for c in claims if c.usage_id in judged_rep_ids)
            resume_usage_id = next(
                (str(c.usage_id) for c in claims if c.usage_id not in judged_rep_ids), None,
            )
            paper_rows.append({
                'id': str(paper.id),
                'bibcode': paper.bibcode,
                'title': paper.title,
                'section': 'overlap' if campaign.overlap_tag in paper.tags else 'bulk',
                'total_claims': len(claims),
                'my_judged_claims': judged,
                'resume_usage_id': resume_usage_id,
            })

        # --- Resume pointer: calibration first, then first unfinished paper ---
        resume = None
        if not calibration_complete and calibration['total'] > 0:
            next_cal = next((c for c in calibration['claims'] if not c['judged']), None)
            if next_cal:
                resume = {'paper_id': next_cal['paper_id'], 'usage_id': next_cal['usage_id']}
        if resume is None:
            in_progress = [p for p in paper_rows if p['resume_usage_id'] and p['my_judged_claims'] > 0]
            not_started = [p for p in paper_rows if p['resume_usage_id'] and p['my_judged_claims'] == 0]
            target = (in_progress or not_started or [None])[0]
            if target:
                resume = {'paper_id': target['id'], 'usage_id': target['resume_usage_id']}

        total_claims = sum(p['total_claims'] for p in paper_rows)
        judged_claims = sum(p['my_judged_claims'] for p in paper_rows)
        return Response({
            'campaign': {
                'slug': campaign.slug,
                'calibration_size': campaign.calibration_size,
                'calibration_complete': calibration_complete,
                'started_at': campaign.started_at,
            },
            'calibration': calibration,
            'papers': paper_rows,
            'stats': {
                'total_claims': total_claims,
                'judged_claims': judged_claims,
                'calibration_total': calibration['total'],
                'calibration_judged': calibration['judged'],
            },
            'resume': resume,
        })


class CampaignPaperClaimsView(CampaignAPIView):
    """Blinded, deduplicated claim list for one paper in a campaign."""

    def get(self, request, slug, paper_id):
        campaign, error = self.get_campaign_or_error(request, slug)
        if error:
            return error
        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            return Response({"error": "Paper not found"}, status=status.HTTP_404_NOT_FOUND)
        if campaign.set_tag not in paper.tags:
            return Response(
                {"error": "Paper is not part of this campaign"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        claims = get_paper_claims(campaign, paper_id)
        my_map = _my_validation_map(claims, request.user)
        return Response([
            _serialize_claim(claim, my_map[claim.usage_id]) for claim in claims
        ])


class CampaignClaimValidationView(CampaignAPIView):
    """Submit a campaign verdict for a claim; propagates to all member DUs.

    Body: ``validation_status`` (approved | rejected | needs_review),
    ``mission_correct`` / ``instrument_correct`` / ``window_correct``
    (booleans; required for approved/rejected), ``validation_notes``
    (required for rejected — it is the rejection reason).
    """

    def post(self, request, slug, usage_id):
        campaign, error = self.get_campaign_or_error(request, slug)
        if error:
            return error

        verdict = request.data.get('validation_status')
        notes = (request.data.get('validation_notes') or '').strip()
        checks = {
            name: request.data.get(name)
            for name in ('mission_correct', 'instrument_correct', 'window_correct')
        }

        if verdict not in ('approved', 'rejected', 'needs_review'):
            return Response(
                {"error": "validation_status must be approved, rejected, or needs_review"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if verdict in ('approved', 'rejected'):
            bad = [name for name, value in checks.items() if not isinstance(value, bool)]
            if bad:
                return Response(
                    {"error": f"Boolean checkmarks required for {verdict} verdicts: {', '.join(bad)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if verdict == 'approved' and not all(checks.values()):
            return Response(
                {"error": "Approve requires all three checkmarks (mission, instrument, window)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if verdict == 'rejected' and not notes:
            return Response(
                {"error": "Reject requires validation_notes (the rejection reason)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        claim = resolve_claim(campaign, usage_id)
        if claim is None:
            return Response(
                {"error": "Dataset usage not found in this campaign"},
                status=status.HTTP_404_NOT_FOUND,
            )

        defaults = {
            'validation_status': verdict,
            'validation_notes': notes,
            'mission_correct': checks['mission_correct'] if isinstance(checks['mission_correct'], bool) else None,
            'instrument_correct': checks['instrument_correct'] if isinstance(checks['instrument_correct'], bool) else None,
            'window_correct': checks['window_correct'] if isinstance(checks['window_correct'], bool) else None,
        }
        # One transaction: a claim must never end up half-propagated.
        with transaction.atomic():
            for member in claim.members:
                DatasetUsageValidation.objects.update_or_create(
                    dataset_usage=member,
                    user=request.user,
                    defaults=defaults,
                )
                recompute_consensus(member)

        # Deliberately no consensus in the response (blinding).
        return Response({
            'claim_usage_id': str(claim.usage_id),
            'propagated_to': len(claim.members),
            'my_validation_status': verdict,
        })
