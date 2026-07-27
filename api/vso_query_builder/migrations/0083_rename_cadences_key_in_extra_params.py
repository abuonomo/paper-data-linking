from django.db import migrations


def rename_cadences_to_cadence(apps, schema_editor):
    """Rename 'cadences' key to 'cadence' in DatasetUsage.extra_params."""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE vso_query_builder_datasetusage
            SET extra_params = (extra_params - 'cadences') || jsonb_build_object('cadence', extra_params->'cadences')
            WHERE extra_params ? 'cadences'
        """)


def rename_cadence_to_cadences(apps, schema_editor):
    """Reverse: rename 'cadence' key back to 'cadences' in DatasetUsage.extra_params."""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE vso_query_builder_datasetusage
            SET extra_params = (extra_params - 'cadence') || jsonb_build_object('cadences', extra_params->'cadence')
            WHERE extra_params ? 'cadence'
        """)


class Migration(migrations.Migration):

    dependencies = [
        ("vso_query_builder", "0082_backfill_null_cost_for_zero_cost_calls"),
    ]

    operations = [
        migrations.RunPython(
            rename_cadences_to_cadence,
            rename_cadence_to_cadences,
        ),
    ]
