"""
Delete mission_only InstrumentMention rows that were created solely from
mission_identification LLM calls (not backed by any mission_selection call).

mission_identification is an early-stage filtering/ranking step that should
never have persisted InstrumentMention rows. This command identifies and
removes the bogus rows.

Usage:
    python manage.py cleanup_mission_identification_mentions
    python manage.py cleanup_mission_identification_mentions --dry-run
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Delete mission_only InstrumentMention rows sourced only from '
        'mission_identification (not backed by mission_selection)'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List rows that would be deleted without making changes',
        )

    def handle(self, *args, **options):
        from vso_query_builder.models import InstrumentMention, PaperAnalysis
        import re

        dry_run = options['dry_run']

        # Find all mission_only mentions
        mission_only_mentions = InstrumentMention.objects.filter(
            match_level=InstrumentMention.MATCH_LEVEL_MISSION_ONLY,
        ).select_related('paper_analysis__paper', 'matched_observatory')

        total = mission_only_mentions.count()
        self.stdout.write(f'Found {total} mission_only InstrumentMention rows to check')

        def _get_selected_observatories_from_selection_calls(pa):
            """Return set of observatory short_names selected by mission_selection calls."""
            selected = set()

            # From render_context (newer calls)
            for call in pa.llm_calls.filter(call_type='mission_selection'):
                candidates_text = (call.render_context or {}).get('candidates_text', '')
                candidates = {}
                for line in (candidates_text or '').strip().splitlines():
                    m = re.match(r'^(\d+)\.\s+(\S+)\s+\((.+)\)\s*$', line.strip())
                    if m:
                        candidates[int(m.group(1))] = m.group(2)

                output = call.output_content or ''
                if output.strip().upper() == 'UNKNOWN':
                    continue
                for idx_str in re.findall(r'\b([1-9]\d*)\b', output):
                    idx = int(idx_str)
                    if idx in candidates:
                        selected.add(candidates[idx].upper())

            # From input_messages (older calls with null render_context)
            for call in pa.llm_calls.filter(
                call_type='mission_selection',
                render_context__isnull=True,
            ):
                user_msg = next(
                    (m.get('content', '') for m in (call.input_messages or [])
                     if m.get('role') == 'user'),
                    '',
                )
                match = re.search(
                    r'<candidate_missions>(.*?)</candidate_missions>',
                    user_msg, re.DOTALL,
                )
                if not match:
                    continue
                candidates = {}
                for line in match.group(1).strip().splitlines():
                    m = re.match(r'^(\d+)\.\s+(.+)$', line.strip())
                    if m:
                        candidates[int(m.group(1))] = m.group(2).strip()

                output = call.output_content or ''
                if output.strip().upper() == 'UNKNOWN':
                    continue
                for idx_str in re.findall(r'\b([1-9]\d*)\b', output):
                    idx = int(idx_str)
                    if idx in candidates:
                        selected.add(candidates[idx].upper())

            return selected

        to_delete = []

        for mention in mission_only_mentions.iterator():
            pa = mention.paper_analysis
            obs = mention.matched_observatory
            if not obs:
                continue

            selected = _get_selected_observatories_from_selection_calls(pa)
            obs_name_upper = (obs.short_name or '').upper()
            obs_full_name_upper = (obs.name or '').upper()

            # Keep if this observatory was selected by a mission_selection call
            if obs_name_upper in selected or obs_full_name_upper in selected:
                continue

            to_delete.append(mention)
            bibcode = pa.paper.bibcode if pa.paper else '?'
            self.stdout.write(
                f'  {"[DRY-RUN] " if dry_run else ""}DELETE: '
                f'InstrumentMention id={mention.id}, '
                f'observatory={obs.short_name}, '
                f'bibcode={bibcode}, '
                f'pa_id={pa.id}'
            )

        if not to_delete:
            self.stdout.write(self.style.SUCCESS('No bogus rows found.'))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] Would delete {len(to_delete)} rows. '
                f'Re-run without --dry-run to apply.'
            ))
        else:
            ids = [m.id for m in to_delete]
            deleted_count, _ = InstrumentMention.objects.filter(id__in=ids).delete()
            self.stdout.write(self.style.SUCCESS(
                f'Deleted {deleted_count} bogus mission_only InstrumentMention rows.'
            ))
