import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vso_query_builder', '0070_add_datasetusage_timestamps'),
    ]

    operations = [
        migrations.CreateModel(
            name='PipelineNode',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('stage', models.CharField(choices=[
                    ('paper_analysis', 'Paper Analysis'),
                    ('structuring', 'Structuring'),
                    ('instrument', 'Instrument'),
                    ('grounding', 'Grounding'),
                    ('grounding_substep', 'Grounding Substep'),
                    ('grounding_match', 'Grounding Match'),
                    ('normalization', 'Normalization'),
                    ('normalizer', 'Normalizer'),
                ], max_length=50)),
                ('label', models.CharField(max_length=255)),
                ('status', models.CharField(choices=[
                    ('running', 'Running'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                    ('skipped', 'Skipped'),
                ], default='running', max_length=20)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('analysis', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='pipeline_nodes',
                    to='vso_query_builder.paperanalysis',
                )),
                ('parent', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='children',
                    to='vso_query_builder.pipelinenode',
                )),
                ('llm_calls', models.ManyToManyField(
                    blank=True,
                    related_name='pipeline_nodes',
                    to='vso_query_builder.llmcall',
                )),
            ],
            options={
                'verbose_name': 'Pipeline Node',
                'verbose_name_plural': 'Pipeline Nodes',
            },
        ),
        migrations.AddIndex(
            model_name='pipelinenode',
            index=models.Index(fields=['analysis', 'stage'], name='pipenode_analysis_stage_idx'),
        ),
        migrations.AddIndex(
            model_name='pipelinenode',
            index=models.Index(fields=['parent'], name='pipenode_parent_idx'),
        ),
        migrations.AddIndex(
            model_name='pipelinenode',
            index=models.Index(fields=['status'], name='pipenode_status_idx'),
        ),
    ]
