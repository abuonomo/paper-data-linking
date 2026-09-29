from django.db import migrations, models


def deduplicate_phenomenon_mentions(apps, schema_editor):
    """
    Keep the oldest PhenomenonMention per (paper_analysis, phenomenon, instrument_name, period_name)
    before enforcing the unique constraint below.
    """
    PhenomenonMention = apps.get_model('vso_query_builder', 'PhenomenonMention')

    seen = {}
    to_delete = []

    for mention in PhenomenonMention.objects.order_by('created_at', 'id'):
        key = (
            str(mention.paper_analysis_id),
            str(mention.phenomenon_id),
            mention.instrument_name,
            mention.period_name,
        )
        if key in seen:
            to_delete.append(mention.pk)
        else:
            seen[key] = mention.pk

    if to_delete:
        PhenomenonMention.objects.filter(pk__in=to_delete).delete()


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('vso_query_builder', '0102_alter_datasetusagevalidation_reject_reason'),
    ]

    operations = [
        migrations.RunPython(
            deduplicate_phenomenon_mentions,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='phenomenonmention',
            constraint=models.UniqueConstraint(
                fields=('paper_analysis', 'phenomenon', 'instrument_name', 'period_name'),
                name='unique_phenomenon_mention_per_period',
            ),
        ),
    ]
