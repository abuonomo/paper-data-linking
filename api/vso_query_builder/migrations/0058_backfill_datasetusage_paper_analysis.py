# Generated manually for backfilling paper_analysis FK

from django.db import migrations


def backfill_paper_analysis(apps, schema_editor):
    """
    Backfill the paper_analysis FK for existing DatasetUsage records.

    Matches each DatasetUsage to its PaperAnalysis using:
    - paper (FK already exists)
    - configuration_name (matches PaperAnalysis.configuration_name)
    """
    DatasetUsage = apps.get_model('vso_query_builder', 'DatasetUsage')
    PaperAnalysis = apps.get_model('vso_query_builder', 'PaperAnalysis')

    # Get all normalized DatasetUsages without paper_analysis set
    usages_to_update = DatasetUsage.objects.filter(
        origin='normalized',
        paper_analysis__isnull=True
    ).select_related('paper')

    total = usages_to_update.count()
    matched = 0
    unmatched = 0

    print(f"\nBackfilling paper_analysis for {total} DatasetUsage records...")

    for usage in usages_to_update:
        # Try to find matching PaperAnalysis
        try:
            paper_analysis = PaperAnalysis.objects.get(
                paper=usage.paper,
                configuration_name=usage.configuration_name
            )
            usage.paper_analysis = paper_analysis
            usage.save(update_fields=['paper_analysis'])
            matched += 1
        except PaperAnalysis.DoesNotExist:
            # No matching PaperAnalysis found
            unmatched += 1
            print(f"  ⚠️  No PaperAnalysis found for usage {usage.id}: "
                  f"paper={usage.paper.bibcode}, config={usage.configuration_name}")
        except PaperAnalysis.MultipleObjectsReturned:
            # Multiple matches - use the first one
            paper_analysis = PaperAnalysis.objects.filter(
                paper=usage.paper,
                configuration_name=usage.configuration_name
            ).first()
            usage.paper_analysis = paper_analysis
            usage.save(update_fields=['paper_analysis'])
            matched += 1
            print(f"  ⚠️  Multiple PaperAnalyses found for usage {usage.id}, using first")

    print(f"\nBackfill complete:")
    print(f"  ✅ Matched: {matched}/{total}")
    print(f"  ❌ Unmatched: {unmatched}/{total}")


def reverse_backfill(apps, schema_editor):
    """Reverse the backfill by setting paper_analysis to NULL."""
    DatasetUsage = apps.get_model('vso_query_builder', 'DatasetUsage')

    # Only clear paper_analysis for records that were backfilled
    # (i.e., normalized records that have paper_analysis set)
    updated = DatasetUsage.objects.filter(
        origin='normalized',
        paper_analysis__isnull=False
    ).update(paper_analysis=None)

    print(f"\nReversed backfill: cleared paper_analysis for {updated} records")


class Migration(migrations.Migration):

    dependencies = [
        ('vso_query_builder', '0057_datasetusage_paper_analysis_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_paper_analysis, reverse_backfill),
    ]
