"""Verify that DatasetUsages with standard/budget configs are properly matched."""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'paper_analyzer_app.settings')
django.setup()

from vso_query_builder.models import DatasetUsage
from django.db.models import Count

print("=" * 80)
print("VERIFYING CONFIG MATCHING AFTER BACKFILL")
print("=" * 80)

# Check all normalized dataset usages by configuration
all_normalized = DatasetUsage.objects.filter(origin='normalized').select_related('paper_analysis')

by_config = all_normalized.values('configuration_name').annotate(count=Count('id')).order_by('-count')

print(f"\n📊 DatasetUsages by configuration_name:")
for item in by_config:
    config = item['configuration_name'] or 'None'
    count = item['count']
    print(f"  {config}: {count} records")

print(f"\n🔍 Verifying paper_analysis.configuration_name matches DatasetUsage.configuration_name:")

mismatches = []
for usage in all_normalized:
    if usage.paper_analysis:
        # Check if the configs match
        usage_config = usage.configuration_name
        pa_config = usage.paper_analysis.configuration_name

        if usage_config != pa_config:
            mismatches.append({
                'usage_id': usage.id,
                'paper': usage.paper.bibcode,
                'usage_config': usage_config,
                'pa_config': pa_config,
                'pa_id': usage.paper_analysis.id
            })

if mismatches:
    print(f"\n❌ FOUND {len(mismatches)} MISMATCHES!")
    print(f"\nExamples of mismatches:")
    for mm in mismatches[:10]:
        print(f"  Usage {str(mm['usage_id'])[:8]}... (paper={mm['paper']})")
        print(f"    DatasetUsage.configuration_name: {mm['usage_config']}")
        print(f"    PaperAnalysis.configuration_name: {mm['pa_config']}")
        print(f"    PaperAnalysis.id: {mm['pa_id']}")
        print()
else:
    print(f"\n✅ ALL {all_normalized.count()} records have matching configurations!")
    print("   DatasetUsage.configuration_name == paper_analysis.configuration_name for all records")

# Show specific breakdown for standard and budget configs
print(f"\n📋 Detailed check for 'standard' config:")
standard_usages = all_normalized.filter(configuration_name='standard')
print(f"  Total with config='standard': {standard_usages.count()}")
standard_pa_configs = standard_usages.values('paper_analysis__configuration_name').annotate(count=Count('id'))
for item in standard_pa_configs:
    pa_config = item['paper_analysis__configuration_name'] or 'None'
    count = item['count']
    print(f"    Linked to PaperAnalysis with config='{pa_config}': {count}")

print(f"\n📋 Detailed check for 'budget' config:")
budget_usages = all_normalized.filter(configuration_name='budget')
print(f"  Total with config='budget': {budget_usages.count()}")
if budget_usages.count() > 0:
    budget_pa_configs = budget_usages.values('paper_analysis__configuration_name').annotate(count=Count('id'))
    for item in budget_pa_configs:
        pa_config = item['paper_analysis__configuration_name'] or 'None'
        count = item['count']
        print(f"    Linked to PaperAnalysis with config='{pa_config}': {count}")

print("\n" + "=" * 80)
