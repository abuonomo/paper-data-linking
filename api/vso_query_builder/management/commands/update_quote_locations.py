from django.core.management.base import BaseCommand
from vso_query_builder.models import DatasetUsage, SupportQuote
from vso_query_builder.tasks import update_supporting_quote_locations_batch_task
from vso_query_builder.utils.storage import read_pdf_bytes
import time
from collections import defaultdict
from tqdm import tqdm


class Command(BaseCommand):
    help = 'Update quote locations for a specific dataset usage or ALL quotes using IR or fast method'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dataset-usage-id', type=str, help='Dataset usage ID to update')
        group.add_argument('--all', action='store_true', help='Update ALL supporting quotes in database')
        parser.add_argument('--method', choices=['ir', 'fast'], default='ir', 
                          help='Method to use: ir (high accuracy) or fast (high speed)')

    def handle(self, *args, **options):
        method = options['method']
        
        if options['all']:
            self.process_all_quotes(method)
        else:
            self.process_dataset_usage_quotes(options['dataset_usage_id'], method)

    def process_dataset_usage_quotes(self, dataset_usage_id, method):
        """Process quotes for a specific dataset usage"""
        try:
            dataset_usage = DatasetUsage.objects.get(id=dataset_usage_id)
            self.stdout.write(f"Found dataset usage: {dataset_usage_id}")
            
            # Get supporting quotes
            supporting_quotes = dataset_usage.supporting_quotes.all()
            quote_count = supporting_quotes.count()
            self.stdout.write(f"Supporting quotes: {quote_count}")
            
            if quote_count == 0:
                self.stdout.write(self.style.WARNING("No supporting quotes found"))
                return
                
            # Check if paper has PDF
            if not dataset_usage.paper.pdf:
                self.stdout.write(self.style.ERROR("No PDF found for this paper"))
                return
                
            self.stdout.write(f"Paper: {dataset_usage.paper.bibcode}")
            self.stdout.write(f"PDF: {dataset_usage.paper.pdf.name}")
            
            # Get paper analysis
            paper_analysis = dataset_usage.paper.paperanalysis_set.first()
            if not paper_analysis:
                self.stdout.write(self.style.ERROR("No paper analysis found"))
                return
                
            self.stdout.write(f"Paper analysis ID: {paper_analysis.id}")
            
            # Process the quotes for this dataset usage
            result = self._process_quotes_for_paper(
                dataset_usage.paper, 
                list(supporting_quotes), 
                method, 
                f"dataset usage {dataset_usage_id}"
            )
            
            self.stdout.write(f"Task result: {result}")
                    
        except DatasetUsage.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Dataset usage {dataset_usage_id} not found"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {e}"))

    def process_all_quotes(self, method):
        """Process ALL quotes in the database, one paper at a time (memory efficient)"""
        from vso_query_builder.models import Paper
        
        # Get papers that have PDFs and quotes (memory efficient - no quote loading yet)
        papers_with_quotes = Paper.objects.filter(
            pdf__isnull=False,
            paperanalysis__support_quotes__isnull=False
        ).distinct().prefetch_related('paperanalysis_set__support_quotes')
        
        if not papers_with_quotes.exists():
            self.stdout.write(self.style.WARNING("No papers with PDFs and quotes found"))
            return
        
        # Count totals efficiently
        total_papers = papers_with_quotes.count()
        total_quotes = SupportQuote.objects.filter(
            paper_analysis__paper__pdf__isnull=False
        ).count()
        
        self.stdout.write(f"\n=== PROCESSING ALL SUPPORTING QUOTES ===")
        self.stdout.write(f"Found {total_quotes} quotes across {total_papers} papers (method: {method})")
        self.stdout.write("")
        
        overall_start_time = time.time()
        processed_papers = 0
        total_found = 0
        total_updated = 0
        skipped_papers = 0
        
        # Process papers one at a time (memory efficient)
        for paper in tqdm(papers_with_quotes, 
                         desc="Processing papers", 
                         unit="paper",
                         total=total_papers):
            try:
                # Get quotes for this paper only (not all quotes at once)
                paper_analysis = paper.paperanalysis_set.first()
                if not paper_analysis:
                    skipped_papers += 1
                    continue
                    
                quotes = list(paper_analysis.support_quotes.all())
                if not quotes:
                    skipped_papers += 1
                    continue
                
                result = self._process_quotes_for_paper_batch(paper, quotes, method)
                processed_papers += 1
                total_found += result['found']
                total_updated += result['updated']
                
            except Exception as e:
                tqdm.write(f"✗ Error processing {paper.bibcode}: {e}")
                skipped_papers += 1
                continue
        
        overall_end_time = time.time()
        overall_time = overall_end_time - overall_start_time
        
        self.stdout.write(f"\n=== FINAL RESULTS ===")
        self.stdout.write(f"Papers processed: {processed_papers}/{total_papers}")
        if skipped_papers:
            self.stdout.write(f"Papers skipped: {skipped_papers}")
        self.stdout.write(f"Total quotes: {total_quotes}")
        self.stdout.write(f"Found locations: {total_found} ({total_found/total_quotes*100:.1f}%)")
        self.stdout.write(f"Updated quotes: {total_updated}")
        self.stdout.write(f"Total time: {overall_time/60:.1f}m {overall_time%60:.0f}s")

    def _process_quotes_for_paper_batch(self, paper, quotes, method):
        """Helper method to process quotes for a single paper with progress bar (used in --all mode)"""
        from paper_data_linking.processing.pdf_text_search import PDFTextSearcher
        
        quote_count = len(quotes)
        pdf_bytes = read_pdf_bytes(paper.pdf)

        # Prepare quote objects for processing
        quote_objects = []
        for quote in quotes:
            quote_objects.append({
                'quote': quote.quote,
                'instrument': quote.instrument,
                'parameter': quote.parameter
            })

        # Process quotes with PDF searcher
        searcher = PDFTextSearcher(pdf_bytes)
        
        if method == 'ir':
            processed_quotes = searcher.find_quotes_ir(quote_objects, debug=False)  # No debug for batch
        elif method == 'fast':
            processed_quotes = searcher.find_quotes_original(quote_objects, debug=False)
        else:
            raise ValueError(f"Unknown method: {method}")
            
        searcher.close()
        
        # Update database with results using tqdm for quote progress
        updated_count = 0
        found_count = 0
        
        with tqdm(total=quote_count, 
                 desc=f"{paper.bibcode[:20]}...", 
                 unit="quote", 
                 leave=False,
                 position=1) as pbar:
            
            for quote, result in zip(quotes, processed_quotes):
                location = result.get('location')
                if location:
                    # Update the database with found location
                    quote.page_number = location.get('page_number', 0)
                    quote.x_coord_start = location.get('x0', 0.0)
                    quote.y_coord_start = location.get('y0', 0.0)
                    quote.x_coord_end = location.get('x1', 0.0)
                    quote.y_coord_end = location.get('y1', 0.0)
                    quote.coordinate_regions = location.get('coordinate_regions', [])
                    quote.save()
                    updated_count += 1
                    found_count += 1
                    pbar.set_postfix(found=f"{found_count}/{quote_count}")
                else:
                    pbar.set_postfix(found=f"{found_count}/{quote_count}")
                
                pbar.update(1)
        
        return {
            "processed_quotes": len(processed_quotes), 
            "found": found_count, 
            "updated": updated_count
        }

    def _process_quotes_for_paper(self, paper, quotes, method, context_description):
        """Helper method to process quotes for a single paper"""
        from paper_data_linking.processing.pdf_text_search import PDFTextSearcher
        
        quote_count = len(quotes)
        
        # Show current quote locations before update
        self.stdout.write(f"  === BEFORE UPDATE ({context_description}) ===")
        for i, quote in enumerate(quotes, 1):
            self.stdout.write(f"  Quote {i}: {quote.quote[:60]}...")
            current_page = quote.page_number if quote.page_number else 0
            self.stdout.write(f"    Current location: page={current_page}, coords=({quote.x_coord_start:.1f}, {quote.y_coord_start:.1f}) to ({quote.x_coord_end:.1f}, {quote.y_coord_end:.1f})")
            if quote.coordinate_regions:
                self.stdout.write(f"    Regions: {len(quote.coordinate_regions)} regions")
        
        # Run the update
        self.stdout.write(f"  === RUNNING UPDATE ({context_description}, method: {method}) ===")
        start_time = time.time()
        
        pdf_bytes = read_pdf_bytes(paper.pdf)
        quote_objects = []
        for quote in quotes:
            quote_objects.append({
                'quote': quote.quote,
                'instrument': quote.instrument,
                'parameter': quote.parameter
            })

        # Use the specified method
        searcher = PDFTextSearcher(pdf_bytes)
        
        # Execute the appropriate method based on command line argument
        if method == 'ir':
            processed_quotes = searcher.find_quotes_ir(quote_objects, debug=True)
        elif method == 'fast':
            # Map 'fast' to the original fast method
            processed_quotes = searcher.find_quotes_original(quote_objects, debug=True)
        else:
            raise ValueError(f"Unknown method: {method}")
        searcher.close()
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        self.stdout.write(f"  Results from PDF searcher:")
        updated_count = 0
        for i, (quote, result) in enumerate(zip(quotes, processed_quotes), 1):
            location = result.get('location')
            if location:
                self.stdout.write(f"  Quote {i}: FOUND on page {location['page_number']}")
                if 'debug' in result:
                    debug_method = result['debug'].get('method', 'unknown')
                    timing = result['debug'].get('timing_ms', 0)
                    self.stdout.write(f"    Method: {debug_method}, Timing: {timing}ms")
                
                # Update the database with found location
                quote.page_number = location.get('page_number', 0)
                quote.x_coord_start = location.get('x0', 0.0)
                quote.y_coord_start = location.get('y0', 0.0)
                quote.x_coord_end = location.get('x1', 0.0)
                quote.y_coord_end = location.get('y1', 0.0)
                quote.coordinate_regions = location.get('coordinate_regions', [])
                quote.save()
                updated_count += 1
                self.stdout.write(f"    ✓ Updated database with new location")
            else:
                self.stdout.write(f"  Quote {i}: NOT FOUND")
                if 'debug' in result:
                    timing = result['debug'].get('timing_ms', 0)
                    self.stdout.write(f"    Timing: {timing}ms")
        
        result = {
            "processed_quotes": len(processed_quotes), 
            "found": sum(1 for q in processed_quotes if q.get('location')), 
            "updated": updated_count
        }
        
        self.stdout.write(f"  ✓ Completed in {processing_time:.1f}s - Found {result['found']}/{quote_count} quotes")
        
        return result