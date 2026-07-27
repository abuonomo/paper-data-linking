"""
Management command to fix malformed SupportQuote parameter fields and re-link them to DatasetUsages.

Background:
- Older SupportQuotes have parameter fields like "Long period name:physobs" that got truncated
- This broke the linking logic between SupportQuotes and DatasetUsages
- This command fixes the parameter field to use semantic categories (time, wavelength, physobs, general)
- Then re-links the quotes to DatasetUsages

Usage:
    python manage.py fix_support_quote_parameters --dry-run  # See what would be fixed
    python manage.py fix_support_quote_parameters            # Fix the data
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from vso_query_builder.models import SupportQuote, DatasetUsage, PaperAnalysis
from vso_query_builder.quote_categorization import create_categorized_quote_usage_links
import re
from tqdm import tqdm


class Command(BaseCommand):
    help = 'Fix malformed SupportQuote parameter fields and re-link them to DatasetUsages'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Number of quotes to process in each batch (default: 1000)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        batch_size = options['batch_size']

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))

        self.stdout.write("=" * 80)
        self.stdout.write("Step 1: Fixing malformed SupportQuote parameter fields")
        self.stdout.write("=" * 80)

        fixed_quotes = self.fix_quote_parameters(dry_run, batch_size)

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("Step 2: Re-linking SupportQuotes to DatasetUsages")
        self.stdout.write("=" * 80)

        linked_usages = self.relink_dataset_usages(dry_run, batch_size)

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("SUMMARY")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Fixed parameter fields: {fixed_quotes}")
        self.stdout.write(f"Re-linked DatasetUsages: {linked_usages}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nThis was a DRY RUN. Run without --dry-run to apply changes."))

    def fix_quote_parameters(self, dry_run, batch_size):
        """Fix malformed parameter fields in SupportQuotes"""

        # Valid semantic categories
        valid_categories = ['time', 'wavelength', 'physobs', 'general']

        # Find quotes with malformed parameters
        # These are quotes where parameter is NOT in the valid categories
        # and also not in the legacy capitalized versions
        all_quotes = SupportQuote.objects.exclude(
            parameter__in=valid_categories + ['Time', 'Wavelength', 'Physobs', 'Physical Observable', 'General Comments']
        ).order_by('id')

        total_malformed = all_quotes.count()

        if total_malformed == 0:
            self.stdout.write(self.style.SUCCESS("No malformed parameter fields found!"))
            return 0

        self.stdout.write(f"Found {total_malformed} quotes with malformed parameter fields")

        # Show examples
        self.stdout.write("\nExamples of malformed parameters:")
        sample_quotes = all_quotes[:5]
        for quote in sample_quotes:
            self.stdout.write(f"  ID {quote.id}: parameter='{quote.parameter[:80]}'")

        if dry_run:
            self.stdout.write(self.style.WARNING(f"\n[DRY RUN] Would fix {total_malformed} quotes"))
            return total_malformed

        # Fix the parameter fields in batches
        self.stdout.write(f"\nFixing {total_malformed} quotes in batches of {batch_size}...")

        fixed_count = 0

        # Process in batches for memory efficiency
        for offset in tqdm(range(0, total_malformed, batch_size), desc="Processing batches"):
            batch = all_quotes[offset:offset + batch_size]

            with transaction.atomic():
                for quote in batch:
                    old_param = quote.parameter
                    new_param = self._extract_category_from_parameter(old_param)

                    if new_param != old_param:
                        quote.parameter = new_param
                        quote.save(update_fields=['parameter'])
                        fixed_count += 1

        self.stdout.write(self.style.SUCCESS(f"\n✓ Fixed {fixed_count} quotes"))
        return fixed_count

    def _extract_category_from_parameter(self, parameter):
        """
        Extract semantic category from a malformed parameter string.

        Examples:
            "Long period name:physobs" -> "physobs"
            "Data Collection Period 1:time" -> "time"
            "Some random text" -> "general"
            "Time, Physobs, Wavelength" -> "general" (multiple categories, treat as general)
        """
        # Check for category at the end after a colon
        if ':' in parameter:
            potential_category = parameter.split(':')[-1].strip().lower()
            if potential_category in ['time', 'wavelength', 'physobs', 'general']:
                return potential_category

        # Check if it contains multiple categories (comma-separated) - these are general
        param_lower = parameter.lower()
        category_count = sum([
            'time' in param_lower,
            'wavelength' in param_lower,
            'physobs' in param_lower or 'physical observable' in param_lower
        ])

        if category_count > 1:
            # Multiple categories mentioned, treat as general
            return 'general'

        # Check if it contains a single category keyword
        if 'physobs' in param_lower or 'physical observable' in param_lower:
            return 'physobs'
        elif 'wavelength' in param_lower:
            return 'wavelength'
        elif 'time' in param_lower:
            return 'time'

        # Check for common legacy parameter names
        if 'instrument' in param_lower:
            return 'general'

        # Default to general for anything else (period names, etc.)
        return 'general'

    def relink_dataset_usages(self, dry_run, batch_size):
        """Re-link SupportQuotes to DatasetUsages using the fixed parameter fields"""

        # Find DatasetUsages that have 0 supporting quotes
        unlinked_usages = DatasetUsage.objects.filter(
            supporting_quotes__isnull=True
        ).select_related('paper_analysis', 'instrument').order_by('id')

        total_unlinked = unlinked_usages.count()

        if total_unlinked == 0:
            self.stdout.write(self.style.SUCCESS("No unlinked DatasetUsages found!"))
            return 0

        self.stdout.write(f"Found {total_unlinked} DatasetUsages with no linked quotes")

        if dry_run:
            self.stdout.write(self.style.WARNING(f"\n[DRY RUN] Would re-link {total_unlinked} DatasetUsages"))
            return total_unlinked

        # Re-link in batches
        self.stdout.write(f"\nRe-linking {total_unlinked} DatasetUsages in batches of {batch_size}...")

        linked_count = 0
        quotes_linked = 0

        for offset in tqdm(range(0, total_unlinked, batch_size), desc="Processing batches"):
            batch = unlinked_usages[offset:offset + batch_size]

            for dataset_usage in batch:
                # Get the paper analysis for this dataset usage
                paper_analysis = dataset_usage.paper_analysis

                if not paper_analysis:
                    continue

                # Get instrument name from dataset usage
                instrument_name = dataset_usage.instrument.short_name

                # Query existing quotes by instrument and parameter
                # Get instrument-level quotes (parameter="general")
                instrument_quotes = paper_analysis.support_quotes.filter(
                    instrument__icontains=instrument_name[:50],
                    parameter="general"
                )

                # Get period-level quotes (parameter in semantic categories)
                period_quotes = paper_analysis.support_quotes.filter(
                    instrument__icontains=instrument_name[:50],
                    parameter__in=['time', 'wavelength', 'physobs']
                )

                # Link the quotes
                all_quotes = list(instrument_quotes) + list(period_quotes)

                if all_quotes:
                    with transaction.atomic():
                        dataset_usage.supporting_quotes.add(*all_quotes)
                        create_categorized_quote_usage_links(dataset_usage, all_quotes)

                    linked_count += 1
                    quotes_linked += len(all_quotes)

        self.stdout.write(self.style.SUCCESS(f"\n✓ Re-linked {linked_count} DatasetUsages with {quotes_linked} total quotes"))
        return linked_count
