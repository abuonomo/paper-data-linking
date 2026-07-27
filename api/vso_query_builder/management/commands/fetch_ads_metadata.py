from django.core.management.base import BaseCommand
from django.utils import timezone
from vso_query_builder.models import Paper
from vso_query_builder.ads_service import ADSService
import time
from tqdm import tqdm


class Command(BaseCommand):
    help = 'Fetch and cache ADS metadata for all papers'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=50,
            help='Number of papers to process in each ADS API batch (default: 50)'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0.5,
            help='Delay between API calls in seconds (default: 0.5)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-fetch metadata even if already cached'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually updating papers'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        delay = options['delay']
        force = options['force']
        dry_run = options['dry_run']

        # Get papers that need ADS metadata
        if force:
            papers = Paper.objects.all()
            total_count = papers.count()
            self.stdout.write(f'Found {total_count} papers to update (force mode)')
        else:
            papers = Paper.objects.filter(ads_metadata_fetched=False)
            total_count = papers.count()
            self.stdout.write(f'Found {total_count} papers without ADS metadata')

        if total_count == 0:
            self.stdout.write(
                self.style.SUCCESS('No papers need metadata updates!')
            )
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN MODE - No changes will be made!')
            )
        
        ads_service = ADSService() if not dry_run else None
        processed = 0
        failed = 0

        # Convert queryset to list and process in batches
        papers_list = list(papers)
        total_batches = (len(papers_list) + batch_size - 1) // batch_size  # Ceiling division
        
        # Create progress bars
        batch_progress = tqdm(
            total=total_batches,
            desc="Processing batches",
            unit="batch",
            position=0
        )
        
        paper_progress = tqdm(
            total=total_count,
            desc="Processing papers",
            unit="paper",
            position=1
        )

        # Process papers in batches
        for batch_idx in range(0, len(papers_list), batch_size):
            batch = papers_list[batch_idx:batch_idx + batch_size]
            batch_bibcodes = [paper.bibcode for paper in batch]
            
            batch_progress.set_description(f"Batch {batch_idx//batch_size + 1}/{total_batches}")
            
            try:
                if dry_run:
                    # In dry-run mode, show what would be done for the batch
                    self.stdout.write(
                        self.style.WARNING(f'[DRY RUN] Would fetch metadata for batch of {len(batch)} papers:')
                    )
                    for paper in batch:
                        self.stdout.write(f'  - {paper.bibcode}')
                        if paper.title:
                            self.stdout.write(f'    Current title: {paper.title[:50]}...')
                        else:
                            self.stdout.write('    No title currently cached')
                    
                    processed += len(batch)
                    paper_progress.update(len(batch))
                    
                    # Shorter delay for dry-run
                    if delay > 0:
                        time.sleep(delay * 0.2)
                    
                else:
                    # Actually fetch metadata in batch
                    batch_progress.set_description(f"Fetching batch {batch_idx//batch_size + 1}/{total_batches}")
                    
                    # Batch fetch ADS metadata
                    batch_results = ads_service.get_papers_batch_details(batch_bibcodes, include_abstract=True)
                    
                    # Update each paper in the batch
                    for paper in batch:
                        bibcode = paper.bibcode
                        ads_details = batch_results.get(bibcode, {})
                        
                        if ads_details.get('title'):  # Only update if we got data
                            title = ads_details.get('title', paper.bibcode)
                            authors = ads_details.get('authors', [])
                            year = ads_details.get('year')
                            journal = ads_details.get('journal')
                            
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'✓ {bibcode}: "{title[:50]}..." ({year}, {len(authors)} authors)'
                                )
                            )
                            
                            # Update paper with ADS metadata
                            paper.title = title
                            paper.authors = authors
                            paper.year = year
                            paper.journal = journal
                            paper.journal_abbrev = ads_details.get('journal_abbrev')
                            paper.abstract = ads_details.get('abstract')
                            paper.ads_metadata_fetched = True
                            paper.ads_metadata_updated = timezone.now()
                            paper.save()
                            
                            processed += 1
                        else:
                            self.stdout.write(
                                self.style.WARNING(f'⚠ No metadata found for {bibcode}')
                            )
                            failed += 1
                        
                        paper_progress.update(1)
                    
                    # Add delay between batches (much less frequent now!)
                    if delay > 0:
                        time.sleep(delay)
                    
            except Exception as e:
                # If batch fails, mark all papers in batch as failed
                failed += len(batch)
                paper_progress.update(len(batch))
                
                if dry_run:
                    self.stdout.write(
                        self.style.ERROR(f'[DRY RUN] Batch would fail with error: {e}')
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f'✗ Batch failed: {e}')
                    )
                    # Continue with next batch
                continue

            batch_progress.update(1)

        batch_progress.close()
        paper_progress.close()
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'\nDRY RUN COMPLETED! Would have processed: {processed}, failed: {failed}'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nCompleted! Processed: {processed}, Failed: {failed}'
                )
            )