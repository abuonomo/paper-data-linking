"""
Find 500 papers without text and analyses, sorted by bibcode,
and run the complete normalized workflow on them.

The normalized workflow includes:
1. Text extraction from PDF
2. Paper analysis (instrument details extraction)
3. Structure analysis (convert to structured JSON)
4. Normalization (normalize instrument/time data)
5. Dataset usage creation
6. Dataset usage analysis
"""
from vso_query_builder.models import Paper
from vso_query_builder.tasks import run_batch_normalized_workflow


def main():
    print("=" * 70)
    print("NORMALIZED WORKFLOW BATCH PROCESSOR")
    print("=" * 70)

    # Find papers without text extraction and without paper analyses
    papers_to_process = (
        Paper.objects
        .filter(full_text__isnull=True)
        .filter(paperanalysis__isnull=True)
        .order_by('bibcode')[:500]
    )

    count = papers_to_process.count()
    print(f"\nFound {count} papers without full_text and paperanalysis")

    if count == 0:
        print("No papers to process. Exiting.")
        return

    # Show sample
    print(f"\nFirst 10 bibcodes:")
    for paper in papers_to_process[:10]:
        has_pdf = "✓ PDF" if paper.pdf else "✗ No PDF"
        print(f"  {paper.bibcode:30} {has_pdf}")

    if count > 10:
        print(f"  ... and {count - 10} more")

    # Get paper IDs
    paper_ids = list(papers_to_process.values_list('id', flat=True))

    print(f"\n{'─' * 70}")
    print("STARTING BATCH WORKFLOW")
    print(f"{'─' * 70}")
    print(f"Total papers: {len(paper_ids)}")
    print("Configuration: standard")
    print("\nWorkflow steps per paper:")
    print("  1. Extract text from PDF")
    print("  2. Analyze paper (extract instrument details)")
    print("  3. Structure analysis (convert to JSON)")
    print("  4. Normalize data (instrument/time normalization)")
    print("  5. Create dataset usages")
    print("  6. Analyze dataset usages")

    # Convert UUIDs to strings for JSON serialization
    paper_id_strings = [str(pid) for pid in paper_ids]

    # Start the workflow
    result = run_batch_normalized_workflow.delay(paper_id_strings, configuration_name='standard')

    print(f"\n{'─' * 70}")
    print("WORKFLOW STARTED")
    print(f"{'─' * 70}")
    print(f"Task ID: {result.id}")
    print(f"Status: {result.status}")
    print("\nThe workflow is running asynchronously via Celery.")
    print("You can monitor progress in the Django admin or Celery logs.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
