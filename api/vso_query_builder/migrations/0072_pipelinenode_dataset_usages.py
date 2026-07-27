from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vso_query_builder', '0071_add_pipeline_node'),
    ]

    operations = [
        migrations.AddField(
            model_name='pipelinenode',
            name='dataset_usages',
            field=models.ManyToManyField(
                blank=True,
                related_name='pipeline_nodes',
                to='vso_query_builder.datasetusage',
            ),
        ),
    ]
