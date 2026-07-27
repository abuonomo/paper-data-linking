"""
Django management command to run the normalized workflow on papers with a different configuration.

This command helps identify papers that have been analyzed with one configuration (e.g., 'standard')
and run the complete normalized workflow on the same papers using a different configuration (e.g., 'budget').

Usage examples:
    # Run budget config on papers that have standard config analyses from the last 7 days
    python manage.py run_workflow_different_config --source-config standard --target-config budget --created-after 2025-08-15

    # Run standard config on specific papers by bibcode
    python manage.py run_workflow_different_config --source-config budget --target-config standard --bibcodes 2021SoPh..296...36B 2020ApJ...901..121C

    # Dry run to see what would happen without executing
    python manage.py run_workflow_different_config --source-config standard --target-config budget --created-after 2025-08-20 --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import datetime, timedelta
from vso_query_builder.models import PaperAnalysis, Paper
from vso_query_builder.tasks import run_batch_normalized_workflow


class Command(BaseCommand):
    help = 'Run normalized workflow on papers with a different configuration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source-config',
            type=str,
            required=True,
            choices=['standard', 'budget', 'super-budget', 'hybrid', 'bedrock-test', 'bedrock-gpt-oss-120b', 'bedrock-qwen3-235b'],
            help='Configuration name to search for existing analyses'
        )
        parser.add_argument(
            '--target-config',
            type=str,
            required=True,
            choices=['standard', 'budget', 'super-budget', 'hybrid', 'bedrock-test', 'bedrock-gpt-oss-120b', 'bedrock-qwen3-235b'],
            help='Configuration name to use for new workflow execution'
        )
        parser.add_argument(
            '--created-after',
            type=str,
            help='Only include analyses created after this date (YYYY-MM-DD format)'
        )
        parser.add_argument(
            '--created-before',
            type=str,
            help='Only include analyses created before this date (YYYY-MM-DD format)'
        )
        parser.add_argument(
            '--bibcodes',
            nargs='+',
            help='Specific paper bibcodes to process (space-separated)'
        )
        parser.add_argument(
            '--status',
            type=str,
            choices=['pending', 'processing', 'completed', 'failed'],
            default='completed',
            help='Only include analyses with this status (default: completed)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without executing the workflow'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Execute even if target configuration already exists for some papers'
        )

    def handle(self, *args, **options):
        source_config = options['source_config']
        target_config = options['target_config']
        
        if source_config == target_config:
            raise CommandError("Source and target configurations cannot be the same")

        # Build the query for source analyses
        query = PaperAnalysis.objects.filter(
            configuration_name=source_config,
            status=options['status']
        )

        # Apply date filters
        if options['created_after']:
            try:
                after_date = datetime.strptime(options['created_after'], '%Y-%m-%d').date()
                query = query.filter(created_at__date__gte=after_date)
            except ValueError:
                raise CommandError("Invalid date format for --created-after. Use YYYY-MM-DD")

        if options['created_before']:
            try:
                before_date = datetime.strptime(options['created_before'], '%Y-%m-%d').date()
                query = query.filter(created_at__date__lte=before_date)
            except ValueError:
                raise CommandError("Invalid date format for --created-before. Use YYYY-MM-DD")

        # Apply bibcode filter
        if options['bibcodes']:
            query = query.filter(paper__bibcode__in=options['bibcodes'])

        # Get the analyses and their papers
        source_analyses = query.select_related('paper')
        
        if not source_analyses.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"No PaperAnalysis objects found with configuration '{source_config}' "
                    f"matching the specified criteria."
                )
            )
            return

        # Extract unique papers
        papers = list(set(analysis.paper for analysis in source_analyses))
        paper_ids = [paper.id for paper in papers]

        self.stdout.write(
            self.style.SUCCESS(
                f"Found {len(source_analyses)} analyses with '{source_config}' config "
                f"covering {len(papers)} unique papers"
            )
        )

        # Check for existing target configuration analyses
        existing_target_analyses = PaperAnalysis.objects.filter(
            paper__id__in=paper_ids,
            configuration_name=target_config
        ).select_related('paper')

        if existing_target_analyses.exists():
            existing_papers = [analysis.paper.bibcode for analysis in existing_target_analyses]
            
            if not options['force']:
                self.stdout.write(
                    self.style.WARNING(
                        f"Warning: {len(existing_target_analyses)} papers already have '{target_config}' configuration:\n"
                        f"{', '.join(existing_papers[:10])}{'...' if len(existing_papers) > 10 else ''}\n"
                        f"Use --force to proceed anyway or filter out these papers."
                    )
                )
                
                if not options['dry_run']:
                    confirm = input("Continue anyway? [y/N]: ")
                    if confirm.lower() != 'y':
                        self.stdout.write("Aborted.")
                        return
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Forcing execution despite {len(existing_target_analyses)} existing '{target_config}' analyses"
                    )
                )

        # Display what will be processed
        self.stdout.write("\nPapers to be processed:")
        for i, paper in enumerate(papers[:20], 1):  # Show first 20
            self.stdout.write(f"  {i:2d}. {paper.bibcode}")
        
        if len(papers) > 20:
            self.stdout.write(f"  ... and {len(papers) - 20} more")

        self.stdout.write(
            f"\nWorkflow configuration: {target_config}"
        )

        # Dry run - just show what would happen
        if options['dry_run']:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n[DRY RUN] Would execute normalized workflow for {len(papers)} papers "
                    f"using '{target_config}' configuration.\n"
                    f"To execute, run the same command without --dry-run"
                )
            )
            return

        # Execute the workflow
        self.stdout.write(
            f"\nExecuting normalized workflow for {len(papers)} papers..."
        )

        # Convert UUIDs to strings for Celery
        paper_ids_str = [str(paper_id) for paper_id in paper_ids]

        # Start the batch normalized workflow task
        task = run_batch_normalized_workflow.delay(paper_ids_str, target_config)
        
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Successfully started normalized workflow with '{target_config}' configuration.\n"
                f"  Task ID: {task.id}\n"
                f"  Papers: {len(papers)}\n"
                f"  Configuration: {target_config}\n"
                f"  Monitor progress in Django admin or Celery logs."
            )
        )