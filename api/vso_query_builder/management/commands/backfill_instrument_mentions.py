"""
Backfill InstrumentMention rows for all existing PaperAnalysis records that have
normalized_instrument_details but no InstrumentMention rows yet.

Calls the same upsert logic used during live pipeline runs, so results are
identical to what a fresh run would produce. The operation is idempotent —
running it multiple times is safe.

Usage:
    python manage.py backfill_instrument_mentions
    python manage.py backfill_instrument_mentions --dry-run
    python manage.py backfill_instrument_mentions --limit 50
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Create InstrumentMention rows for all PaperAnalysis records that have normalized data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Count eligible analyses without making any changes',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Process at most N analyses (useful for incremental runs)',
        )

    def handle(self, *args, **options):
        from vso_query_builder.models import PaperAnalysis, InstrumentMention
        from vso_query_builder.tasks import (
            _upsert_instrument_mentions_from_normalized,
            _upsert_mission_only_from_llm_calls,
            _backfill_mission_only_from_input_messages,
        )

        dry_run = options['dry_run']
        limit = options['limit']

        # Analyses with normalized data that have no InstrumentMention rows yet
        candidates = (
            PaperAnalysis.objects
            .exclude(normalized_instrument_details__isnull=True)
            .exclude(normalized_instrument_details={})
            .exclude(instrument_mentions__isnull=False)
            .order_by('id')
        )

        total = candidates.count()
        self.stdout.write(f'Phase 1: Found {total} analyses without InstrumentMention rows')

        # Phase 2: mission-only rows from LLM call history (render_context path)
        llm_candidates = (
            PaperAnalysis.objects
            .filter(llm_calls__call_type='mission_selection')
            .distinct()
            .order_by('id')
        )
        llm_total = llm_candidates.count()
        self.stdout.write(f'Phase 2: Found {llm_total} analyses with mission_selection LLM calls')

        # Phase 3: input_messages fallback for pre-Oct-10 calls (render_context IS NULL)
        old_candidates = (
            PaperAnalysis.objects
            .filter(
                llm_calls__call_type='mission_selection',
                llm_calls__render_context__isnull=True,
            )
            .distinct()
            .order_by('id')
        )
        old_total = old_candidates.count()
        self.stdout.write(f'Phase 3: Found {old_total} analyses with null-render_context LLM calls')

        if dry_run:
            self.stdout.write(self.style.WARNING('[dry-run] No changes made.'))
            return

        # --- Phase 1 ---
        if limit:
            candidates = candidates[:limit]

        processed = 0
        mentions_created = 0

        for pa in candidates.iterator():
            try:
                created = _upsert_instrument_mentions_from_normalized(pa)
            except Exception as exc:
                self.stderr.write(f'  Error on PaperAnalysis {pa.id} ({pa.paper.bibcode}): {exc}')
                continue
            mentions_created += created
            processed += 1

            if processed % 50 == 0:
                self.stdout.write(f'  Phase 1: processed {processed} analyses...')

        self.stdout.write(self.style.SUCCESS(
            f'Phase 1 done. {processed} analyses, {mentions_created} InstrumentMention rows created.'
        ))

        # --- Phase 2 ---
        self.stdout.write('\nPhase 2: backfilling mission-only mentions from LLM call data...')
        llm_processed = 0
        llm_mentions_created = 0
        for pa in llm_candidates.iterator():
            try:
                created = _upsert_mission_only_from_llm_calls(pa)
            except Exception as exc:
                self.stderr.write(f'  Error on PaperAnalysis {pa.id}: {exc}')
                continue
            llm_mentions_created += created
            llm_processed += 1
            if llm_processed % 50 == 0:
                self.stdout.write(f'  Phase 2: processed {llm_processed} analyses...')

        self.stdout.write(self.style.SUCCESS(
            f'Phase 2 done. {llm_processed} analyses, {llm_mentions_created} mission-only rows created.'
        ))

        # --- Phase 3 ---
        self.stdout.write('\nPhase 3: backfilling mission-only mentions from input_messages (pre-Oct-10)...')
        old_processed = 0
        old_mentions_created = 0
        all_ambiguity_warnings = []

        for pa in old_candidates.iterator():
            try:
                created, warnings = _backfill_mission_only_from_input_messages(pa)
            except Exception as exc:
                self.stderr.write(f'  Error on PaperAnalysis {pa.id}: {exc}')
                continue
            old_mentions_created += created
            all_ambiguity_warnings.extend(warnings)
            old_processed += 1
            if old_processed % 50 == 0:
                self.stdout.write(f'  Phase 3: processed {old_processed} analyses...')

        self.stdout.write(self.style.SUCCESS(
            f'Phase 3 done. {old_processed} analyses, {old_mentions_created} mission-only rows created.'
        ))

        if all_ambiguity_warnings:
            self.stdout.write(self.style.WARNING(
                f'\n{len(all_ambiguity_warnings)} ambiguous observatory name(s) skipped (manual review needed):'
            ))
            for w in all_ambiguity_warnings:
                self.stdout.write(f'  {w}')
