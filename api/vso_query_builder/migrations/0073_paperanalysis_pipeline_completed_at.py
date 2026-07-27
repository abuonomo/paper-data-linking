from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vso_query_builder', '0072_pipelinenode_dataset_usages'),
    ]

    operations = [
        migrations.AddField(
            model_name='paperanalysis',
            name='pipeline_completed_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Set when all downstream pipeline tasks (including usage analysis) have completed.',
            ),
        ),
    ]
