"""
Backfill mission validation on existing mission_only InstrumentMention rows.

For each mission-only stub, runs the new mission validation LLM call. If the
mission fails validation, deletes the InstrumentMention AND removes the
corresponding entry from normalized_instrument_details so it won't be recreated.

Usage:
    python manage.py validate_mission_only_mentions --dry-run
    python manage.py validate_mission_only_mentions
    python manage.py validate_mission_only_mentions --limit 100
"""
import copy
import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Run mission validation on existing mission_only InstrumentMention rows. '
        'Deletes stubs that fail validation and cleans normalized_instrument_details.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be deleted without making changes',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit the number of mentions to process',
        )
        parser.add_argument(
            '--config',
            type=str,
            default='standard',
            help='LLM config profile name (default: "standard")',
        )

    def handle(self, *args, **options):
        from vso_query_builder.models import InstrumentMention, PaperAnalysis
        from vso_query_builder.finders import DjangoInstrumentFinder
        from vso_query_builder.clients import DjangoLiteLLMClient
        from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder
        from paper_data_linking.linkers.general.catalogue_models import Mission
        from paper_data_linking.config.settings import get_llm_configuration

        dry_run = options['dry_run']
        limit = options['limit']
        config_name = options['config']

        llm_config = get_llm_configuration(config_name)
        self.stdout.write(f'Using config: {config_name}')
        val_config = llm_config.instrument_grounding.mission_validation or llm_config.instrument_grounding.validation
        self.stdout.write(f'Mission validation model: {val_config.model}')

        finder = DjangoInstrumentFinder()
        llm_client = DjangoLiteLLMClient()
        grounder = InstrumentGrounder(finder=finder, llm_client=llm_client, llm_config=llm_config)

        mentions = (
            InstrumentMention.objects
            .filter(match_level=InstrumentMention.MATCH_LEVEL_MISSION_ONLY)
            .select_related('paper_analysis__paper', 'matched_observatory__datasource')
            .order_by('paper_analysis_id')
        )

        total = mentions.count()
        self.stdout.write(f'Found {total} mission_only InstrumentMention rows')

        if limit:
            mentions = mentions[:limit]
            self.stdout.write(f'Processing first {limit}')

        validated = 0
        invalidated = 0
        errors = 0

        for mention in mentions.iterator():
            pa = mention.paper_analysis
            obs = mention.matched_observatory
            if not obs:
                continue

            # Build instrument_entry from normalized_instrument_details
            instrument_entry = self._find_instrument_entry(pa, obs)
            if not instrument_entry:
                # Fallback: build minimal entry from the paper analysis instruments_details
                instrument_entry = {
                    'name': obs.name,
                    'general_comments': (pa.instruments_details or '')[:500],
                    'data_collection_periods': [],
                }
                self.stdout.write(
                    f'  NOTE: No normalized JSON match for {obs.name} / '
                    f'{pa.paper.bibcode} — using fallback context'
                )

            # Build Mission object for validation
            # Get data_system from the observatory's datasource
            data_system = obs.datasource.slug if obs.datasource_id else 'vso'
            mission_obj = Mission(
                mission_code=obs.short_name,
                mission_name=obs.name,
                data_system=data_system,
                description=obs.description or None,
            )

            if dry_run:
                # In dry-run, just report what we'd validate
                self.stdout.write(
                    f'  WOULD VALIDATE: {obs.name} for {pa.paper.bibcode}'
                )
                continue

            # Run validation
            try:
                is_valid = grounder._validate_single_mission(instrument_entry, mission_obj)
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'  ERROR validating {obs.name} for {pa.paper.bibcode}: {e}'
                    )
                )
                errors += 1
                continue

            if is_valid:
                validated += 1
                self.stdout.write(
                    f'  VALID: {obs.name} for {pa.paper.bibcode}'
                )
            else:
                invalidated += 1
                self.stdout.write(
                    f'  INVALID — deleting: {obs.name} for {pa.paper.bibcode}'
                )
                # Delete the mention
                mention.delete()
                # Clean the normalized JSON
                self._remove_from_normalized(pa, obs)

        self.stdout.write('')
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] Would validate {mentions.count() if limit else total} mentions. '
                f'Re-run without --dry-run to apply.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Done. validated={validated}, invalidated={invalidated}, errors={errors}'
            ))

    def _find_instrument_entry(self, pa, obs):
        """
        Find the instrument entry in normalized_instrument_details that matches
        this mission-only mention, and convert it to the flat dict format that
        _validate_single_mission expects.

        The grounder expects: {"name": "string", "general_comments": "string",
        "data_collection_periods": [...]}

        But normalized JSON has: {"name": {"original": "...", "normalized": {...}},
        "general_comments": "...", "data_collection_periods": [...]}
        """
        normalized = pa.normalized_instrument_details
        if not normalized or 'instruments' not in normalized:
            return None

        obs_code = (obs.short_name or '').upper()
        obs_name = (obs.name or '').upper()

        for inst in normalized['instruments']:
            name_obj = inst.get('name', {})
            name_norm = name_obj.get('normalized', {}) if isinstance(name_obj, dict) else {}
            inst_code = name_norm.get('matched_instrument_code')
            mission_code = (name_norm.get('matched_mission_code') or '').upper()
            mission_name = (name_norm.get('matched_mission_name') or '').upper()

            # Match: same mission (by code or name), no instrument (mission-only)
            if not inst_code and (mission_code == obs_code or mission_name == obs_name or
                                  mission_code in obs_code or obs_code in mission_code):
                # Convert to the flat format the grounder expects
                original_name = name_obj.get('original', '') if isinstance(name_obj, dict) else str(name_obj)

                # Flatten data_collection_periods from normalized format
                flat_periods = []
                for period in inst.get('data_collection_periods', []):
                    flat = {}
                    tr = period.get('time_range', {})
                    if isinstance(tr, dict):
                        flat['time_range'] = tr.get('original', '')
                    else:
                        flat['time_range'] = str(tr) if tr else ''

                    wo = period.get('wavelengths_or_instantaneous_range', period.get('wavelengths', {}))
                    if isinstance(wo, dict):
                        flat['wavelengths'] = wo.get('original', '')
                    else:
                        flat['wavelengths'] = str(wo) if wo else ''

                    po = period.get('physical_observable', {})
                    if isinstance(po, dict):
                        flat['physical_observable'] = po.get('original', '')
                    else:
                        flat['physical_observable'] = str(po) if po else ''

                    flat['additional_comments'] = period.get('additional_comments', '')
                    flat_periods.append(flat)

                return {
                    'name': original_name,
                    'general_comments': inst.get('general_comments', ''),
                    'data_collection_periods': flat_periods,
                }

        return None

    def _remove_from_normalized(self, pa, obs):
        """Remove the mission-only entry from normalized_instrument_details and save."""
        normalized = pa.normalized_instrument_details
        if not normalized or 'instruments' not in normalized:
            return

        obs_code = (obs.short_name or '').upper()
        obs_name = (obs.name or '').upper()
        original_count = len(normalized['instruments'])

        def _matches_observatory(inst):
            name_norm = inst.get('name', {}).get('normalized', {}) if isinstance(inst.get('name'), dict) else {}
            inst_code = name_norm.get('matched_instrument_code')
            mission_code = (name_norm.get('matched_mission_code') or '').upper()
            mission_name = (name_norm.get('matched_mission_name') or '').upper()
            if inst_code:
                return False  # Not a mission-only entry
            return (mission_code == obs_code or mission_name == obs_name or
                    mission_code in obs_code or obs_code in mission_code)

        updated = copy.deepcopy(normalized)
        updated['instruments'] = [
            inst for inst in updated['instruments']
            if not _matches_observatory(inst)
        ]

        removed_count = original_count - len(updated['instruments'])
        if removed_count > 0:
            pa.normalized_instrument_details = updated
            pa.save(update_fields=['normalized_instrument_details'])
            logger.info(
                f'Removed {removed_count} mission-only entries from '
                f'normalized_instrument_details for PA {pa.id}'
            )
