import json
import os
from django.utils.dateparse import parse_datetime
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from ...models import LLMCall, PaperAnalysis


class Command(BaseCommand):
    help = 'Export LLM calls to JSONL format with configurable filters'

    def add_arguments(self, parser):
        parser.add_argument(
            '--config',
            type=str,
            help='Configuration name to filter by (e.g., "budget", "standard")'
        )
        parser.add_argument(
            '--call-type',
            type=str,
            help='LLM call type to filter by (e.g., "time_normalization", "paper_analysis")'
        )
        parser.add_argument(
            '--output',
            type=str,
            default='llm_calls_export.jsonl',
            help='Output JSONL file path (default: llm_calls_export.jsonl)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit number of records to export'
        )
        parser.add_argument(
            '--list-configs',
            action='store_true',
            help='List available configuration names and exit'
        )
        parser.add_argument(
            '--list-call-types',
            action='store_true',
            help='List available call types and exit'
        )
        parser.add_argument(
            '--require-render-context',
            action='store_true',
            help='Only export calls that have a non-null render_context'
        )
        parser.add_argument(
            '--created-after',
            type=str,
            help='Only export calls created after this ISO timestamp (e.g., 2025-10-10T00:00:00)'
        )
        parser.add_argument(
            '--created-before',
            type=str,
            help='Only export calls created before this ISO timestamp (e.g., 2025-10-10T23:59:59)'
        )
        parser.add_argument(
            '--paper-tags',
            type=str,
            nargs='+',
            help='Filter by paper tags (e.g., "test_set_2025_11_26"). Can specify multiple tags.'
        )

    def handle(self, *args, **options):
        # Handle listing options
        if options['list_configs']:
            self.list_configurations()
            return
        
        if options['list_call_types']:
            self.list_call_types()
            return

        # Build query filters
        filters = Q()
        
        # Filter by configuration if specified
        if options['config']:
            config_filter = Q(paper_analyses__configuration_name=options['config'])
            filters &= config_filter
            self.stdout.write(f"Filtering by configuration: {options['config']}")
        
        # Filter by call type if specified
        if options['call_type']:
            call_type_filter = Q(call_type=options['call_type'])
            filters &= call_type_filter
            self.stdout.write(f"Filtering by call type: {options['call_type']}")

        # Optional created_at range filters
        created_after = options.get('created_after')
        created_before = options.get('created_before')
        if created_after:
            dt = parse_datetime(created_after)
            if not dt:
                raise CommandError(f"Invalid --created-after datetime: {created_after}")
            filters &= Q(created_at__gte=dt)
            self.stdout.write(f"Filtering created_at >= {created_after}")
        if created_before:
            dt = parse_datetime(created_before)
            if not dt:
                raise CommandError(f"Invalid --created-before datetime: {created_before}")
            filters &= Q(created_at__lte=dt)
            self.stdout.write(f"Filtering created_at <= {created_before}")

        # Optional render_context presence filter
        if options.get('require_render_context'):
            filters &= Q(render_context__isnull=False)
            self.stdout.write("Filtering to calls with render_context present")

        # Filter by paper tags if specified
        if options.get('paper_tags'):
            tags = options['paper_tags']
            # For each tag, filter papers that contain it in their tags JSON array
            tag_filter = Q()
            for tag in tags:
                tag_filter |= Q(paper_analyses__paper__tags__contains=[tag])
            filters &= tag_filter
            self.stdout.write(f"Filtering by paper tags: {', '.join(tags)}")

        # Get queryset
        queryset = LLMCall.objects.filter(filters).distinct().order_by('created_at')

        if options['config'] or options.get('paper_tags'):
            # Prefetch related analyses for configuration or paper tag filtering
            queryset = queryset.prefetch_related('paper_analyses')

        # Apply limit if specified
        if options['limit']:
            queryset = queryset[:options['limit']]
            self.stdout.write(f"Limiting to {options['limit']} records")

        # Count total records
        total_count = queryset.count()
        self.stdout.write(f"Found {total_count} LLM calls matching filters")
        
        if total_count == 0:
            self.stdout.write(self.style.WARNING("No records found matching the specified filters"))
            return

        # Export to JSONL
        output_file = options['output']
        
        try:
            with open(output_file, 'w') as f:
                for i, call in enumerate(queryset.iterator(chunk_size=100), 1):
                    record = self.serialize_llm_call(call)
                    f.write(json.dumps(record, default=str) + '\n')
                    
                    if i % 100 == 0:
                        self.stdout.write(f"Exported {i}/{total_count} records...")

            self.stdout.write(
                self.style.SUCCESS(f"Successfully exported {total_count} LLM calls to {output_file}")
            )
            
            # Show file size
            file_size = os.path.getsize(output_file)
            self.stdout.write(f"File size: {file_size / 1024 / 1024:.2f} MB")

        except Exception as e:
            raise CommandError(f"Error writing to {output_file}: {e}")

    def serialize_llm_call(self, call):
        """Serialize an LLMCall instance to a dictionary"""
        # Get associated paper analysis configs
        analysis_configs = list(
            call.paper_analyses.values_list('configuration_name', flat=True).distinct()
        ) if hasattr(call, 'paper_analyses') else []
        
        # Get associated paper bibcodes
        paper_bibcodes = list(
            call.paper_analyses.values_list('paper__bibcode', flat=True).distinct()
        ) if hasattr(call, 'paper_analyses') else []

        record = {
            'id': str(call.id),
            'created_at': call.created_at.isoformat(),
            'call_type': call.call_type,
            'model_name': call.model_name,
            'provider': call.provider,
            'prompt_tokens': call.prompt_tokens,
            'completion_tokens': call.completion_tokens,
            'total_tokens': call.total_tokens,
            'estimated_cost_usd': float(call.estimated_cost_usd) if call.estimated_cost_usd is not None else None,
            'duration_ms': call.duration_ms,
            'metadata': call.metadata,
            # Include render_context for re-rendering prompts in experiments
            'render_context': call.render_context,
            'analysis_configs': analysis_configs,
            'paper_bibcodes': paper_bibcodes,
            'input_messages': call.input_messages,
            'output_content': call.output_content,
        }

        return record

    def list_configurations(self):
        """List all available configuration names"""
        configs = PaperAnalysis.objects.values_list(
            'configuration_name', flat=True
        ).distinct().order_by('configuration_name')
        
        self.stdout.write("Available configuration names:")
        for config in configs:
            if config:
                self.stdout.write(f"  - {config}")
            else:
                self.stdout.write("  - (null/legacy)")

    def list_call_types(self):
        """List all available call types"""
        call_types = LLMCall.objects.values_list(
            'call_type', flat=True
        ).distinct().order_by('call_type')
        
        self.stdout.write("Available call types:")
        for call_type in call_types:
            count = LLMCall.objects.filter(call_type=call_type).count()
            self.stdout.write(f"  - {call_type} ({count} calls)")
