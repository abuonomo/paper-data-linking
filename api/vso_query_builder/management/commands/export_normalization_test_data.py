import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from ...models import PaperAnalysis, Instrument, Observatory, DataSource
from paper_data_linking.config.paths import VSO_METADATA_JSONL


class Command(BaseCommand):
    help = 'Export normalization test data from production for prompt testing'

    # Define supported call types
    NORMALIZATION_CALL_TYPES = [
        'physobs_normalization',
        'wavelength_normalization',
        'time_normalization',
        'detector_normalization',
        'cadence_normalization',
        'instrument_validation',
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            '--call-type',
            type=str,
            action='append',
            dest='call_types',
            help='Call type(s) to export (can specify multiple times). Use --list-call-types to see available types.'
        )
        parser.add_argument(
            '--config',
            type=str,
            help='Configuration name to filter by (e.g., "budget", "standard")'
        )
        parser.add_argument(
            '--output',
            type=str,
            default='normalization_test_data.jsonl',
            help='Output JSONL file path (default: normalization_test_data.jsonl)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit number of test cases to export per call type'
        )
        parser.add_argument(
            '--list-call-types',
            action='store_true',
            help='List available call types and exit'
        )

    def handle(self, *args, **options):
        # Handle listing option
        if options['list_call_types']:
            self.list_call_types()
            return

        # Validate call types
        requested_call_types = options.get('call_types') or self.NORMALIZATION_CALL_TYPES
        invalid_types = [ct for ct in requested_call_types if ct not in self.NORMALIZATION_CALL_TYPES]
        if invalid_types:
            self.stdout.write(self.style.ERROR(f"Invalid call types: {', '.join(invalid_types)}"))
            self.stdout.write(f"Available types: {', '.join(self.NORMALIZATION_CALL_TYPES)}")
            return

        # Query PaperAnalysis records
        filters = Q(status='completed', normalized_instrument_details__isnull=False)

        if options['config']:
            filters &= Q(configuration_name=options['config'])
            self.stdout.write(f"Filtering by configuration: {options['config']}")

        queryset = PaperAnalysis.objects.filter(filters).select_related('paper').order_by('created_at')
        total_count = queryset.count()

        if total_count == 0:
            self.stdout.write(self.style.WARNING("No records found matching the specified filters"))
            return

        self.stdout.write(f"Found {total_count} PaperAnalysis records with normalized data")

        # Extract test cases
        all_test_cases = []

        for call_type in requested_call_types:
            self.stdout.write(f"\nExtracting test cases for: {call_type}")

            call_type_cases = []
            for pa in queryset.iterator(chunk_size=100):
                cases = self.extract_test_cases(pa, call_type)
                call_type_cases.extend(cases)

                # Apply limit if specified
                if options['limit'] and len(call_type_cases) >= options['limit']:
                    call_type_cases = call_type_cases[:options['limit']]
                    break

            self.stdout.write(f"  Extracted {len(call_type_cases)} test cases for {call_type}")
            all_test_cases.extend(call_type_cases)

        if not all_test_cases:
            self.stdout.write(self.style.WARNING("No test cases extracted"))
            return

        # Export to JSONL
        output_file = options['output']
        try:
            with open(output_file, 'w') as f:
                for case in all_test_cases:
                    f.write(json.dumps(case, default=str) + '\n')

            self.stdout.write(
                self.style.SUCCESS(f"\nSuccessfully exported {len(all_test_cases)} test cases to {output_file}")
            )

            # Print summary by call type
            from collections import Counter
            call_type_counts = Counter(case['call_type'] for case in all_test_cases)
            self.stdout.write("\nBreakdown by call type:")
            for call_type, count in call_type_counts.items():
                self.stdout.write(f"  {call_type}: {count}")

        except Exception as e:
            raise CommandError(f"Error writing to {output_file}: {e}")

    def list_call_types(self):
        """List all available call types"""
        self.stdout.write("Available call types:")
        for call_type in self.NORMALIZATION_CALL_TYPES:
            self.stdout.write(f"  - {call_type}")

    def extract_test_cases(self, paper_analysis: PaperAnalysis, call_type: str) -> List[Dict]:
        """Extract test cases of specified type from a PaperAnalysis"""
        if call_type == 'instrument_validation':
            return self.extract_validation_cases(paper_analysis)
        else:
            return self.extract_normalization_cases(paper_analysis, call_type)

    def extract_normalization_cases(self, paper_analysis: PaperAnalysis, call_type: str) -> List[Dict]:
        """Extract normalization test cases (physobs, wavelength, time, detector, cadence)"""
        cases = []
        norm_json = paper_analysis.normalized_instrument_details

        if not norm_json or 'instruments' not in norm_json:
            return cases

        # Map call types to field names
        field_map = {
            'physobs_normalization': 'physical_observable',
            'wavelength_normalization': 'wavelengths',
            'time_normalization': 'time_range',
            'detector_normalization': 'detector',
            'cadence_normalization': 'cadence',
        }

        field_name = field_map.get(call_type)
        if not field_name:
            return cases

        for inst_idx, instrument in enumerate(norm_json.get('instruments', [])):
            # Get instrument code for metadata lookup
            inst_code = instrument.get('name', {}).get('normalized', {}).get('matched_instrument_code')
            mission_code = instrument.get('name', {}).get('normalized', {}).get('matched_mission_code')
            data_system = instrument.get('name', {}).get('normalized', {}).get('data_system')

            if not inst_code:
                continue

            # Get canonical instrument for context
            canonical_instrument = self.get_canonical_instrument(inst_code, mission_code, data_system)

            for period_idx, period in enumerate(instrument.get('data_collection_periods', [])):
                # Check if this field exists in the period
                if field_name not in period:
                    continue

                field_data = period[field_name]

                # Skip if no normalization occurred
                if not isinstance(field_data, dict) or 'original' not in field_data or 'normalized' not in field_data:
                    continue

                # Build test case
                test_case = {
                    'case_id': str(uuid.uuid4()),
                    'paper_bibcode': paper_analysis.paper.bibcode,
                    'call_type': call_type,
                    'raw_inputs': self.get_raw_inputs(call_type, field_data['original']),
                    'canonical_instrument': canonical_instrument,
                    'expected_output': field_data['normalized'],
                    'provenance': {
                        'paper_analysis_id': str(paper_analysis.id),
                        'instrument_index': inst_idx,
                        'period_index': period_idx,
                        'configuration_name': paper_analysis.configuration_name,
                    }
                }

                # Add VSO metadata for call types that need candidates
                if call_type in ['physobs_normalization', 'detector_normalization']:
                    test_case['vso_metadata'] = self.get_vso_metadata(inst_code, call_type)

                cases.append(test_case)

        return cases

    def extract_validation_cases(self, paper_analysis: PaperAnalysis) -> List[Dict]:
        """Extract instrument validation test cases"""
        cases = []

        # Need both structured and normalized data
        structured = paper_analysis.structured_instruments_details
        normalized = paper_analysis.normalized_instrument_details

        if not structured or not normalized:
            return cases

        if 'instruments' not in structured or 'instruments' not in normalized:
            return cases

        # Match structured entries with normalized entries by index
        for inst_idx, (struct_inst, norm_inst) in enumerate(zip(
            structured.get('instruments', []),
            normalized.get('instruments', [])
        )):
            # Get original instrument entry
            original_name = struct_inst.get('name', '')
            original_comments = struct_inst.get('general_comments', '')

            # Get matched instrument from normalized data
            norm_name = norm_inst.get('name', {}).get('normalized', {})
            matched_instrument_code = norm_name.get('matched_instrument_code')
            matched_mission_code = norm_name.get('matched_mission_code')
            data_system = norm_name.get('data_system')

            if not matched_instrument_code or not matched_mission_code:
                continue

            # Get canonical instrument details
            canonical_instrument = self.get_canonical_instrument(
                matched_instrument_code,
                matched_mission_code,
                data_system
            )

            if not canonical_instrument:
                continue

            # Extract time and observable info from first period if available
            time_info = ""
            obs_info = ""
            periods = struct_inst.get('data_collection_periods', [])
            if periods:
                first_period = periods[0]
                if first_period.get('time_range'):
                    time_info = f"Time period: {first_period['time_range']}"
                if first_period.get('physical_observable'):
                    obs_info = f"Observes: {first_period['physical_observable']}"

            test_case = {
                'case_id': str(uuid.uuid4()),
                'paper_bibcode': paper_analysis.paper.bibcode,
                'call_type': 'instrument_validation',
                'raw_inputs': {
                    'original_name': original_name,
                    'original_comments': original_comments,
                    'time_info': time_info,
                    'obs_info': obs_info,
                },
                'canonical_instrument': canonical_instrument,
                'expected_output': {
                    'decision': 'valid',  # If it's in normalized data, it passed validation
                },
                'provenance': {
                    'paper_analysis_id': str(paper_analysis.id),
                    'instrument_index': inst_idx,
                    'configuration_name': paper_analysis.configuration_name,
                }
            }

            cases.append(test_case)

        return cases

    def get_raw_inputs(self, call_type: str, original_text: str) -> Dict:
        """Format raw inputs based on call type"""
        input_map = {
            'physobs_normalization': {'raw_observable': original_text},
            'wavelength_normalization': {'raw_wavelength': original_text},
            'time_normalization': {'raw_time': original_text},
            'detector_normalization': {'raw_detector': original_text},
            'cadence_normalization': {'raw_cadence': original_text},
        }
        return input_map.get(call_type, {'raw_input': original_text})

    def get_canonical_instrument(self, instrument_code: str, mission_code: str, data_system: str) -> Optional[Dict]:
        """Get canonical instrument details from database"""
        try:
            # Find the instrument by code and mission
            instrument = Instrument.objects.select_related('observatory__datasource').get(
                short_name=instrument_code,
                observatory__short_name=mission_code
            )

            return {
                'id': str(instrument.id),
                'code': instrument.short_name,
                'full_name': instrument.full_name,
                'observatory_code': instrument.observatory.short_name,
                'observatory_name': instrument.observatory.name,
                'datasource': instrument.observatory.datasource.slug if instrument.observatory.datasource else data_system,
            }
        except Instrument.DoesNotExist:
            self.stdout.write(self.style.WARNING(
                f"Warning: Instrument not found in catalog: {instrument_code}/{mission_code}"
            ))
            return None
        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f"Warning: Error fetching instrument {instrument_code}/{mission_code}: {e}"
            ))
            return None

    def get_vso_metadata(self, instrument_code: str, call_type: str) -> Dict:
        """Get VSO metadata (valid candidates) for instrument"""
        metadata = {}

        if not VSO_METADATA_JSONL.exists():
            return metadata

        try:
            candidates = set()
            with open(VSO_METADATA_JSONL, 'r', encoding='utf-8') as f:
                for line in f:
                    entry = json.loads(line)
                    if entry.get('instrument') == instrument_code:
                        if call_type == 'physobs_normalization':
                            if entry.get('physobs'):
                                candidates.add(entry['physobs'])
                        elif call_type == 'detector_normalization':
                            if entry.get('detector'):
                                candidates.add(entry['detector'])

            if call_type == 'physobs_normalization':
                metadata['valid_physobs_candidates'] = sorted(candidates)
            elif call_type == 'detector_normalization':
                metadata['valid_detector_candidates'] = sorted(candidates)

        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f"Warning: Error reading VSO metadata for {instrument_code}: {e}"
            ))

        return metadata
